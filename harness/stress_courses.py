#!/usr/bin/env python3
"""Reproduce the declared input/dependency study without a model or network."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness import course_evaluation_cases as corpus  # noqa: E402

COPY_FILES = (
    "harness/course_workflow.py", "harness/course_sources.py", "harness/model_budget.py",
    "harness/openai_course_client.py", "harness/course_records.schema.json",
    "harness/prompts/extract_courses.md", "harness/render_courses.py", "eval/check_courses.py",
    "fixtures/courses/course-sources.json", "tests/test_budgeted_course_workflow.py",
    "tests/test_course_records.py", "harness/course_evaluation_cases.py",
    "fixtures/courses/course-evaluation-cases.json",
)
SOURCE_CASES = {
    "source-base.json": "S00-base", "source-duplicate.json": "S02-identical-repeated-row",
    "source-conflict.json": "S05-conflicting-offerings", "source-unapproved.json": "S08-unapproved-url",
}
CANDIDATES = ("candidate-base.json", "candidate-conflict-bad.json", "candidate-conflict-abstain.json")
HISTORICAL_HASH = "18ad08ca77ed6d9244ba72e1b825617f6d6e5cd24f082aa799bb7c1088c9f67d"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _json(path, value):
    _write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def _read(root, relative):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("study input escapes the repository: " + relative)
    return path.read_bytes()


def _prepared_inputs(root):
    data_root = "fixtures/courses/stress/"
    declaration = _read(root, data_root + "protocol.json")
    protocol = json.loads(declaration)
    if protocol["protocol_version"] != 1 or protocol["source_case_ids"] != SOURCE_CASES:
        raise ValueError("unsupported stress-study declaration")
    catalog_bytes = _read(root, "fixtures/courses/course-evaluation-cases.json")
    if _sha(catalog_bytes) != protocol["source_catalog_sha256"]:
        raise ValueError("stress source catalog differs from its declaration")
    base = _read(root, "fixtures/courses/course-sources.json")
    generated = corpus.generate_cases(base, json.loads(catalog_bytes))
    inputs = {name: generated[case_id]["bytes"] for name, case_id in SOURCE_CASES.items()}
    inputs.update({name: _read(root, data_root + name) for name in CANDIDATES})
    if set(protocol["inputs"]) != set(inputs):
        raise ValueError("stress input set differs from its declaration")
    for name, data in inputs.items():
        if _sha(data) != protocol["inputs"][name]["sha256"]:
            raise ValueError("retained stress input hash differs: " + name)
    historical = _read(root, data_root + "compulsory2-checker.py.txt")
    if _sha(historical) != HISTORICAL_HASH or protocol["historical_control"]["sha256"] != HISTORICAL_HASH:
        raise ValueError("historical checker control differs from the accepted checkpoint")
    return protocol, inputs, historical, declaration


def _fresh_directory(root):
    out = (root / "out").resolve()
    destination = (root / "out/course-stress").resolve()
    training = (root / "out/training").resolve()
    if (not out.is_relative_to(root) or destination == out or not destination.is_relative_to(out)
            or destination == training or destination.is_relative_to(training)
            or training.is_relative_to(destination)):
        raise ValueError("stress evidence must stay under out/, outside normal training output")
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = destination / ("run-" + stamp + "-" + uuid.uuid4().hex[:8])
    directory.mkdir(exist_ok=False)
    return directory


def _published(root):
    return {name: _sha((root / name).read_bytes()) if (root / name).is_file() else None
            for name in ("out/training/courses.json", "out/training/comparison.md")}


def run_study(root=ROOT):
    root = Path(root).resolve(strict=True)
    protocol, inputs, historical, original_declaration = _prepared_inputs(root)
    source = {name: _read(root, name) for name in COPY_FILES}
    driver_bytes = _read(root, "harness/course_stress_driver.py")
    directory = _fresh_directory(root)
    source_copy = directory / "source-copy"
    for name, data in source.items():
        _write(source_copy / name, data)
    for name, data in inputs.items():
        _write(directory / "inputs" / name, data)
    _write(source_copy / "historical-control/check_courses.py", historical)
    _write(directory / "run_study.py", driver_bytes)
    protocol["declared_at_utc"] = datetime.now(timezone.utc).isoformat()
    protocol["verified_source_sha256"] = {name: _sha(data) for name, data in source.items()}
    _json(directory / "protocol.json", protocol)
    before_published = _published(root)
    manifest = {"report_version": 1, "execution_kind": "offline_recorded_candidate_replay",
                "not_model_accuracy": True, "live_provider_requests": 0,
                "python_version": platform.python_version(), "platform": platform.platform(),
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "original_protocol_sha256": _sha(original_declaration),
                "declared_protocol_sha256": _sha((directory / "protocol.json").read_bytes()),
                "source_sha256": protocol["verified_source_sha256"],
                "runner_sha256": _sha(_read(root, "harness/stress_courses.py")),
                "driver_sha256": _sha(driver_bytes), "historical_checker_sha256": _sha(historical),
                "published_before": before_published}
    _json(directory / "run-manifest.json", manifest)
    report = {"status": "incomplete", "live_provider_requests": 0, "not_model_accuracy": True}
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        with (directory / "study.log").open("wb") as stream:
            process = subprocess.Popen([sys.executable, "-B", str(directory / "run_study.py"),
                        str(source_copy), str(directory)], cwd=source_copy, env=env,
                        stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True)
            try:
                code = process.wait(timeout=180)
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                raise
        report["driver_exit_code"] = code
        if code != 0:
            raise ValueError("stress driver failed; inspect retained study.log")
        study = json.loads((directory / "study-results.json").read_bytes())
        if study["status"] != "all_declared_controls_met" or study["case_count"] != 10:
            raise ValueError("declared stress cases are incomplete")
        if [row["case_id"] for row in study["rows"]] != [case["id"] for case in protocol["cases"]]:
            raise ValueError("stress result case set differs from the declaration")
        for name, data in source.items():
            if _sha(_read(root, name)) != _sha(data) or (source_copy / name).read_bytes() != data:
                raise ValueError("source changed during the stress study: " + name)
        for name, data in inputs.items():
            if (directory / "inputs" / name).read_bytes() != data:
                raise ValueError("stress input changed: " + name)
        if (source_copy / "historical-control/check_courses.py").read_bytes() != historical:
            raise ValueError("historical comparison component changed")
        report.update(status="complete", declared_controls_met=10)
        lines = ["# Offline course stress study", "",
                 "Recorded candidate replay and simulated dependencies; no live provider requests or model-accuracy claim.", "",
                 "| Case | Observed outcome | Declared expectation met |", "|---|---|---|"]
        for row in study["rows"]:
            observed = row["result"]["status"] if "result" in row else "CLI exit " + str(row["cli_exit_code"])
            if "later_case_result" in row:
                observed += "; later " + row["later_case_result"]["status"]
            lines.append("| " + row["case_id"] + " | " + observed + " | yes |")
        lines.extend(["", "The historical checker accepting the bad selection is an intentionally reproduced failure. The current checker blocks the identical first candidate. Existing dependency containment absorbs the injected timeout and missing-usage faults.",
                      "", "See docs/exam/stress-study-2026-11-10.md for interpretation, provenance and limitations. Student qualitative confirmation remains separate.", ""])
        _write(directory / "results.md", "\n".join(lines).encode())
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        report["failure_type"] = type(error).__name__
    finally:
        after_published = _published(root)
        report["normal_publication_unchanged"] = after_published == before_published
        if not report["normal_publication_unchanged"]:
            report["status"] = "incomplete"
        manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["published_after"] = after_published
        manifest["run_output_sha256"] = {str(p.relative_to(directory)): _sha(p.read_bytes())
            for p in sorted(directory.rglob("*")) if p.is_file() and p.name not in {"run-manifest.json", "results.json"}}
        _json(directory / "run-manifest.json", manifest)
        report["manifest_sha256"] = _sha((directory / "run-manifest.json").read_bytes())
        _json(directory / "results.json", report)
    return directory, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", required=True,
                        help="replay retained candidates with an in-memory provider double")
    parser.parse_args(argv)
    try:
        directory, result = run_study()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("ERROR: stress preflight failed: " + str(error), file=sys.stderr)
        return 2
    print("Evidence: " + str(directory.relative_to(ROOT)))
    print("Declared controls met: " + str(result.get("declared_controls_met", "incomplete")) + "/10")
    print("Live provider requests: 0")
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

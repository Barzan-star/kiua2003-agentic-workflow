#!/usr/bin/env python3
"""Run offline controls or explicitly approved, budgeted course evaluation."""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import course_evaluation_cases as corpus
from harness import course_evaluation_scoring as scoring
from harness import course_sources


RUNS_ROOT = ROOT / "out" / "course-evaluations"
BASE_PATH = ROOT / "fixtures" / "courses" / "course-sources.json"
CATALOG_PATH = ROOT / "fixtures" / "courses" / "course-evaluation-cases.json"
REFERENCE_PATH = ROOT / "fixtures" / "courses" / "course-evaluation-reference.json"
CHECKER_PATH = ROOT / "eval" / "check_courses.py"
RENDERER_PATH = ROOT / "harness" / "render_courses.py"
SCHEMA_PATH = ROOT / "harness" / "course_records.schema.json"
PROMPT_PATH = ROOT / "harness" / "prompts" / "extract_courses.md"
RUNNER_PATH = ROOT / "harness" / "run_courses.sh"
COMPONENT_TIMEOUT_SECONDS = 30
REPORT_VERSION = 2
ACTUAL_REPORT_VERSION = 1
PINNED_OPENAI_VERSION = "3.46.0"
ACTUAL_MODEL = "gpt-6-luna"
ACTUAL_REASONING_EFFORT = "low"
ACTUAL_TIMEOUT_SECONDS = 90
EXPECTED_PREFLIGHT_REJECTIONS = frozenset({"S07-unapproved-course", "S08-unapproved-url"})
TRAINING_PATHS = (
    ROOT / "out" / "training" / "course-sources.json",
    ROOT / "out" / "training" / "courses.json",
    ROOT / "out" / "training" / "comparison.md",
)
MUTATION_SOURCE_CASES = {
    "C01-swapped-dates": "S00-base",
    "C02-invented-date": "S00-base",
    "C03-invented-fee": "S00-base",
    "C04-zero-as-unknown": "S00-base",
    "C05-omit-admissions-alternative": "S00-base",
    "C06-omit-module-prerequisite": "S00-base",
    "C07-deadline-means-open": "S00-base",
    "C08-drop-materials-qualification": "S00-base",
    "C09-follow-injection": "S06-hostile-source-text",
}
EXPECTED_MUTATION_CHECKS = {
    "C01-swapped-dates": "reject",
    "C02-invented-date": "reject",
    "C03-invented-fee": "reject",
    "C04-zero-as-unknown": "pass",
    "C05-omit-admissions-alternative": "pass",
    "C06-omit-module-prerequisite": "pass",
    "C07-deadline-means-open": "reject",
    "C08-drop-materials-qualification": "pass",
    "C09-follow-injection": "reject",
}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _json_bytes(value)
    descriptor, name = tempfile.mkstemp(prefix=".evaluation-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _unique_run_directory():
    out_root = (ROOT / "out").resolve()
    destination = RUNS_ROOT.resolve()
    training = (ROOT / "out" / "training").resolve()
    if (".." in RUNS_ROOT.parts or not out_root.is_relative_to(ROOT.resolve())
            or destination == out_root or not destination.is_relative_to(out_root)
            or destination == training or destination.is_relative_to(training)
            or training.is_relative_to(destination)):
        raise ValueError("evaluation evidence must use a separate directory beneath out/, outside out/training/")
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    for _attempt in range(20):
        run_id = f"run-{stamp}-{secrets.token_hex(4)}"
        path = RUNS_ROOT / run_id
        try:
            path.mkdir()
        except FileExistsError:
            continue
        return run_id, path
    raise RuntimeError("could not create a unique replay run directory")


def _hash_file(path):
    if not path.is_file():
        return None
    return _sha256(path.read_bytes())


def _protected_snapshot():
    paths = tuple(dict.fromkeys((BASE_PATH, CATALOG_PATH, REFERENCE_PATH,
                                *_implementation_paths(), *TRAINING_PATHS)))
    return {
        str(path.relative_to(ROOT)): {
            "exists": path.is_file(),
            "sha256": _hash_file(path),
        }
        for path in paths
    }


def _case_facts(reference, case_id):
    facts = [fact for fact in reference["base_facts"] if case_id in fact["case_ids"]]
    facts.extend(
        fact
        for override in reference["case_overrides"] if override["case_id"] == case_id
        for fact in override["facts"]
    )
    return facts


def _evidence(fact):
    source = fact["source"]
    if fact["expected_unknown"]:
        return []
    return [{"section_index": source["section_index"], "quote": source["quote"]}]


def build_reference_candidate(source_bundle, reference, case_id):
    """Build a positive synthetic control from reviewed facts and source quotes."""
    facts = _case_facts(reference, case_id)
    by_course = {course_id: {} for course_id in corpus.APPROVED_IDS}
    prerequisites = {course_id: [] for course_id in corpus.APPROVED_IDS}
    missing = {course_id: [] for course_id in corpus.APPROVED_IDS}
    contracts = reference["candidate_unknown_contract"]["by_fact_id"]

    for fact in facts:
        course_id = fact["course_id"]
        field = fact["candidate_value_field"]
        if field == "prerequisites[*].text":
            prerequisites[course_id].append({
                "text": fact["expected_value"],
                "evidence": _evidence(fact),
            })
            continue
        parent_key, child_key = field.split(".", 1)
        parent = by_course[course_id].setdefault(parent_key, {})
        parent[child_key] = fact["expected_value"]
        parent["evidence"] = _evidence(fact)
        if fact["expected_unknown"]:
            missing_field = contracts[fact["fact_id"]]["missing_field"]
            if missing_field not in missing[course_id]:
                missing[course_id].append(missing_field)

    source_by_id = {item["course_id"]: item for item in source_bundle["courses"]}
    records = []
    for course_id in corpus.APPROVED_IDS:
        source = source_by_id[course_id]
        record = {
            "course_id": source["course_id"],
            "title": source["title"],
            "source_url": source["source_url"],
            "retrieved_at": source["retrieved_at"],
            **by_course[course_id],
            "prerequisites": prerequisites[course_id],
            "missing_or_uncertain_fields": missing[course_id],
        }
        records.append(record)
    return {"schema_version": 1, "courses": records}


def _find_record(candidate, course_id):
    return next(item for item in candidate["courses"] if item["course_id"] == course_id)


def apply_candidate_mutation(candidate, source_bundle, reference, catalog, mutation_id):
    """Create one deterministic negative or omission control from a parent."""
    mutated = copy.deepcopy(candidate)
    intro = _find_record(mutated, "automation-introduction")
    pls = _find_record(mutated, "automation-pls")
    robot = _find_record(mutated, "automation-robot-regulation")

    if mutation_id == "C01-swapped-dates":
        deadline = intro["application_deadline"]["date"]
        intro["application_deadline"]["date"] = intro["start_date"]["date"]
        intro["start_date"]["date"] = deadline
    elif mutation_id == "C02-invented-date":
        robot["application_deadline"] = copy.deepcopy(pls["application_deadline"])
    elif mutation_id == "C03-invented-fee":
        robot["study_fee_nok"] = {
            "amount": 999,
            "evidence": copy.deepcopy(intro["study_fee_nok"]["evidence"]),
        }
    elif mutation_id == "C04-zero-as-unknown":
        intro["study_fee_nok"] = {"amount": None, "evidence": []}
        intro["missing_or_uncertain_fields"].append("study_fee_nok")
    elif mutation_id == "C05-omit-admissions-alternative":
        full_source_text = source_bundle["courses"][0]["source_sections"][7]["text"]
        formal_fact = next(
            fact for fact in _case_facts(reference, "S00-base")
            if fact["fact_id"] == "intro-admission-formal-route"
        )
        intro["prerequisites"] = [{
            "text": formal_fact["expected_value"],
            "evidence": [{"section_index": 7, "quote": full_source_text}],
        }]
    elif mutation_id == "C06-omit-module-prerequisite":
        pls["prerequisites"] = []
        pls["missing_or_uncertain_fields"].append("prerequisites")
    elif mutation_id == "C07-deadline-means-open":
        intro["application_status"] = {
            "value": "open_for_application",
            "evidence": copy.deepcopy(intro["application_deadline"]["evidence"]),
        }
        intro["missing_or_uncertain_fields"] = [
            item for item in intro["missing_or_uncertain_fields"] if item != "application_status"
        ]
    elif mutation_id == "C08-drop-materials-qualification":
        intro["materials_qualification"] = {"value": None, "evidence": []}
        intro["missing_or_uncertain_fields"].append("materials_qualification")
    elif mutation_id == "C09-follow-injection":
        payload = next(
            item["transformation"]["payload"] for item in catalog["source_cases"]
            if item["case_id"] == "S06-hostile-source-text"
        )
        intro["application_deadline"] = {
            "date": "2030-12-31",
            "evidence": [{"section_index": 0, "quote": payload}],
        }
        intro["study_fee_nok"] = {
            "amount": 999999,
            "evidence": [{"section_index": 0, "quote": payload}],
        }
    else:
        raise ValueError(f"unknown candidate mutation: {mutation_id}")
    return mutated


def _run_checker(source_path, candidate_path, feedback_path):
    command = [
        sys.executable, str(CHECKER_PATH),
        "--source", str(source_path), "--candidate", str(candidate_path),
    ]
    result = _run_component(command)
    exit_code = result["exit_code"]
    status = "pass" if exit_code == 0 else "reject" if exit_code == 1 else "error"
    feedback = {
        "invocation_method": "subprocess CLI: eval/check_courses.py",
        "command": command,
        "cwd": str(ROOT),
        **result,
        "status": status,
    }
    _write_json(feedback_path, feedback)
    return {**feedback, "feedback_path": str(feedback_path.relative_to(ROOT))}


def _run_component(command):
    """Capture local component failures without inventing a child exit code."""
    try:
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True,
                                check=False, timeout=COMPONENT_TIMEOUT_SECONDS)
        return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                "failure_kind": None, "timeout_seconds": COMPONENT_TIMEOUT_SECONDS}
    except subprocess.TimeoutExpired as error:
        decode = lambda value: value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        return {"exit_code": None, "stdout": decode(error.stdout), "stderr": decode(error.stderr),
                "failure_kind": "timeout", "timeout_seconds": COMPONENT_TIMEOUT_SECONDS,
                "error_message": str(error)}
    except OSError as error:
        return {"exit_code": None, "stdout": "", "stderr": "", "failure_kind": "dispatch_error",
                "timeout_seconds": COMPONENT_TIMEOUT_SECONDS, "error_message": str(error)}


def _run_renderer(candidate_path, render_directory):
    json_output = render_directory / "rendered-candidate.json"
    markdown_output = render_directory / "comparison.md"
    command = [
        sys.executable, str(RENDERER_PATH), "--input", str(candidate_path),
        "--json-output", str(json_output), "--markdown-output", str(markdown_output),
    ]
    render_directory.mkdir(parents=True, exist_ok=True)
    result = _run_component(command)
    status = "pass" if result["exit_code"] == 0 else "error"
    return {
        "invocation_method": "subprocess CLI: harness/render_courses.py",
        "command": command,
        "cwd": str(ROOT),
        **result,
        "status": status,
        "json_output": str(json_output.relative_to(ROOT)) if json_output.is_file() else None,
        "markdown_output": str(markdown_output.relative_to(ROOT)) if markdown_output.is_file() else None,
        "output_sha256": {
            "json": _hash_file(json_output),
            "markdown": _hash_file(markdown_output),
        },
    }


def _write_candidate(directory, candidate, provenance):
    directory.mkdir(parents=True, exist_ok=True)
    candidate_path = directory / "candidate.json"
    candidate_bytes = _json_bytes(candidate)
    candidate_path.write_bytes(candidate_bytes)
    manifest = {**provenance, "candidate_sha256": _sha256(candidate_bytes)}
    _write_json(directory / "provenance.json", manifest)
    return candidate_path, manifest


def _implementation_paths():
    return (
        ROOT / "harness" / "course_evaluation_cases.py",
        ROOT / "harness" / "course_evaluation_scoring.py",
        ROOT / "harness" / "evaluate_courses.py",
        ROOT / "harness" / "course_workflow.py",
        ROOT / "harness" / "model_budget.py",
        ROOT / "harness" / "openai_course_client.py",
        ROOT / "harness" / "course_sources.py",
        CHECKER_PATH, RENDERER_PATH, SCHEMA_PATH, PROMPT_PATH, RUNNER_PATH,
        ROOT / "requirements-model.txt",
    )


def _hash_inputs(generated):
    inputs = (BASE_PATH, CATALOG_PATH, REFERENCE_PATH, SCHEMA_PATH)
    result = {
        "source_fixture_sha256": _hash_file(BASE_PATH),
        "catalog_sha256": _hash_file(CATALOG_PATH),
        "reference_sha256": _hash_file(REFERENCE_PATH),
        "schema_sha256": _hash_file(SCHEMA_PATH),
        "model_requirement_sha256": _hash_file(ROOT / "requirements-model.txt"),
        "implementation_sha256": {
            str(path.relative_to(ROOT)): _hash_file(path) for path in _implementation_paths()
        },
        "input_files_sha256": {
            str(path.relative_to(ROOT)): _hash_file(path) for path in inputs
        },
        "generated_case_inputs_sha256": {
            case_id: _sha256(item["bytes"]) for case_id, item in generated.items()
        },
    }
    return result


def check_scoring_expectation(score, reference, case_id, mutation_id=None):
    """Check the fixed control's expected score effects, separately from its checker verdict."""
    facts = _case_facts(reference, case_id)
    expected_states = {fact["fact_id"]: "correct" for fact in facts
                       if fact["candidate_value_field"] in scoring.VALUE_FIELDS}
    expected_text = {fact["fact_id"]: True for fact in facts if not fact["expected_unknown"]
                     and fact["candidate_value_field"] in {*scoring.KNOWN_TEXT_FIELDS, scoring.PREREQUISITE_FIELD}}
    state_changes = {
        "C01-swapped-dates": {"intro-deadline": "incorrect", "intro-start": "incorrect"},
        "C02-invented-date": {"robot-deadline-unknown": "incorrect"},
        "C03-invented-fee": {"robot-study-fee-unknown": "incorrect"},
        "C04-zero-as-unknown": {"intro-study-fee": "missing"},
        "C05-omit-admissions-alternative": {},
        "C06-omit-module-prerequisite": {},
        "C07-deadline-means-open": {"intro-status-not-stated": "incorrect"},
        "C08-drop-materials-qualification": {"intro-materials-may-cost-extra": "missing"},
        "C09-follow-injection": {"intro-deadline": "incorrect", "intro-study-fee": "incorrect"},
    }
    text_omissions = {
        "C05-omit-admissions-alternative": corpus.ADMISSIONS_ATOMS["automation-introduction"] - {"intro-admission-formal-route"},
        "C06-omit-module-prerequisite": {"pls-module-1-prerequisite"},
        "C08-drop-materials-qualification": {"intro-materials-may-cost-extra"},
    }
    if mutation_id is not None:
        if mutation_id not in state_changes or MUTATION_SOURCE_CASES[mutation_id] != case_id:
            raise ValueError("scoring control uses an unknown mutation or the wrong source case")
        expected_states.update(state_changes[mutation_id])
        expected_text.update({fact_id: False for fact_id in text_omissions.get(mutation_id, ())})
    differences = []
    expected_provenance = "mutated_candidate" if mutation_id else "synthetic_reference"
    if not isinstance(score, dict):
        differences.append("candidate was not scored")
        return {"met": False, "differences": differences,
                "expected_value_states": expected_states, "expected_text_coverage": expected_text}
    if score.get("case_id") != case_id or score.get("provenance_class") != expected_provenance:
        differences.append("score has the wrong source case or provenance")
    if score.get("report_version") != REPORT_VERSION:
        differences.append("score has an unsupported report version")
    if score.get("candidate_status") != "scoreable":
        differences.append("control candidate is unscorable")

    def inspect_rows(key, expected, value_key):
        rows = score.get(key)
        if (not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("fact_id"), str) for row in rows)
                or len(rows) != len(expected) or {row["fact_id"] for row in rows} != set(expected)):
            differences.append(f"{key} has missing, duplicate, or unexpected fact IDs")
            return
        for row in rows:
            wanted = expected[row["fact_id"]]
            actual = row.get(value_key)
            if type(actual) is not type(wanted) or actual != wanted:
                differences.append(f"{row['fact_id']}: expected {value_key}={wanted!r}; found {actual!r}")

    inspect_rows("value_results", expected_states, "state")
    inspect_rows("text_atom_results", expected_text, "covered")
    expected_counts = {state: sum(value == state for value in expected_states.values())
                       for state in ("correct", "missing", "incorrect")}
    expected_prerequisites = {fact["fact_id"] for fact in facts if fact["candidate_value_field"] == scoring.PREREQUISITE_FIELD}
    totals = {
        "value_slot_denominator": len(expected_states),
        "value_slot_counts": expected_counts,
        "required_text_denominator": len(expected_text),
        "required_text_covered": sum(expected_text.values()),
        "prerequisite_atom_denominator": len(expected_prerequisites),
        "prerequisite_atoms_covered": sum(expected_text[fact_id] for fact_id in expected_prerequisites),
        "unscorable_value_slots": 0,
    }
    for key, expected in totals.items():
        if score.get(key) != expected:
            differences.append(f"{key} disagrees with the control's expected per-fact results")
    return {"met": not differences, "differences": differences,
            "expected_value_states": expected_states, "expected_text_coverage": expected_text}


def _summarise_results(source_results, mutation_results, source_scores, mutation_scores, reference=None):
    reference = scoring.load_reviewed_reference()[0] if reference is None else reference
    accepted = [item for item in source_results if item["expected_preflight"] == "accept"]
    rejected = [item for item in source_results if item["expected_preflight"] == "reject"]
    source_rejection_success = sum(item["outcome_matches_expectation"] for item in rejected)
    unexpected_failures = sum(
        item["checker"] is None or item["checker"]["status"] != "pass"
        or item["renderer"] is None or item["renderer"]["status"] != "pass"
        for item in accepted
    )
    preflight_matches = sum(item["outcome_matches_expectation"] for item in source_results)
    rejection_controls = [item for item in mutation_results if item["expected_checker_status"] == "reject"]
    sensitivity_controls = [item for item in mutation_results if item["expected_checker_status"] == "pass"]
    expected_rejection_success = sum(item["checker_expectation_met"] for item in rejection_controls)
    sensitivity_success = sum(item["checker_expectation_met"] for item in sensitivity_controls)
    required_mutant_renders = [item for item in mutation_results if item.get("checker") and item["checker"]["status"] == "pass"]
    mutant_render_failures = sum(
        item["renderer"] is None or item["renderer"]["status"] != "pass"
        for item in required_mutant_renders
    )
    synthetic_summary = scoring.aggregate_scores(source_scores)
    mutant_summary = scoring.aggregate_scores(mutation_scores)
    expected_source_ids = {item[0] for item in corpus.CASE_TRANSFORMS}
    expected_positive_ids = expected_source_ids - {"S07-unapproved-course", "S08-unapproved-url"}
    expected_mutation_ids = set(MUTATION_SOURCE_CASES)
    source_by_case = {item["case_id"]: item for item in source_scores}
    mutants_by_id = {item.get("mutation_id"): item for item in mutation_scores}
    positive_scoring_controls = {case_id: check_scoring_expectation(source_by_case.get(case_id), reference, case_id)
                                 for case_id in sorted(expected_positive_ids)}
    mutation_scoring_controls = {mutation_id: check_scoring_expectation(mutants_by_id.get(mutation_id), reference,
                                MUTATION_SOURCE_CASES[mutation_id], mutation_id)
                                for mutation_id in sorted(expected_mutation_ids)}
    complete = (
        len(source_results) == 9 and {item["case_id"] for item in source_results} == expected_source_ids
        and len(mutation_results) == 9 and {item["mutation_id"] for item in mutation_results} == expected_mutation_ids
        and len(source_scores) == 7 and set(source_by_case) == expected_positive_ids
        and len(mutation_scores) == 9 and set(mutants_by_id) == expected_mutation_ids
    )
    positive_scores_met = sum(item["met"] for item in positive_scoring_controls.values())
    mutation_scores_met = sum(item["met"] for item in mutation_scoring_controls.values())
    for aggregate, expected_count in ((synthetic_summary, 7), (mutant_summary, 9)):
        aggregate["expected_candidate_count"] = expected_count
        aggregate["expected_value_slots"] = expected_count * scoring.SCALAR_DENOMINATOR
        aggregate["not_scored_candidate_count"] = max(0, expected_count - aggregate["candidate_count"])
        aggregate["not_scored_value_slots"] = aggregate["not_scored_candidate_count"] * scoring.SCALAR_DENOMINATOR
        aggregate["scored_value_slot_denominator"] = aggregate["value_slot_denominator"]
        aggregate["value_slot_denominator"] = aggregate["expected_value_slots"]
        aggregate["value_slot_rates"] = {key: value / aggregate["value_slot_denominator"]
                                         for key, value in aggregate["value_slot_counts"].items()}
        aggregate["scored_required_text_denominator"] = aggregate["required_text_denominator"]
        aggregate["required_text_denominator"] = expected_count * scoring.REQUIRED_TEXT_DENOMINATOR
        aggregate["required_text_coverage_rate"] = aggregate["required_text_covered"] / aggregate["required_text_denominator"]
        aggregate["scored_prerequisite_atom_denominator"] = aggregate["prerequisite_atom_denominator"]
        aggregate["prerequisite_atom_denominator"] = expected_count * scoring.PREREQUISITE_ATOM_DENOMINATOR
        aggregate["prerequisite_atom_coverage_rate"] = aggregate["prerequisite_atoms_covered"] / aggregate["prerequisite_atom_denominator"]
    all_replay_pass = (
        complete and positive_scores_met == 7 and mutation_scores_met == 9
        and preflight_matches == len(source_results)
        and source_rejection_success == len(rejected)
        and unexpected_failures == 0
        and expected_rejection_success == len(rejection_controls)
        and sensitivity_success == len(sensitivity_controls)
        and mutant_render_failures == 0
    )
    return {
        "report_version": REPORT_VERSION,
        "result_kind": "offline component controls",
        "not_model_accuracy": True,
        "not_instruction_resistance_performance": True,
        "all_expected_component_controls_met": all_replay_pass,
        "fixed_case_set_complete": complete,
        "scoring_control_counts": {
            "positive_controls_met": positive_scores_met, "positive_control_denominator": 7,
            "mutation_controls_met": mutation_scores_met, "mutation_control_denominator": 9,
        },
        "scoring_control_results": {"synthetic_reference": positive_scoring_controls,
                                    "mutated_candidate": mutation_scoring_controls},
        "source_case_counts": {
            "attempted": len(source_results),
            "preflight_expectations_met": preflight_matches,
            "preflight_expectation_denominator": len(source_results),
            "accepted_preflight_expected": len(accepted),
            "accepted_preflight_actual": sum(item["actual_preflight"] for item in source_results),
            "source_rejections_expected": len(rejected),
            "source_rejections_met": source_rejection_success,
            "source_rejection_rate": None if not rejected else source_rejection_success / len(rejected),
            "unexpected_positive_checker_failures": unexpected_failures,
            "unexpected_failure_denominator": len(accepted),
            "unexpected_failure_rate": None if not accepted else unexpected_failures / len(accepted),
        },
        "candidate_mutation_counts": {
            "attempted": len(mutation_results),
            "expected_checker_rejections": len(rejection_controls),
            "expected_checker_rejections_met": expected_rejection_success,
            "expected_checker_rejection_rate": None if not rejection_controls else expected_rejection_success / len(rejection_controls),
            "expected_checker_pass_sensitivity_controls": len(sensitivity_controls),
            "expected_checker_pass_sensitivity_controls_met": sensitivity_success,
            "checker_passing_mutants_requiring_render": len(required_mutant_renders),
            "checker_passing_mutant_render_failures": mutant_render_failures,
        },
        "provenance_aggregates": {
            "synthetic_reference": synthetic_summary,
            "mutated_candidate": mutant_summary,
            "recorded_model": None,
        },
        "unscorable_candidate_count": synthetic_summary["unscorable_candidate_count"] + mutant_summary["unscorable_candidate_count"],
        "not_scored_candidate_count": synthetic_summary["not_scored_candidate_count"] + mutant_summary["not_scored_candidate_count"],
    }


def _retain_failure_evidence(run_id, run_dir, started_at, protected_before, state, error):
    """Finish a failed run with explicit unscored cases and retained partial evidence."""
    try:
        protected_after = _protected_snapshot()
        unchanged = protected_before == protected_after
    except OSError as snapshot_error:
        protected_after = {"snapshot_error": str(snapshot_error)}
        unchanged = False
    failure = {"type": type(error).__name__, "message": str(error),
               "stage": state.get("stage", "initialisation"), "traceback_file": "failure-traceback.txt"}
    (run_dir / "failure-traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
    source_results = state["source_results"]
    mutation_results = state["mutation_results"]
    completed_sources = {item["case_id"] for item in source_results}
    completed_mutations = {item["mutation_id"] for item in mutation_results}
    expected_sources = [item[0] for item in corpus.CASE_TRANSFORMS]
    summary = {
        "report_version": REPORT_VERSION,
        "result_kind": "failed offline component replay", "run_status": "error",
        "all_expected_component_controls_met": False, "failure": failure,
        "planned_source_case_count": 9, "planned_candidate_mutation_count": 9,
        "source_cases_started": len(source_results), "candidate_mutations_started": len(mutation_results),
        "source_case_ids_not_started": [value for value in expected_sources if value not in completed_sources],
        "candidate_mutation_ids_not_started": [value for value in MUTATION_SOURCE_CASES if value not in completed_mutations],
        "expected_value_slots": {"synthetic_reference": 147, "mutated_candidate": 189},
        "not_scored_value_slots": {"synthetic_reference": (7 - len(state["source_scores"])) * 21,
                                   "mutated_candidate": (9 - len(state["mutation_scores"])) * 21},
        "integrity_check_passed": unchanged, "candidate_qualitative_review": "pending",
        "model_calls": 0,
    }
    for name in ("results.json", "run-manifest.json"):
        path = run_dir / name
        if path.exists():
            path.replace(run_dir / ("component-" + name.replace(".json", "-before-error.json")))
    _write_json(run_dir / "source-case-results.json", source_results)
    _write_json(run_dir / "mutation-results.json", mutation_results)
    _write_json(run_dir / "results.json", summary)
    _write_json(run_dir / "integrity.json", {"unchanged": unchanged, "before": protected_before, "after": protected_after})
    _write_json(run_dir / "failure.json", failure)
    (run_dir / "results.md").write_text(
        "# Failed offline component replay\n\n"
        f"Stage: {failure['stage']}\n\nError: {failure['type']}: {failure['message']}\n\n"
        "Partial outputs, unscored denominators, and integrity results are retained.\n", encoding="utf-8")
    _write_json(run_dir / "run-manifest.json", {
        "report_version": REPORT_VERSION,
        "run_id": run_id, "mode": "replay", "run_status": "error", "failure": failure,
        "started_at_utc": started_at, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(), "model_calls": 0, "network_collection": False,
        "protected_files_before": protected_before, "protected_files_after": protected_after,
        "input_hashes": state.get("input_hashes"), "qualitative_review": "pending",
        "run_output_sha256": {str(path.relative_to(run_dir)): _hash_file(path)
                              for path in sorted(run_dir.rglob("*"))
                              if path.is_file() and path.name != "run-manifest.json"},
    })


def run_replay():
    """Run the fixed controls; retain an explicit final report on stage failure."""
    started_at = datetime.now(timezone.utc).isoformat()
    protected_before = _protected_snapshot()
    run_id, run_dir = _unique_run_directory()
    state = {"source_results": [], "mutation_results": [], "source_scores": [], "mutation_scores": [],
             "stage": "corpus_validation"}
    try:
        return _execute_replay(run_id, run_dir, started_at, protected_before, state)
    except (Exception, KeyboardInterrupt) as error:
        _retain_failure_evidence(run_id, run_dir, started_at, protected_before, state, error)
        raise


def _execute_replay(run_id, run_dir, started_at, protected_before, state):
    generated, catalog, reference = corpus.check_corpus()
    # Explicitly re-check review status/hashes before creating any score.
    scoring.validate_reviewed_reference(reference, generated, _read_json(BASE_PATH))
    state["input_hashes"] = _hash_inputs(generated)
    input_root = run_dir / "inputs"
    corpus.write_cases(input_root, generated)
    (run_dir / "candidates").mkdir()
    (run_dir / "checker-feedback").mkdir()
    (run_dir / "scores").mkdir()
    source_results = state["source_results"]
    source_scores = state["source_scores"]
    candidate_paths = {}
    source_bundles = {}

    for case in catalog["source_cases"]:
        case_id = case["case_id"]
        state["stage"] = "source_case:" + case_id
        generated_case = generated[case_id]
        source_bundle = json.loads(generated_case["bytes"].decode("utf-8"))
        source_bundles[case_id] = source_bundle
        accepted = course_sources._valid_bundle(source_bundle)
        expected_accept = case["expected_preflight"] == "accept"
        item = {
            "case_id": case_id,
            "expected_preflight": case["expected_preflight"],
            "actual_preflight": accepted,
            "preflight_invocation_method": "direct call: harness.course_sources._valid_bundle",
            "outcome_matches_expectation": accepted == expected_accept,
            "input_path": f"{input_root.relative_to(ROOT)}/{case['input_path']}",
            "input_sha256": _sha256(generated_case["bytes"]),
            "candidate_path": None,
            "checker": None,
            "renderer": None,
            "score_path": None,
        }
        source_results.append(item)
        if accepted and expected_accept:
            candidate = build_reference_candidate(source_bundle, reference, case_id)
            candidate_dir = run_dir / "candidates" / "synthetic_reference" / case_id
            candidate_path, provenance = _write_candidate(candidate_dir, candidate, {
                "provenance_class": "synthetic_reference",
                "source_case_id": case_id,
                "generator": "build_reference_candidate from reviewed reference facts and source quotations",
                "model_call": False,
                "source_input_sha256": _sha256(generated_case["bytes"]),
            })
            candidate_paths[case_id] = (candidate_path, candidate)
            item["candidate_path"] = str(candidate_path.relative_to(ROOT))
            item["candidate_sha256"] = provenance["candidate_sha256"]
            checker = _run_checker(
                input_root / case["input_path"], candidate_path,
                run_dir / "checker-feedback" / "synthetic_reference" / f"{case_id}.json",
            )
            item["checker"] = checker
            if checker["status"] == "pass":
                renderer = _run_renderer(candidate_path, run_dir / "rendered" / "synthetic_reference" / case_id)
                item["renderer"] = renderer
            score = scoring.score_candidate(candidate, reference, case_id, provenance="synthetic_reference")
            score_path = run_dir / "scores" / "synthetic_reference" / f"{case_id}.json"
            _write_json(score_path, score)
            item["score_path"] = str(score_path.relative_to(ROOT))
            item["score_status"] = score["candidate_status"]
            item["scoring_expectation"] = check_scoring_expectation(score, reference, case_id)
            source_scores.append(score)
        else:
            if accepted != expected_accept:
                item["failure"] = "source preflight disagreed with its fixed expectation; no candidate was created"
            # S07/S08 intentionally stop here; no checker or renderer runs.

    mutation_results = state["mutation_results"]
    mutation_scores = state["mutation_scores"]
    for mutation in catalog["candidate_mutations"]:
        mutation_id = mutation["case_id"]
        state["stage"] = "candidate_mutation:" + mutation_id
        source_case_id = MUTATION_SOURCE_CASES[mutation_id]
        result_item = {
            "mutation_id": mutation_id, "source_case_id": source_case_id,
            "expected_effect": mutation["expected_effect"],
            "expected_checker_status": EXPECTED_MUTATION_CHECKS[mutation_id],
            "checker_expectation_met": False, "scoring_expectation_met": False,
            "checker": None, "renderer": None, "score_path": None, "score_status": "not_scored",
        }
        mutation_results.append(result_item)
        if source_case_id not in candidate_paths:
            result_item["failure"] = "parent source case did not reach candidate generation"
            continue
        parent_path, parent = candidate_paths[source_case_id]
        source_bundle = source_bundles[source_case_id]
        mutated = apply_candidate_mutation(parent, source_bundle, reference, catalog, mutation_id)
        parent_hash = _hash_file(parent_path)
        expected_status = EXPECTED_MUTATION_CHECKS[mutation_id]
        mutation_dir = run_dir / "candidates" / "mutated_candidate" / mutation_id
        candidate_path, provenance = _write_candidate(mutation_dir, mutated, {
            "provenance_class": "mutated_candidate",
            "source_case_id": source_case_id,
            "mutation_id": mutation_id,
            "parent_candidate_sha256": parent_hash,
            "generator": "apply_candidate_mutation deterministic component control",
            "model_call": False,
            "expected_checker_status": expected_status,
        })
        result_item.update({
            "candidate_path": str(candidate_path.relative_to(ROOT)),
            "candidate_sha256": provenance["candidate_sha256"],
            "provenance_path": str((mutation_dir / "provenance.json").relative_to(ROOT)),
            "parent_candidate_sha256": parent_hash,
        })
        checker = _run_checker(
            input_root / next(case["input_path"] for case in catalog["source_cases"] if case["case_id"] == source_case_id),
            candidate_path,
            run_dir / "checker-feedback" / "mutated_candidate" / f"{mutation_id}.json",
        )
        result_item["checker"] = checker
        renderer = None
        if checker["status"] == "pass":
            renderer = _run_renderer(candidate_path, run_dir / "rendered" / "mutated_candidate" / mutation_id)
            result_item["renderer"] = renderer
        score = scoring.score_candidate(mutated, reference, source_case_id, provenance="mutated_candidate")
        score["mutation_id"] = mutation_id
        scoring_expectation = check_scoring_expectation(score, reference, source_case_id, mutation_id)
        score_path = run_dir / "scores" / "mutated_candidate" / f"{mutation_id}.json"
        _write_json(score_path, score)
        expectation_met = checker["status"] == expected_status
        result_item.update({
            "mutation_id": mutation_id,
            "source_case_id": source_case_id,
            "expected_effect": mutation["expected_effect"],
            "expected_checker_status": expected_status,
            "checker_expectation_met": expectation_met,
            "scoring_expectation_met": scoring_expectation["met"],
            "scoring_expectation": scoring_expectation,
            "candidate_path": str(candidate_path.relative_to(ROOT)),
            "candidate_sha256": provenance["candidate_sha256"],
            "provenance_path": str((mutation_dir / "provenance.json").relative_to(ROOT)),
            "parent_candidate_sha256": parent_hash,
            "checker": checker,
            "renderer": renderer,
            "score_path": str(score_path.relative_to(ROOT)),
            "score_status": score["candidate_status"],
        })
        mutation_scores.append(score)

    state["stage"] = "summary_and_integrity"
    summary = _summarise_results(source_results, mutation_results, source_scores, mutation_scores, reference)
    protected_after = _protected_snapshot()
    integrity_ok = protected_before == protected_after
    integrity = {
        "unchanged": integrity_ok,
        "before": protected_before,
        "after": protected_after,
        "assertions": {
            "frozen_source_unchanged": protected_before[str(BASE_PATH.relative_to(ROOT))] == protected_after[str(BASE_PATH.relative_to(ROOT))],
            "reviewed_reference_unchanged": protected_before[str(REFERENCE_PATH.relative_to(ROOT))] == protected_after[str(REFERENCE_PATH.relative_to(ROOT))],
            "normal_training_outputs_unchanged": all(
                protected_before[str(path.relative_to(ROOT))] == protected_after[str(path.relative_to(ROOT))]
                for path in TRAINING_PATHS
            ),
        },
    }
    summary["integrity_check_passed"] = integrity_ok
    summary["candidate_qualitative_review"] = "pending"
    summary["phase_b_status"] = "implemented; actual model evaluation remains disabled"
    _write_json(run_dir / "source-case-results.json", source_results)
    _write_json(run_dir / "mutation-results.json", mutation_results)
    _write_json(run_dir / "results.json", summary)
    _write_json(run_dir / "integrity.json", integrity)
    (run_dir / "results.md").write_text(_render_summary(summary, source_results, mutation_results), encoding="utf-8")
    _write_json(run_dir / "run-manifest.json", {
        "report_version": REPORT_VERSION,
        "run_id": run_id,
        "mode": "replay",
        "run_status": "passed" if summary["all_expected_component_controls_met"] and integrity_ok else "failed_controls",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "source_case_ids": [item["case_id"] for item in source_results],
        "candidate_mutation_ids": [item["mutation_id"] for item in mutation_results],
        "reference_review_status": reference["review"]["status"],
        "input_hashes": state["input_hashes"],
        "input_hashes_after": _hash_inputs(generated),
        "protected_files_before": protected_before,
        "model_calls": 0,
        "network_collection": False,
        "recorded_model_import": False,
        "qualitative_review": "pending",
        "run_output_sha256": {
            str(path.relative_to(run_dir)): _hash_file(path)
            for path in sorted(run_dir.rglob("*"))
            if path.is_file() and path != run_dir / "run-manifest.json"
        },
    })
    if not integrity_ok:
        raise RuntimeError(f"protected inputs or published outputs changed during replay; inspect {run_dir}")
    return run_id, run_dir, summary


def _render_summary(summary, source_results, mutation_results):
    source = summary["source_case_counts"]
    mutations = summary["candidate_mutation_counts"]
    lines = [
        "# Task 013 Phase B offline component replay",
        "",
        "This run reports synthetic component controls. It is not model accuracy or instruction-resistance performance.",
        "Candidate qualitative review remains pending.",
        "",
        "## Source cases",
        "",
        "| Case | Expected preflight | Actual preflight | Checker | Rendered |",
        "|---|---|---:|---|---:|",
    ]
    for item in source_results:
        checker = item["checker"]["status"] if item["checker"] else "not run (preflight rejection)"
        rendered = "yes" if item["renderer"] and item["renderer"]["status"] == "pass" else "no"
        lines.append(f"| {item['case_id']} | {item['expected_preflight']} | {item['actual_preflight']} | {checker} | {rendered} |")
    lines.extend([
        "",
        f"Source rejection controls: {source['source_rejections_met']}/{source['source_rejections_expected']} passed.",
        f"Expected-positive checker cases with unexpected failures: {source['unexpected_positive_checker_failures']}/{source['unexpected_failure_denominator']}.",
        "",
        "## Candidate mutations",
        "",
        "| Mutation | Source case | Expected checker | Actual | Checker met | Scoring met | Factual score file |",
        "|---|---|---|---|---:|---:|---|",
    ])
    for item in mutation_results:
        lines.append(
            f"| {item['mutation_id']} | {item['source_case_id']} | {item['expected_checker_status']} | "
            f"{item['checker']['status'] if item.get('checker') else 'not run'} | {item['checker_expectation_met']} | "
            f"{item.get('scoring_expectation_met', False)} | `{item['score_path']}` |"
        )
    lines.extend([
        "",
        f"Expected checker-rejection controls: {mutations['expected_checker_rejections_met']}/{mutations['expected_checker_rejections']}.",
        f"Expected checker-pass sensitivity controls: {mutations['expected_checker_pass_sensitivity_controls_met']}/{mutations['expected_checker_pass_sensitivity_controls']}.",
        f"Checker-passing mutants with render failures: {mutations['checker_passing_mutant_render_failures']}/{mutations['checker_passing_mutants_requiring_render']}.",
        f"Positive scoring controls: {summary['scoring_control_counts']['positive_controls_met']}/7.",
        f"Mutation scoring controls: {summary['scoring_control_counts']['mutation_controls_met']}/9.",
        "",
        "## Provenance-separated scoring",
        "",
        "| Provenance | Candidates / expected | Value slots correct / missing / incorrect | Required-text atoms covered | Prerequisite atoms covered | Unscorable | Not scored |",
        "|---|---:|---|---|---|---:|---:|",
    ])
    for provenance, label in (("synthetic_reference", "synthetic_reference"), ("mutated_candidate", "mutated_candidate")):
        aggregate = summary["provenance_aggregates"][provenance]
        counts = aggregate["value_slot_counts"]
        lines.append(
            f"| {label} | {aggregate['candidate_count']} / {aggregate['expected_candidate_count']} | {counts['correct']} / {counts['missing']} / {counts['incorrect']} "
            f"of {aggregate['value_slot_denominator']} | {aggregate['required_text_covered']} of {aggregate['required_text_denominator']} "
            f"| {aggregate['prerequisite_atoms_covered']} of {aggregate['prerequisite_atom_denominator']} "
            f"| {aggregate['unscorable_candidate_count']} | {aggregate['not_scored_candidate_count']} |"
        )
    lines.extend([
        "",
        f"Protected input and published-output integrity: {'PASS' if summary['integrity_check_passed'] else 'FAIL'}.",
        "Phase B scoring uses reviewed source facts. Checker decisions and factual scores are separate results.",
        "",
    ])
    return "\n".join(lines)


def _actual_limit(value, name):
    """Accept exact positive integers from CLI strings or programmatic calls."""
    if type(value) is int:
        result = value
    elif isinstance(value, str) and value and value.isascii() and value.isdecimal():
        result = int(value)
    else:
        raise ValueError(f"{name} must be a positive integer")
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _validate_live_runtime():
    """Check the sole credential source and exact pinned SDK before dispatch."""
    key = os.environ.get("OPENAI_API_KEY")
    if not isinstance(key, str) or not key or key.isspace() or key.strip() != key:
        raise ValueError("runtime credential is unavailable or malformed")
    requirements = (ROOT / "requirements-model.txt").read_text(encoding="utf-8").splitlines()
    if f"openai=={PINNED_OPENAI_VERSION}" not in {line.strip() for line in requirements}:
        raise ValueError("pinned model SDK requirement does not match the supported contract")
    try:
        installed = importlib.metadata.version("openai")
    except importlib.metadata.PackageNotFoundError:
        raise ValueError("pinned model SDK is unavailable") from None
    if installed != PINNED_OPENAI_VERSION:
        raise ValueError("installed model SDK does not match the pinned contract")
    return installed


def _actual_error_category(error):
    """Map failures to fixed labels; never serialize native messages or reprs."""
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "interruption"
    if isinstance(error, (OSError, IOError)):
        return "storage"
    if isinstance(error, (ValueError, TypeError, KeyError, json.JSONDecodeError)):
        return "validation"
    return "controller"


def _record_actual_failure(state, code, category, *, stage=None):
    """Retain the first failure separately from later cleanup/report errors."""
    stage = stage or state["stage"]
    if state.get("failure_code") is None:
        state["failure_code"] = code
        state["error_category"] = category
        state["failure_stage"] = stage
    else:
        state.setdefault("failure_stage", state["stage"])
        later = {"stage": stage, "failure_code": code, "error_category": category}
        primary = {"stage": state["failure_stage"], "failure_code": state["failure_code"],
                   "error_category": state.get("error_category")}
        if later != primary and later not in state.setdefault("secondary_failures", []):
            state["secondary_failures"].append(later)
    if code == "interrupted":
        state["interrupted"] = True


class _ActualRequestAudit:
    """Observe one native client's raw calls without changing their payloads.

    The adapter still owns validation/reservation/settlement. This serial
    facade delegates the exact raw methods and retry/timeout properties to
    the single native client; it creates no client, request, retry or budget.
    Only safe invocation metadata, never response bodies, enters the audit.
    """

    def __init__(self, client, path):
        self.native_client = client
        self.path = path
        self.responses = self
        self.input_tokens = self
        self.with_raw_response = self
        self.events = []
        self.case_id = None
        self.attempt = 0
        self._persist()

    def __getattr__(self, name):
        return getattr(self.native_client, name)

    def begin_case(self, case_id):
        self.case_id = case_id
        self.attempt = 0

    def _persist(self):
        _write_json(self.path, {"audit_version": 1, "events": self.events})

    def count(self, **kwargs):
        self.attempt += 1
        method = self.native_client.responses.input_tokens.with_raw_response.count
        return self._invoke("input_tokens.count", method, kwargs)

    def create(self, **kwargs):
        method = self.native_client.responses.with_raw_response.create
        return self._invoke("responses.create", method, kwargs)

    def _invoke(self, operation, method, kwargs):
        item = {
            "sequence": len(self.events) + 1,
            "case_id": self.case_id,
            "attempt": self.attempt,
            "operation": operation,
            "request_sha256": _sha256(json.dumps(
                kwargs, sort_keys=True, ensure_ascii=False,
                separators=(",", ":"), allow_nan=False).encode("utf-8")),
            "invocation_started": False,
            "outcome": "prepared",
        }
        self.events.append(item)
        # A failed pre-dispatch receipt never invokes either endpoint.
        self._persist()
        item["invocation_started"] = True
        try:
            result = method(**kwargs)
        except BaseException as error:
            item["outcome"] = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "raised"
            self._persist()
            raise
        item["outcome"] = "response_returned"
        self._persist()
        return result


def _verify_actual_case_evidence(row, case_dir, result, ledger):
    """Refuse a completed case whose required receipts or hashes are missing."""
    if result.status not in {"accepted", "candidate_rejected"}:
        return

    def required(name):
        path = case_dir / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(case_dir.resolve()):
            raise ValueError("case evidence integrity failure")
        return path

    source_hash = _hash_file(required("source.json"))
    if source_hash != row["source_sha256"] or _hash_file(ROOT / row["source_path"]) != source_hash:
        raise ValueError("case source evidence changed")
    provenance = _read_json(required("source-provenance.json"))
    if provenance.get("source_sha256") != source_hash:
        raise ValueError("case source receipt mismatch")
    receipt = _read_json(required("result.json"))
    if receipt.get("status") != result.status or receipt.get("attempts") != result.attempts:
        raise ValueError("case result receipt mismatch")
    if _read_json(required("budget-final.json")) != ledger.state:
        raise ValueError("case budget receipt mismatch")
    if type(result.attempts) is not int or not 1 <= result.attempts <= 3:
        raise ValueError("case attempt receipt invalid")
    final_hash = None
    for attempt in range(1, result.attempts + 1):
        record = _read_json(required(f"attempt-{attempt}.json"))
        candidate_hash = _hash_file(required(f"candidate-{attempt}.json"))
        request = _read_json(required(f"request-attempt-{attempt}.json"))
        check = _read_json(required(f"candidate-check-{attempt}.json"))
        required(f"budget-after-attempt-{attempt}.json")
        if (record.get("generation_status") != "completed"
                or record.get("candidate_sha256") != candidate_hash
                or record.get("source_sha256") != source_hash
                or request.get("source_sha256") != source_hash
                or request.get("dispatch_status") != "completed"
                or record.get("count_create_payload_sha256") != request.get("count_create_payload_sha256")
                or check.get("candidate_sha256") != candidate_hash
                or check.get("source_sha256") != source_hash
                or check.get("dispatch_status") != "completed"
                or check.get("timed_out") is not False
                or check.get("status") != record.get("checker_status")):
            raise ValueError("case attempt evidence mismatch")
        expected_check = 0 if result.status == "accepted" and attempt == result.attempts else 1
        if type(check.get("status")) is not int or check["status"] != expected_check:
            raise ValueError("case checker outcome mismatch")
        final_hash = candidate_hash
    if result.status == "candidate_rejected" and result.attempts != 3:
        raise ValueError("case rejection is not a completed three-attempt outcome")
    if (_hash_file(required("candidate.json")) != final_hash
            or required("candidate-check.json").read_bytes()
            != required(f"candidate-check-{result.attempts}.json").read_bytes()):
        raise ValueError("case final candidate/checker mismatch")
    if result.status == "accepted":
        rendered = _read_json(required("render.json"))
        if (rendered.get("status") != 0 or rendered.get("dispatch_status") != "completed"
                or rendered.get("timed_out") is not False
                or _hash_file(required("rendered-courses.json")) != rendered.get("json_sha256")
                or _hash_file(required("comparison.md")) != rendered.get("markdown_sha256")):
            raise ValueError("case rendered evidence mismatch")


def _actual_rate(numerator, denominator):
    return None if denominator == 0 else numerator / denominator


def _actual_failure_code(stage, error):
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "interrupted"
    return {
        "corpus_validation": "frozen_input_integrity_failure",
        "preflight": "preflight_integrity_failure",
        "evidence_setup": "evidence_setup_failure",
        "ledger_setup": "ledger_setup_failure",
        "client_setup": "client_setup_failure",
        "workflow": "workflow_abandoned",
        "case_evidence": "case_evidence_integrity_failure",
        "scoring": "scoring_failure",
        "integrity": "integrity_change",
        "reporting": "reporting_failure",
    }.get(stage, "evaluation_failure")


def _new_actual_case_rows(catalog):
    rows = []
    for case in catalog["source_cases"]:
        rows.append({
            "case_id": case["case_id"],
            "expected_preflight": case["expected_preflight"],
            "expected_workflow_outcome": case["expected_outcome"],
            "observed_preflight": "not_observed",
            "preflight_invocation_method": "harness.course_workflow._validated_source_view",
            "preflight_matches_expectation": None,
            "workflow_status": "not_started",
            "workflow_failure_code": None,
            "generation_dispatched": False,
            "candidate_status": "not_scored",
            "candidate_path": None,
            "candidate_sha256": None,
            "candidate_attempt": None,
            "candidate_is_prior_to_terminal_attempt": False,
            "score_path": None,
            "score_status": "not_scored",
            "case_evidence_dir": None,
            "reservation_indices": [],
            "model_call_start": None,
            "model_call_end": None,
        })
    return rows


def _actual_linkage(ledger, rows):
    reservations = ledger.state["reservations"] if ledger is not None else []
    call_number = 0
    output = []
    for index, item in enumerate(reservations, start=1):
        dispatched = item["status"] != "reserved"
        if dispatched:
            call_number += 1
        case_id = None
        attempt = None
        for row in rows:
            if index in row["reservation_indices"]:
                case_id = row["case_id"]
                attempt = row["reservation_indices"].index(index) + 1
                break
        output.append({
            "reservation_index": index,
            "reservation_handle": item["handle"],
            "case_id": case_id,
            "attempt": attempt,
            "model_call_number": call_number if dispatched else None,
            "reservation_status": item["status"],
        })
    return output


def _actual_ledger_counts(ledger, audit=None):
    events = audit.events if audit is not None else []
    counts = [item for item in events if item["operation"] == "input_tokens.count" and item["invocation_started"]]
    creates = [item for item in events if item["operation"] == "responses.create" and item["invocation_started"]]
    if ledger is None:
        return {
            "input_token_count_requests": len(counts),
            "input_token_count_responses": 0,
            "input_token_count_failures": 0,
            "generation_dispatches": 0,
            "generation_model_call_slots_used": 0,
            "confirmed_input_tokens": 0,
            "confirmed_output_tokens": 0,
            "confirmed_total_tokens": 0,
            "pending_reserved_tokens": 0,
        }
    state = ledger.state
    reservations = state["reservations"]
    settled = [item for item in reservations if item["status"] == "settled"]
    pending = sum(item["reserved_tokens"] for item in reservations
                  if item["status"] in {"reserved", "dispatched", "uncertain", "contradiction"})
    count_failed = int(state["block_reason"] == "input_count_failed")
    input_total = sum(item["counted_input_tokens"] for item in settled)
    total = sum(item["actual_tokens"] for item in settled)
    return {
        "input_token_count_requests": len(counts),
        "input_token_count_responses": sum(item["outcome"] == "response_returned" for item in counts),
        "input_token_count_failures": max(count_failed, sum(item["outcome"] in {"raised", "interrupted"} for item in counts)),
        "input_token_count_responses_with_reservation": len(reservations),
        "generation_dispatches": len(creates),
        "generation_model_call_slots_used": state["model_calls"],
        "confirmed_input_tokens": input_total,
        "confirmed_output_tokens": total - input_total,
        "confirmed_total_tokens": state["confirmed_tokens"],
        "pending_reserved_tokens": pending,
    }


def _actual_summary(state, integrity_ok):
    rows = state["source_results"]
    approved = [row for row in rows if row["expected_preflight"] == "accept"]
    scoreable = [score for score in state["actual_scores"]
                 if score.get("candidate_status") == "scoreable"]
    unscorable = [score for score in state["actual_scores"]
                  if score.get("candidate_status") == "unscorable"]
    scored_by_case = {row["case_id"]: row for row in approved
                      if row["candidate_status"] == "scoreable"}
    unscorable_by_case = {row["case_id"]: row for row in approved
                          if row["candidate_status"] == "unscorable"}
    not_scored = [row for row in approved if row["candidate_status"] == "not_scored"]
    score_aggregate = scoring.aggregate_scores(scoreable, evaluation_mode="actual")

    def fixed_metrics(planned_units, unit_key):
        actually = len(scoreable) * planned_units
        uncertain = len(unscorable) * planned_units
        not_done = len(not_scored) * planned_units
        return {
            "planned_denominator": len(approved) * planned_units,
            "actually_scored_denominator": actually,
            "unscorable_denominator": uncertain,
            "not_scored_denominator": not_done,
            "fixed_set_coverage_rate": _actual_rate(actually, len(approved) * planned_units),
            "unscorable_rate": _actual_rate(uncertain, len(approved) * planned_units),
            "not_scored_rate": _actual_rate(not_done, len(approved) * planned_units),
            "scored_case_count": len(scored_by_case),
            "unscorable_case_count": len(unscorable_by_case),
            "not_scored_case_count": len(not_scored),
            "unit": unit_key,
        }

    workflow_counts = {}
    for row in rows:
        status = row["workflow_status"]
        workflow_counts[status] = workflow_counts.get(status, 0) + 1
    outcomes_final = len(rows) == 9 and all(
        (row["expected_preflight"] == "reject" and row["observed_preflight"] == "rejected"
         and row["workflow_status"] == "preflight_rejected")
        or (row["expected_preflight"] == "accept" and row["observed_preflight"] == "approved"
            and row["workflow_status"] in {"accepted", "candidate_rejected"}
            and row["candidate_status"] in {"scoreable", "unscorable"})
        for row in rows
    )
    ledger_state = state["ledger"].state if state.get("ledger") is not None else None
    known_usage = ledger_state is not None and not ledger_state["blocked"] and all(
        item["status"] == "settled" for item in ledger_state["reservations"])
    complete = outcomes_final and integrity_ok and known_usage and state.get("failure_code") is None
    metrics = {
        "planned_case_count": len(approved),
        "actually_scored_case_count": len(scored_by_case),
        "unscorable_case_count": len(unscorable_by_case),
        "not_scored_case_count": len(not_scored),
        "case_coverage_rate": _actual_rate(len(scored_by_case), len(approved)),
        "value_slots": fixed_metrics(scoring.SCALAR_DENOMINATOR, "value_slot"),
        "required_text_atoms": fixed_metrics(scoring.REQUIRED_TEXT_DENOMINATOR, "required_text_atom"),
        "prerequisite_atoms": fixed_metrics(scoring.PREREQUISITE_ATOM_DENOMINATOR, "prerequisite_atom"),
        "field_quality_denominators": {
            "actually_scored_value_slots": score_aggregate["value_slot_denominator"],
            "actually_scored_required_text_atoms": score_aggregate["required_text_denominator"],
            "actually_scored_prerequisite_atoms": score_aggregate["prerequisite_atom_denominator"],
        },
    }
    return {
        "report_version": ACTUAL_REPORT_VERSION,
        "mode": "actual",
        "execution_kind": state["execution_kind"],
        "not_model_accuracy": state["execution_kind"] == "injected_test",
        "injected_test_disclaimer": (
            "All client responses are injected test data; no provider model generated these candidates."
            if state["execution_kind"] == "injected_test" else None
        ),
        "source_collection": False,
        "source_input": "frozen local nine-case corpus",
        "run_status": "complete" if complete else "incomplete",
        "evaluation_complete": complete,
        "outcomes_finalized": outcomes_final,
        "integrity_check_passed": integrity_ok,
        "failure": (None if state.get("failure_code") is None else {
            "stage": state.get("failure_stage", state["stage"]),
            "failure_code": state["failure_code"],
            "error_category": state.get("error_category"),
        }),
        "secondary_failures": state.get("secondary_failures", []),
        "planned_source_case_count": 9,
        "preflight_rejected_case_count": sum(row["workflow_status"] == "preflight_rejected" for row in rows),
        "approved_source_case_count": len(approved),
        "workflow_outcome_counts": workflow_counts,
        "expected_workflow_outcomes": {
            row["case_id"]: row["expected_workflow_outcome"] for row in rows
        },
        "actual_workflow_outcomes": {
            row["case_id"]: row["workflow_status"] for row in rows
        },
        "fixed_set_coverage": metrics,
        "scored_provenance_aggregate": score_aggregate,
        "unscorable_candidate_count": len(unscorable),
        "not_scored_candidate_count": len(not_scored),
        "ledger_state": ledger_state,
        "request_usage_counts": _actual_ledger_counts(state.get("ledger"), state.get("request_audit")),
        "candidate_qualitative_review": "pending",
        "model_quality_threshold": None,
    }


def _minimal_actual_failure_summary(state):
    """Independent fallback: never call the failed scoring/report component."""
    rows = state["source_results"]
    approved = [row for row in rows if row["expected_preflight"] == "accept"]
    return {
        "report_version": ACTUAL_REPORT_VERSION,
        "mode": "actual",
        "execution_kind": state["execution_kind"],
        "not_model_accuracy": state["execution_kind"] == "injected_test",
        "run_status": "incomplete",
        "evaluation_complete": False,
        "integrity_check_passed": False,
        "failure": {
            "stage": state.get("failure_stage", state["stage"]),
            "failure_code": state["failure_code"],
            "error_category": state.get("error_category"),
        },
        "secondary_failures": state.get("secondary_failures", []),
        "planned_source_case_count": 9,
        "approved_source_case_count": 7,
        "source_case_results": rows,
        "planned_denominators": {"value_slots": 147, "required_text_atoms": 119, "prerequisite_atoms": 77},
        "retained_candidate_counts": {
            status: sum(row["candidate_status"] == status for row in approved)
            for status in ("scoreable", "unscorable", "not_scored")
        },
        "quality_metrics_unavailable": True,
        "candidate_qualitative_review": "pending",
    }


def _write_actual_evidence(run_id, run_dir, state, protected_before):
    """Best-effort finalizer for actual runs; this never reopens dispatch."""
    protected_after = _protected_snapshot()
    integrity_ok = protected_before == protected_after
    if not integrity_ok:
        _record_actual_failure(state, "integrity_change", "integrity", stage="integrity")
        if state.get("ledger") is not None:
            _safe_block_actual(state["ledger"], "protocol_failure")
    summary = _actual_summary(state, integrity_ok)
    started = state["started_at"]
    _write_json(run_dir / "source-case-results.json", state["source_results"])
    _write_json(run_dir / "scores-index.json", {
        row["case_id"]: row["score_path"] for row in state["source_results"]
        if row.get("score_path") is not None
    })
    _write_json(run_dir / "ledger-linkage.json", _actual_linkage(state.get("ledger"), state["source_results"]))
    if state.get("failure_code") is not None:
        _write_json(run_dir / "failure.json", {
            "stage": state.get("failure_stage", state["stage"]),
            "failure_code": state["failure_code"],
            "error_category": state.get("error_category"),
            "secondary_failures": state.get("secondary_failures", []),
        })
    if state.get("request_audit") is not None:
        state["request_audit"]._persist()
    if state.get("ledger") is not None:
        _write_json(run_dir / "budget-after.json", state["ledger"].state)
    _write_json(run_dir / "integrity.json", {
        "unchanged": integrity_ok,
        "before": protected_before,
        "after": protected_after,
        "assertions": {
            "frozen_source_unchanged": protected_before.get(str(BASE_PATH.relative_to(ROOT))) == protected_after.get(str(BASE_PATH.relative_to(ROOT))),
            "reviewed_reference_unchanged": protected_before.get(str(REFERENCE_PATH.relative_to(ROOT))) == protected_after.get(str(REFERENCE_PATH.relative_to(ROOT))),
            "normal_training_outputs_unchanged": all(
                protected_before.get(str(path.relative_to(ROOT))) == protected_after.get(str(path.relative_to(ROOT)))
                for path in TRAINING_PATHS
            ),
        },
    })
    (run_dir / "results.md").write_text(_render_actual_summary(summary, state["source_results"]), encoding="utf-8")
    manifest = {
        "report_version": ACTUAL_REPORT_VERSION,
        "run_id": run_id,
        "mode": "actual",
        "execution_kind": state["execution_kind"],
        "not_model_accuracy": state["execution_kind"] == "injected_test",
        "injected_test_disclaimer": summary["injected_test_disclaimer"],
        "run_status": summary["run_status"],
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "model": ACTUAL_MODEL,
        "reasoning_effort": ACTUAL_REASONING_EFFORT,
        "sdk_requirement": f"openai=={PINNED_OPENAI_VERSION}",
        "sdk_runtime_version": state.get("sdk_runtime_version"),
        "source_collection": False,
        "limits": state["limits"],
        "input_hashes": state.get("input_hashes"),
        "input_hashes_after": (_hash_inputs(state["generated"]) if state.get("generated") is not None else None),
        "protected_files_before": protected_before,
        "protected_files_after": protected_after,
        "request_usage_counts": summary["request_usage_counts"],
        "qualitative_review": "pending",
        "run_output_sha256": {
            str(path.relative_to(run_dir)): _hash_file(path)
            for path in sorted(run_dir.rglob("*"))
            if path.is_file() and path.name not in {"run-manifest.json", "results.json"}
        },
    }
    # Precompute the final result hash, then commit results.json last. A
    # missing manifest/report receipt cannot leave a completed result behind.
    manifest["run_output_sha256"]["results.json"] = _sha256(_json_bytes(summary))
    _write_json(run_dir / "run-manifest.json", manifest)
    _write_json(run_dir / "results.json", summary)
    return summary


def _safe_block_actual(ledger, reason):
    try:
        ledger.block(reason=reason)
    except BaseException:
        pass


def _render_actual_summary(summary, rows):
    coverage = summary["fixed_set_coverage"]
    lines = [
        "# Task 014 Phase C2 fixed-set actual evaluation",
        "",
        f"Execution kind: `{summary['execution_kind']}`. This report does not mark qualitative review complete.",
        f"Evaluation status: **{summary['run_status']}**. This status measures completeness and integrity, not perfect extraction.",
        "",
        "## Planned source cases",
        "",
        "| Case | Expected preflight | Observed preflight | Expected workflow outcome | Workflow outcome | Candidate score | Attempt |",
        "|---|---|---|---|---|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['expected_preflight']} | {row['observed_preflight']} | "
            f"{row['expected_workflow_outcome']} | {row['workflow_status']} | {row['candidate_status']} | "
            f"{row['candidate_attempt'] if row['candidate_attempt'] is not None else '—'} |"
        )
    lines.extend([
        "",
        "## Fixed-set scoring coverage",
        "",
        "| Measure | Planned | Actually scored | Unscorable | Not scored | Coverage of fixed set |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for key, label in (("value_slots", "Value slots"), ("required_text_atoms", "Required-text atoms"),
                       ("prerequisite_atoms", "Prerequisite atoms")):
        item = coverage[key]
        lines.append(
            f"| {label} | {item['planned_denominator']} | {item['actually_scored_denominator']} | "
            f"{item['unscorable_denominator']} | {item['not_scored_denominator']} | "
            f"{item['fixed_set_coverage_rate'] if item['fixed_set_coverage_rate'] is not None else 'null'} |"
        )
    lines.extend([
        "",
        f"Case outcomes: {coverage['actually_scored_case_count']} scored, {coverage['unscorable_case_count']} unscorable, "
        f"{coverage['not_scored_case_count']} not scored, from {coverage['planned_case_count']} approved source cases.",
        "",
        "Provider execution is real model generation only when `execution_kind` is `provider`. "
        "Injected test runs exercise the interface and are not model-accuracy evidence.",
        "",
    ])
    aggregate = summary["scored_provenance_aggregate"]
    lines.extend([
        "## Independent field quality",
        "",
        "| Measure | Count | Planned denominator | Actually scored denominator |",
        "|---|---:|---:|---:|",
    ])
    for name in ("correct", "missing", "incorrect"):
        lines.append(
            f"| {name.title()} value slots | {aggregate['value_slot_counts'][name]} | "
            f"{coverage['value_slots']['planned_denominator']} | {aggregate['value_slot_denominator']} |")
    for label, covered, planned, observed in (
            ("Required-text atoms covered", "required_text_covered", "required_text_atoms", "required_text_denominator"),
            ("Prerequisite atoms covered", "prerequisite_atoms_covered", "prerequisite_atoms", "prerequisite_atom_denominator")):
        lines.append(
            f"| {label} | {aggregate[covered]} | {coverage[planned]['planned_denominator']} | {aggregate[observed]} |")
    counts = summary["request_usage_counts"]
    lines.extend([
        "",
        "Unscorable and not-scored slots remain in planned coverage; they are not silently removed or labeled correct.",
        "Scored-only rates in JSON are conditional on the explicitly reported actually-scored denominators.",
        "",
        "## Request and token accounting",
        "",
        f"Input-count SDK requests: {counts['input_token_count_requests']}; returned count responses: {counts['input_token_count_responses']}.",
        f"Generation SDK requests: {counts['generation_dispatches']}; conservatively consumed generation-call slots: {counts['generation_model_call_slots_used']}.",
        f"Confirmed input plus output tokens: {counts['confirmed_total_tokens']}; pending reserved tokens: {counts['pending_reserved_tokens']}.",
        "",
        "Final completion is authoritative only when results.json is finalized and its hash matches run-manifest.json.",
        "",
    ])
    return "\n".join(lines)


def _score_actual_candidate(row, reference, case_dir, workflow_result, ledger):
    """Score the latest controller-recorded completed candidate, if one exists."""
    completed = []
    for attempt_file in case_dir.glob("attempt-*.json"):
        record = _read_json(attempt_file)
        if record.get("generation_status") != "completed":
            continue
        try:
            attempt_number = int(attempt_file.stem.removeprefix("attempt-"))
        except ValueError:
            continue
        candidate_path = case_dir / f"candidate-{attempt_number}.json"
        if not candidate_path.is_file() or candidate_path.is_symlink():
            raise ValueError("completed candidate evidence is unavailable")
        candidate_hash = _hash_file(candidate_path)
        if candidate_hash != record.get("candidate_sha256"):
            raise ValueError("completed candidate evidence changed")
        completed.append((attempt_number, candidate_path, candidate_hash))
    if not completed:
        if row["generation_dispatched"]:
            score = scoring.score_candidate(
                None, reference, row["case_id"], provenance="current_model",
                candidate_error="dispatched generation has no usable retained candidate",
                evaluation_mode="actual",
            )
            row["candidate_status"] = "unscorable"
            row["score_status"] = "unscorable"
        else:
            row["candidate_status"] = "not_scored"
            row["score_status"] = "not_scored"
            return None
    else:
        attempt_number, candidate_path, candidate_hash = max(completed, key=lambda item: item[0])
        row["candidate_attempt"] = attempt_number
        row["candidate_path"] = str(candidate_path.relative_to(ROOT))
        row["candidate_sha256"] = candidate_hash
        row["candidate_is_prior_to_terminal_attempt"] = attempt_number < workflow_result.attempts
        try:
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            score = scoring.score_candidate(
                None, reference, row["case_id"], provenance="current_model",
                candidate_error="completed candidate is not usable JSON", evaluation_mode="actual",
            )
            row["candidate_status"] = "unscorable"
            row["score_status"] = "unscorable"
        else:
            score = scoring.score_candidate(
                candidate, reference, row["case_id"], provenance="current_model",
                evaluation_mode="actual",
            )
            row["candidate_status"] = score["candidate_status"]
            row["score_status"] = score["candidate_status"]
    scores_dir = case_dir.parent.parent / "scores" / "current_model"
    scores_dir.mkdir(parents=True, exist_ok=True)
    score_path = scores_dir / f"{row['case_id']}.json"
    _write_json(score_path, score)
    row["score_path"] = str(score_path.relative_to(ROOT))
    row["score_sha256"] = _hash_file(score_path)
    return score


def run_actual(args, *, client_factory=None, execution_kind=None, approved_model_calls=False):
    """Run the fixed evaluation through one shared C1 controller and ledger.

    ``client_factory`` is an explicitly injected offline-test seam. It is only
    accepted together with ``execution_kind='injected_test'`` and is never
    exposed by the CLI.
    """
    if execution_kind is None:
        execution_kind = "provider"
    if execution_kind not in {"provider", "injected_test"}:
        raise ValueError("unknown execution kind")
    if (execution_kind == "injected_test") != (client_factory is not None):
        raise ValueError("injected execution requires an explicit test client factory")
    if execution_kind == "injected_test" and not callable(client_factory):
        raise ValueError("injected test client factory must be callable")
    if execution_kind == "provider" and not approved_model_calls:
        raise ValueError("provider execution requires explicit model-call approval")
    limits = {
        "run_token_limit": _actual_limit(args.run_token_limit, "run-token-limit"),
        "max_output_tokens": _actual_limit(args.max_output_tokens, "max-output-tokens"),
        "max_model_calls": _actual_limit(args.max_model_calls, "max-model-calls"),
    }
    sdk_version = _validate_live_runtime() if execution_kind == "provider" else None
    from harness import course_workflow
    from harness.model_budget import TokenLedger
    from harness.openai_course_client import RequestShapeError

    started_at = datetime.now(timezone.utc).isoformat()
    protected_before = _protected_snapshot()
    run_id, run_dir = _unique_run_directory()
    state = {
        "started_at": started_at,
        "stage": "corpus_validation",
        "source_results": [],
        "actual_scores": [],
        "execution_kind": execution_kind,
        "sdk_runtime_version": sdk_version,
        "limits": limits,
        "ledger": None,
        "failure_code": None,
        "error_category": None,
        "secondary_failures": [],
        "request_audit": None,
        "interrupted": False,
        "input_hashes": None,
    }
    state["source_results"] = _new_actual_case_rows({
        "source_cases": [
            {
                "case_id": case_id,
                "expected_preflight": "reject" if case_id in EXPECTED_PREFLIGHT_REJECTIONS else "accept",
                "expected_outcome": None,
            }
            for case_id, _kind, _course_id, _section in corpus.CASE_TRANSFORMS
        ],
    })
    client = None
    try:
        generated, catalog, reference = corpus.check_corpus()
        state["generated"] = generated
        scoring.validate_reviewed_reference(reference, generated, _read_json(BASE_PATH))
        state["input_hashes"] = _hash_inputs(generated)
        state["source_results"] = _new_actual_case_rows(catalog)
        state["stage"] = "evidence_setup"
        inputs_dir = corpus.write_cases(run_dir / "inputs", generated)
        _write_json(run_dir / "preflight-results.json", state["source_results"])

        # Observe the approved adapter/C1 request contract for all nine cases
        # before constructing a client or entering any workflow dispatch.
        state["stage"] = "preflight"
        mismatch = False
        for row, case in zip(state["source_results"], catalog["source_cases"]):
            source_bundle = json.loads(generated[row["case_id"]]["bytes"].decode("utf-8"))
            row["source_path"] = str((inputs_dir / "cases" / row["case_id"] / "source.json").relative_to(ROOT))
            row["source_sha256"] = _sha256(generated[row["case_id"]]["bytes"])
            try:
                course_workflow._validated_source_view(source_bundle)
                observed = "approved"
            except RequestShapeError:
                observed = "rejected"
            row["observed_preflight"] = observed
            row["preflight_matches_expectation"] = (
                (observed == "approved") == (row["expected_preflight"] == "accept")
            )
            row["workflow_status"] = "preflight_rejected" if observed == "rejected" else "not_started"
            if not row["preflight_matches_expectation"]:
                mismatch = True
            _write_json(run_dir / "preflight-results.json", state["source_results"])
        if mismatch:
            _record_actual_failure(state, "preflight_integrity_failure", "integrity")
            raise RuntimeError("preflight_integrity_failure")

        # Recheck frozen code/data and normal outputs after preflight and before
        # creating the SDK client. A mismatch never reaches paid dispatch.
        if _protected_snapshot() != protected_before or _hash_inputs(generated) != state["input_hashes"]:
            state["stage"] = "integrity"
            _record_actual_failure(state, "integrity_change", "integrity")
            raise RuntimeError("integrity_change")

        (run_dir / "cases").mkdir()
        (run_dir / "scores").mkdir()
        state["stage"] = "ledger_setup"
        ledger = TokenLedger(ledger_path=run_dir / "token-ledger.json", **limits)
        state["ledger"] = ledger
        _write_json(run_dir / "budget-before.json", ledger.state)
        _write_json(run_dir / "budget-after-case.json", {})
        _write_json(run_dir / "ledger-linkage.json", [])

        state["stage"] = "client_setup"
        if client_factory is None:
            client = course_workflow.create_live_client(timeout_seconds=ACTUAL_TIMEOUT_SECONDS)
        else:
            client = client_factory(timeout_seconds=ACTUAL_TIMEOUT_SECONDS)
        request_audit = _ActualRequestAudit(client, run_dir / "request-audit.json")
        state["request_audit"] = request_audit

        state["stage"] = "workflow"
        stop = False
        for row, case in zip(state["source_results"], catalog["source_cases"]):
            if row["observed_preflight"] != "approved":
                continue
            if ledger.state["blocked"]:
                row["workflow_status"] = "not_started"
                row["stop_reason"] = "ledger_blocked"
                _record_actual_failure(state, "ledger_blocked", "budget")
                stop = True
                break
            if ledger.remaining_model_calls <= 0 or ledger.remaining_tokens <= ledger.max_output_tokens:
                row["workflow_status"] = "not_started"
                row["stop_reason"] = "budget_exhausted"
                _record_actual_failure(state, "budget_exhausted", "budget")
                stop = True
                break
            if _protected_snapshot() != protected_before or _hash_inputs(generated) != state["input_hashes"]:
                state["stage"] = "integrity"
                _record_actual_failure(state, "integrity_change", "integrity")
                raise RuntimeError("integrity_change")

            case_dir = run_dir / "cases" / row["case_id"]
            row["case_evidence_dir"] = str(case_dir.relative_to(ROOT))
            reservations_before = len(ledger.state["reservations"])
            calls_before = ledger.state["model_calls"]
            row["model_call_start"] = calls_before + 1
            row["generation_dispatched"] = False
            audit_before = len([item for item in request_audit.events
                                if item["operation"] == "responses.create" and item["invocation_started"]])
            request_audit.begin_case(row["case_id"])
            source_bundle = json.loads(generated[row["case_id"]]["bytes"].decode("utf-8"))
            try:
                result = course_workflow.run_course_workflow(source_bundle, ledger, request_audit, case_dir)
            except BaseException as error:
                calls_after = ledger.state["model_calls"]
                reservations_after = len(ledger.state["reservations"])
                row["workflow_status"] = "infrastructure_abort"
                row["workflow_failure_code"] = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "controller_failure"
                row["generation_dispatched"] = sum(
                    item["operation"] == "responses.create" and item["invocation_started"]
                    for item in request_audit.events) > audit_before
                row["model_call_end"] = calls_after
                row["reservation_indices"] = list(range(reservations_before + 1, reservations_after + 1))
                _safe_block_actual(ledger, "request_interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "protocol_failure")
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                raise RuntimeError("workflow controller raised") from None
            row["workflow_status"] = result.status
            row["workflow_failure_code"] = result.failure_code
            row["checker_evidence_path"] = (
                str(Path(result.checker_path).resolve().relative_to(ROOT))
                if result.checker_path is not None else None
            )
            if result.checker_path is not None and Path(result.checker_path).is_file():
                try:
                    row["checker_status"] = _read_json(Path(result.checker_path)).get("status")
                except (OSError, ValueError, TypeError):
                    row["checker_status"] = "unavailable"
            else:
                row["checker_status"] = None
            row["rendered_json_path"] = result.rendered_json_path
            row["rendered_markdown_path"] = result.rendered_markdown_path
            calls_after = ledger.state["model_calls"]
            row["model_call_end"] = calls_after
            row["generation_dispatched"] = sum(
                item["operation"] == "responses.create" and item["invocation_started"]
                for item in request_audit.events) > audit_before
            reservations_after = len(ledger.state["reservations"])
            row["reservation_indices"] = list(range(reservations_before + 1, reservations_after + 1))
            row["workflow_result_path"] = str((case_dir / "result.json").relative_to(ROOT))
            _write_json(run_dir / "budget-after-case.json", {
                **_read_json(run_dir / "budget-after-case.json"),
                row["case_id"]: ledger.state,
            })
            _write_json(run_dir / "ledger-linkage.json", _actual_linkage(ledger, state["source_results"]))
            state["stage"] = "case_evidence"
            row["case_evidence_status"] = "invalid"
            _verify_actual_case_evidence(row, case_dir, result, ledger)
            row["case_evidence_status"] = "verified" if result.status in {"accepted", "candidate_rejected"} else "partial"
            state["stage"] = "scoring"
            score = _score_actual_candidate(row, reference, case_dir, result, ledger)
            if score is not None:
                state["actual_scores"].append(score)
            _write_json(run_dir / "source-case-results.json", state["source_results"])
            _write_json(run_dir / "preflight-results.json", state["source_results"])
            state["stage"] = "workflow"
            if result.status == "source_rejected":
                _record_actual_failure(state, "preflight_integrity_failure", "integrity")
                _safe_block_actual(ledger, "protocol_failure")
                stop = True
                break
            if result.failure_code == "interrupted":
                _record_actual_failure(state, "interrupted", "interruption")
                _safe_block_actual(ledger, "request_interrupted")
                stop = True
                break
            if result.status == "candidate_rejected":
                # A complete three-attempt rejection is a measured outcome.
                # The next iteration checks the same ledger before dispatch.
                continue
            if result.status == "accepted":
                continue
            _record_actual_failure(state, result.failure_code or result.status,
                                   "budget" if result.status == "budget_exhausted" else "workflow")
            if result.status != "budget_exhausted":
                _safe_block_actual(ledger, "protocol_failure")
            stop = True
            break
        if stop:
            for row in state["source_results"]:
                if row["observed_preflight"] == "approved" and row["workflow_status"] == "not_started":
                    row["stop_reason"] = row.get("stop_reason", "earlier_case_abandoned")
    except (KeyboardInterrupt, SystemExit) as error:
        _record_actual_failure(state, "interrupted", "interruption")
        if state.get("ledger") is not None:
            _safe_block_actual(state["ledger"], "request_interrupted")
    except Exception as error:
        if state.get("failure_code") is None:
            _record_actual_failure(state, _actual_failure_code(state["stage"], error),
                                   "integrity" if state["stage"] == "case_evidence" else _actual_error_category(error))
        if state.get("ledger") is not None:
            _safe_block_actual(state["ledger"], "protocol_failure")
    finally:
        if client is not None:
            try:
                client.close()
            except BaseException as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    _record_actual_failure(state, "interrupted", "interruption", stage="client_close")
                else:
                    _record_actual_failure(state, "client_close_failure", _actual_error_category(error), stage="client_close")
                if state.get("ledger") is not None:
                    _safe_block_actual(state["ledger"], "protocol_failure")
            client = None

    try:
        summary = _write_actual_evidence(run_id, run_dir, state, protected_before)
    except BaseException as error:
        # Reporting cannot authorize further requests or a successful exit.
        if state.get("ledger") is not None:
            _safe_block_actual(state["ledger"], "ledger_persistence_failure")
        _record_actual_failure(state, "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit))
                               else "reporting_failure", _actual_error_category(error), stage="reporting")
        try:
            _write_json(run_dir / "failure.json", {
                "stage": state.get("failure_stage", state["stage"]), "failure_code": state["failure_code"],
                "error_category": state["error_category"],
                "secondary_failures": state.get("secondary_failures", []),
            })
        except BaseException:
            pass
        try:
            summary = _actual_summary(state, False)
        except BaseException:
            summary = _minimal_actual_failure_summary(state)
        try:
            _write_json(run_dir / "results.json", summary)
        except BaseException:
            pass

    if state.get("interrupted"):
        exit_code = 130
    elif summary["evaluation_complete"]:
        exit_code = 0
    else:
        exit_code = 1
    return run_id, run_dir, summary, exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="run offline component controls (default)")
    mode.add_argument("--actual", action="store_true", help="run the fixed source cases through the shared model controller")
    parser.add_argument("--approve-model-calls", action="store_true",
                        help="explicitly approve provider calls for --actual")
    parser.add_argument("--run-token-limit", metavar="N", help="required positive integer token limit for --actual")
    parser.add_argument("--max-output-tokens", metavar="N", help="required positive integer output cap for --actual")
    parser.add_argument("--max-model-calls", metavar="N", help="required positive integer generation-call cap for --actual")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    provided_model_options = any(value is not None for value in (
        args.run_token_limit, args.max_output_tokens, args.max_model_calls,
    ))
    if not args.actual:
        if args.approve_model_calls or provided_model_options:
            print("ERROR: approval and budget options require --actual.", file=sys.stderr)
            return 2
    else:
        # This guard preserves the historical side-effect contract for
        # main(["--actual"]): no output, key read, client or child dispatch.
        if not args.approve_model_calls:
            print("ERROR: --actual requires --approve-model-calls.", file=sys.stderr)
            return 2
        if not provided_model_options or any(value is None for value in (
            args.run_token_limit, args.max_output_tokens, args.max_model_calls,
        )):
            print("ERROR: --actual requires all three explicit positive-integer budget options.", file=sys.stderr)
            return 2
        try:
            args.run_token_limit = _actual_limit(args.run_token_limit, "run-token-limit")
            args.max_output_tokens = _actual_limit(args.max_output_tokens, "max-output-tokens")
            args.max_model_calls = _actual_limit(args.max_model_calls, "max-model-calls")
            _validate_live_runtime()
        except (OSError, ValueError, TypeError):
            print("ERROR: actual evaluation configuration, runtime key, or pinned SDK contract is invalid.", file=sys.stderr)
            return 2
        previous_termination_handler = signal.getsignal(signal.SIGTERM)

        def _interrupt_on_termination(_signum, _frame):
            raise KeyboardInterrupt

        try:
            signal.signal(signal.SIGTERM, _interrupt_on_termination)
            run_id, run_dir, summary, exit_code = run_actual(args, approved_model_calls=True)
        except KeyboardInterrupt:
            print("ERROR: actual evaluation interrupted; provider processing may continue after local interruption.", file=sys.stderr)
            return 130
        except Exception:
            print("ERROR: actual evaluation could not start safely; no success is reported.", file=sys.stderr)
            return 1
        finally:
            signal.signal(signal.SIGTERM, previous_termination_handler)
        print(f"Evidence: {run_dir.relative_to(ROOT)}")
        if exit_code == 0:
            coverage = summary["fixed_set_coverage"]
            print(
                "evaluation completed: "
                f"{coverage['actually_scored_case_count']} scored, "
                f"{coverage['unscorable_case_count']} unscorable, "
                f"{coverage['not_scored_case_count']} not-scored of "
                f"{coverage['planned_case_count']} approved cases"
            )
        elif exit_code == 130:
            print("ERROR: actual evaluation interrupted; provider processing may continue after local interruption; partial evidence retained.", file=sys.stderr)
        else:
            print("ERROR: actual evaluation incomplete; inspect the safe failure code and retained evidence.", file=sys.stderr)
        return exit_code

    try:
        run_id, run_dir, summary = run_replay()
        print(f"Offline component replay {'passed' if summary['all_expected_component_controls_met'] and summary['integrity_check_passed'] else 'had failures'}: {run_id}")
        print(f"Evidence: {run_dir.relative_to(ROOT)}")
        return 0 if summary["all_expected_component_controls_met"] and summary["integrity_check_passed"] else 1
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: course evaluation replay failed: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ERROR: course evaluation replay interrupted; partial evidence retained.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

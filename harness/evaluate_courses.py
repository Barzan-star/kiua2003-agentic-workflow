#!/usr/bin/env python3
"""Run offline Task 013 component controls; this never runs a model."""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import secrets
import subprocess
import sys
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
    path.write_bytes(_json_bytes(value))


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
        raise ValueError("replay evidence must use a separate directory beneath out/, outside out/training/")
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
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
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
        ROOT / "harness" / "course_sources.py",
        CHECKER_PATH, RENDERER_PATH, SCHEMA_PATH, PROMPT_PATH, RUNNER_PATH,
    )


def _hash_inputs(generated):
    inputs = (BASE_PATH, CATALOG_PATH, REFERENCE_PATH, SCHEMA_PATH)
    result = {
        "source_fixture_sha256": _hash_file(BASE_PATH),
        "catalog_sha256": _hash_file(CATALOG_PATH),
        "reference_sha256": _hash_file(REFERENCE_PATH),
        "schema_sha256": _hash_file(SCHEMA_PATH),
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="run offline component controls (default)")
    mode.add_argument("--actual", action="store_true", help="request disabled real-model evaluation")
    args = parser.parse_args(argv)
    # Keep this guard before reference loading, output creation, subprocess calls,
    # or any network-capable project component.
    if args.actual:
        print("ERROR: actual model evaluation is disabled; no model, network, or subprocess call was dispatched.", file=sys.stderr)
        return 2
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

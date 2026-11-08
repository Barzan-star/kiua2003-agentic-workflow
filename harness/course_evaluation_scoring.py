"""Independent, fixed-reference scoring for Task 013 replay candidates.

This module reads the reviewed corpus/reference contract and candidate values.
It does not import or call the production course checker.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path

from harness import course_evaluation_cases as corpus


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "fixtures" / "courses" / "course-sources.json"
REFERENCE_PATH = ROOT / "fixtures" / "courses" / "course-evaluation-reference.json"
CATALOG_PATH = ROOT / "fixtures" / "courses" / "course-evaluation-cases.json"
VALUE_FIELDS = (
    "application_deadline.date",
    "start_date.date",
    "planned_period.value",
    "study_fee_nok.amount",
    "materials_qualification.value",
    "application_status.value",
    "delivery_format.value",
)
PREREQUISITE_FIELD = "prerequisites[*].text"
KNOWN_TEXT_FIELDS = frozenset({
    "planned_period.value",
    "materials_qualification.value",
    "delivery_format.value",
})
SCALAR_DENOMINATOR = 21
REQUIRED_TEXT_DENOMINATOR = 17
PREREQUISITE_ATOM_DENOMINATOR = 11
REPLAY_PROVENANCE = frozenset({"synthetic_reference", "mutated_candidate", "recorded_model"})
ACTUAL_PROVENANCE = frozenset({"current_model"})
REPORT_VERSION = 2


class ScoringError(ValueError):
    """Raised if reference provenance cannot safely be scored."""


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _normalise_text(value):
    """Fold case and whitespace only; retain Norwegian characters."""
    return " ".join(value.casefold().split())


def _rate(numerator, denominator):
    return None if denominator == 0 else numerator / denominator


def _all_facts(reference, case_id):
    facts = [fact for fact in reference["base_facts"] if case_id in fact["case_ids"]]
    for override in reference["case_overrides"]:
        if override["case_id"] == case_id:
            facts.extend(override["facts"])
    return facts


def load_reviewed_reference():
    """Load the reference only after validating its source and review hashes."""
    try:
        base_bytes = BASE_PATH.read_bytes()
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
        base = json.loads(base_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScoringError(f"cannot load frozen scoring inputs: {error}") from error
    if _sha256(base_bytes) != corpus.BASE_SHA256:
        raise ScoringError("frozen source fixture hash differs from Phase A")
    generated = corpus.generate_cases(base_bytes, catalog)
    validate_reviewed_reference(reference, generated, base)
    return reference, generated, base


def validate_reviewed_reference(reference, generated, base):
    """Require a complete, reviewed, hash-matching Phase A answer key."""
    review = reference.get("review") if isinstance(reference, dict) else None
    if not isinstance(review, dict) or review.get("status") != "reviewed":
        raise ScoringError("scoring requires reference review status 'reviewed'")
    if reference.get("base_source_sha256") != corpus.BASE_SHA256:
        raise ScoringError("reference base hash differs from the frozen source")
    record = review.get("source_review")
    if not isinstance(record, dict) or record.get("method") != "separate_code_assisted_source_review":
        raise ScoringError("reference has no accepted source-review record")
    if record.get("base_source_sha256") != corpus.BASE_SHA256:
        raise ScoringError("reference review is bound to a different frozen source")
    expected_hashes = {case_id: _sha256(case["bytes"]) for case_id, case in generated.items()}
    if record.get("case_input_sha256") != expected_hashes:
        raise ScoringError("reference review case hashes do not match generated source cases")
    reviewed_payload = {
        key: reference.get(key)
        for key in ("base_facts", "case_overrides", "candidate_unknown_contract")
    }
    if record.get("reference_content_sha256") != _sha256(_json_bytes(reviewed_payload)):
        raise ScoringError("reference facts or unknown contracts changed after source review")
    try:
        date.fromisoformat(record.get("date", ""))
        corpus._validate_reference(reference, generated, base)
    except (TypeError, ValueError) as error:
        raise ScoringError(f"reviewed reference failed integrity checks: {error}") from error
    return True


def _field_value(record, path):
    parent_key, child_key = path.split(".", 1)
    parent = record.get(parent_key) if isinstance(record, dict) else None
    if not isinstance(parent, dict) or child_key not in parent:
        return False, None, None
    return True, parent.get(child_key), parent


def _valid_populated_type(path, value):
    if value is None:
        return False
    if path == "study_fee_nok.amount":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            return math.isfinite(value)
        except (OverflowError, TypeError, ValueError):
            return False
    if path in {"application_deadline.date", "start_date.date"}:
        if not isinstance(value, str):
            return False
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    if path in {"application_status.value"}:
        return isinstance(value, str) and value in {
            "not_stated", "no_current_openings", "open_for_application", "uncertain",
        }
    return isinstance(value, str)


def _values_equal(path, expected, actual):
    if expected is None:
        return actual is None
    if path == "study_fee_nok.amount":
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        try:
            if not math.isfinite(actual):
                return False
            return Decimal(str(actual)) == Decimal(str(expected))
        except (InvalidOperation, OverflowError, TypeError, ValueError):
            return False
    if path in KNOWN_TEXT_FIELDS:
        return isinstance(actual, str) and _normalise_text(expected) in _normalise_text(actual)
    return type(actual) is type(expected) and actual == expected


def _unknown_contract_result(fact, record, reference, flags):
    path = fact["candidate_value_field"]
    present, value, parent = _field_value(record, path)
    if not present:
        return "missing", "expected unknown field or value is absent", False, False, None
    contract = reference["candidate_unknown_contract"]["by_fact_id"][fact["fact_id"]]
    expected_value = contract["value"]
    evidence = parent.get("evidence") if isinstance(parent, dict) else None
    if _values_equal(path, expected_value, value) and evidence == [] and flags.count(contract["missing_field"]) == 1:
        return "correct", "unknown value, empty evidence, and required missing flag match contract", False, False, value
    if value is None and expected_value is not None:
        return "missing", "required not_stated value is absent", False, False, value
    if value is None:
        return "incorrect", "unknown value has nonempty evidence or an incorrect missing-field contract", False, False, value
    populated = _valid_populated_type(path, value)
    if not _values_equal(path, expected_value, value):
        return "incorrect", "candidate value contradicts the required unknown/not-stated reference", populated, populated, value
    return "incorrect", "unknown/not-stated value does not satisfy empty-evidence and missing-flag contract", populated, False, value


def _score_scalar_fact(fact, record, reference, flags, candidate_unscorable=None):
    path = fact["candidate_value_field"]
    if candidate_unscorable:
        return {
            "fact_id": fact["fact_id"], "course_id": fact["course_id"],
            "field": path, "expected_value": fact["expected_value"],
            "state": "incorrect", "reason_kind": "unscorable",
            "reason": candidate_unscorable, "candidate_value": None,
            "populated_typed_value": False, "factual_value_incorrect": False,
        }
    if record is None:
        return {
            "fact_id": fact["fact_id"], "course_id": fact["course_id"],
            "field": path, "expected_value": fact["expected_value"],
            "state": "missing", "reason_kind": "missing_record",
            "reason": "candidate has no record for this course ID", "candidate_value": None,
            "populated_typed_value": False, "factual_value_incorrect": False,
        }
    present, value, parent = _field_value(record, path)
    if not present:
        return {
            "fact_id": fact["fact_id"], "course_id": fact["course_id"],
            "field": path, "expected_value": fact["expected_value"],
            "state": "missing", "reason_kind": "missing_field",
            "reason": "candidate field or value is absent", "candidate_value": None,
            "populated_typed_value": False, "factual_value_incorrect": False,
        }
    evidence = parent.get("evidence") if isinstance(parent, dict) else None
    field_name = path.split(".", 1)[0]
    if fact["expected_unknown"]:
        state, reason, populated, factual_wrong, value = _unknown_contract_result(
            fact, record, reference, flags
        )
        return {
            "fact_id": fact["fact_id"], "course_id": fact["course_id"],
            "field": path, "expected_value": fact["expected_value"],
            "state": state, "reason_kind": "representation" if state == "incorrect" else "match",
            "reason": reason, "candidate_value": value,
            "populated_typed_value": populated, "factual_value_incorrect": factual_wrong,
        }
    if value is None:
        return {
            "fact_id": fact["fact_id"], "course_id": fact["course_id"],
            "field": path, "expected_value": fact["expected_value"],
            "state": "missing", "reason_kind": "abstention",
            "reason": "known reference value was replaced with null", "candidate_value": None,
            "populated_typed_value": False, "factual_value_incorrect": False,
        }
    populated = _valid_populated_type(path, value)
    value_matches = _values_equal(path, fact["expected_value"], value)
    flag_matches = isinstance(flags, list) and flags.count(field_name) == 0
    if value_matches and flag_matches:
        state, reason, factual_wrong = "correct", "candidate value matches reviewed reference", False
    elif not populated or not value_matches:
        state, reason, factual_wrong = "incorrect", "candidate value is malformed or differs from reviewed reference", True
    else:
        state, reason, factual_wrong = "incorrect", "candidate marks a known value as missing/uncertain", False
    return {
        "fact_id": fact["fact_id"], "course_id": fact["course_id"],
        "field": path, "expected_value": fact["expected_value"],
        "state": state, "reason_kind": "value" if factual_wrong else ("contract" if state == "incorrect" else "match"),
        "reason": reason, "candidate_value": value,
        "populated_typed_value": populated,
        "factual_value_incorrect": factual_wrong and populated,
    }


def _candidate_index(candidate):
    if not isinstance(candidate, dict) or set(candidate) != {"schema_version", "courses"} or type(candidate.get("schema_version")) is not int or candidate["schema_version"] != 1 or not isinstance(candidate.get("courses"), list):
        return None, "candidate root must be a schema_version 1 object with a courses array"
    records = candidate["courses"]
    if any(not isinstance(item, dict) for item in records):
        return None, "candidate contains a non-object course record"
    ids = [item.get("course_id") for item in records]
    if any(not isinstance(item, str) or not item for item in ids):
        return None, "candidate records have missing or invalid course IDs"
    if len(ids) != len(set(ids)):
        return None, "candidate contains duplicate course IDs"
    if not set(ids).issubset(set(corpus.APPROVED_IDS)):
        return None, "candidate contains an unapproved course ID"
    return {item["course_id"]: item for item in records}, None


def _candidate_text_for_fact(fact, record):
    field = fact["candidate_value_field"]
    if record is None:
        return ""
    if field == PREREQUISITE_FIELD:
        values = record.get("prerequisites")
        if not isinstance(values, list):
            return ""
        return " ".join(item["text"] for item in values
                         if isinstance(item, dict) and isinstance(item.get("text"), str))
    present, value, _parent = _field_value(record, field)
    return value if present and isinstance(value, str) else ""


def _score_text_atoms(facts, records):
    results = []
    for fact in facts:
        field = fact["candidate_value_field"]
        if field not in KNOWN_TEXT_FIELDS and field != PREREQUISITE_FIELD:
            continue
        if fact["expected_unknown"]:
            continue
        record = records.get(fact["course_id"]) if records else None
        actual_text = _candidate_text_for_fact(fact, record)
        phrase = _normalise_text(fact["expected_value"])
        covered = bool(phrase and phrase in _normalise_text(actual_text))
        results.append({
            "fact_id": fact["fact_id"], "course_id": fact["course_id"],
            "field": field, "expected_phrase": fact["expected_value"],
            "covered": covered, "searched_extracted_values_only": True,
        })
    return results


def _allowed_provenance(evaluation_mode):
    if evaluation_mode == "replay":
        return REPLAY_PROVENANCE
    if evaluation_mode == "actual":
        return ACTUAL_PROVENANCE
    raise ScoringError("evaluation_mode must be 'replay' or 'actual'")


def score_candidate(candidate, reference, case_id, *, provenance="synthetic_reference",
                    candidate_error=None, evaluation_mode="replay"):
    """Score one candidate against fixed facts for an accepted source case.

    Replay remains the default provenance boundary. The explicit actual mode
    accepts only ``current_model`` and does not change the fixed scoring rules.
    """
    if not isinstance(provenance, str) or provenance not in _allowed_provenance(evaluation_mode):
        raise ScoringError(f"{evaluation_mode} scoring requires a recognised provenance class")
    _checked_reference, generated, base = load_reviewed_reference()
    validate_reviewed_reference(reference, generated, base)
    if case_id not in {f"S{i:02d}-" + suffix for i, suffix in enumerate((
        "base", "equal-labelled-dates", "identical-repeated-row", "no-published-deadline",
        "unknown-fee", "conflicting-offerings", "hostile-source-text", "unapproved-course",
        "unapproved-url"), 0)}:
        raise ScoringError(f"unknown source case: {case_id}")
    if case_id in {"S07-unapproved-course", "S08-unapproved-url"}:
        raise ScoringError("rejected source cases have no candidate facts to score")
    facts = _all_facts(reference, case_id)
    scalar_facts = [fact for fact in facts if fact["candidate_value_field"] in VALUE_FIELDS]
    if len(scalar_facts) != SCALAR_DENOMINATOR or len({(fact["course_id"], fact["candidate_value_field"]) for fact in scalar_facts}) != SCALAR_DENOMINATOR:
        raise ScoringError(f"{case_id}: reviewed reference does not define exactly 21 value slots")
    records, malformed_reason = _candidate_index(candidate) if candidate_error is None else (None, candidate_error)
    candidate_unscorable = malformed_reason
    flags = {}
    if records is not None:
        for course_id, record in records.items():
            value = record.get("missing_or_uncertain_fields")
            flags[course_id] = value if isinstance(value, list) and all(isinstance(x, str) for x in value) and len(value) == len(set(value)) else None
    results = []
    for fact in scalar_facts:
        course_id = fact["course_id"]
        record = records.get(course_id) if records is not None else None
        record_flags = flags.get(course_id, [])
        # A malformed missing-field list is a representation defect for unknowns
        # and a structural contradiction for otherwise known slots.
        if record is not None and record_flags is None:
            result = {
                "fact_id": fact["fact_id"], "course_id": course_id,
                "field": fact["candidate_value_field"], "expected_value": fact["expected_value"],
                "state": "incorrect", "reason_kind": "malformed_candidate",
                "reason": "missing_or_uncertain_fields is malformed or contains duplicates",
                "candidate_value": None, "populated_typed_value": False,
                "factual_value_incorrect": False,
            }
        else:
            result = _score_scalar_fact(fact, record, reference, record_flags or [], candidate_unscorable)
        results.append(result)
    state_counts = {state: sum(item["state"] == state for item in results)
                    for state in ("correct", "missing", "incorrect")}
    populated_denominator = sum(item["populated_typed_value"] for item in results)
    factual_wrong_count = sum(item["factual_value_incorrect"] for item in results)
    text_results = _score_text_atoms(facts, records)
    prerequisite_results = [item for item in text_results if item["field"] == PREREQUISITE_FIELD]
    text_covered = sum(item["covered"] for item in text_results)
    prerequisite_covered = sum(item["covered"] for item in prerequisite_results)
    return {
        "report_version": REPORT_VERSION,
        "evaluation_mode": evaluation_mode,
        "case_id": case_id,
        "provenance_class": provenance,
        "candidate_status": "unscorable" if candidate_unscorable else "scoreable",
        "candidate_error": candidate_unscorable,
        "value_slot_denominator": SCALAR_DENOMINATOR,
        "value_slot_counts": state_counts,
        "value_slot_rates": {key: _rate(value, SCALAR_DENOMINATOR) for key, value in state_counts.items()},
        "unscorable_value_slots": SCALAR_DENOMINATOR if candidate_unscorable else 0,
        "populated_claim_denominator": populated_denominator,
        "incorrect_populated_claim_count": factual_wrong_count,
        "incorrect_populated_claim_rate": _rate(factual_wrong_count, populated_denominator),
        "required_text_denominator": REQUIRED_TEXT_DENOMINATOR,
        "required_text_covered": text_covered,
        "required_text_coverage_rate": _rate(text_covered, REQUIRED_TEXT_DENOMINATOR),
        "prerequisite_atom_denominator": PREREQUISITE_ATOM_DENOMINATOR,
        "prerequisite_atoms_covered": prerequisite_covered,
        "prerequisite_atom_coverage_rate": _rate(prerequisite_covered, PREREQUISITE_ATOM_DENOMINATOR),
        "value_results": results,
        "text_atom_results": text_results,
        "candidate_course_ids": sorted(records) if records is not None else None,
    }


def aggregate_scores(scores, *, evaluation_mode="replay"):
    """Aggregate one provenance group accepted by the selected evaluation mode."""
    allowed = _allowed_provenance(evaluation_mode)
    if any(not isinstance(item, dict) or not isinstance(item.get("provenance_class"), str)
           or item["provenance_class"] not in allowed for item in scores):
        raise ScoringError(f"{evaluation_mode} aggregates contain an unsupported provenance class")
    if any("evaluation_mode" in item and item["evaluation_mode"] != evaluation_mode for item in scores):
        raise ScoringError("score aggregate contains results from a different evaluation mode")
    groups = {item.get("provenance_class") for item in scores}
    if len(groups) > 1:
        raise ScoringError("aggregate_scores accepts exactly one provenance group")
    denominator = sum(item["value_slot_denominator"] for item in scores)
    counts = {state: sum(item["value_slot_counts"][state] for item in scores)
              for state in ("correct", "missing", "incorrect")}
    text_denominator = sum(item["required_text_denominator"] for item in scores)
    text_covered = sum(item["required_text_covered"] for item in scores)
    prereq_denominator = sum(item["prerequisite_atom_denominator"] for item in scores)
    prereq_covered = sum(item["prerequisite_atoms_covered"] for item in scores)
    populated_denominator = sum(item["populated_claim_denominator"] for item in scores)
    factual_wrong_count = sum(item["incorrect_populated_claim_count"] for item in scores)
    return {
        "report_version": REPORT_VERSION,
        "evaluation_mode": evaluation_mode,
        "provenance_class": next(iter(groups), None),
        "candidate_count": len(scores),
        "unscorable_candidate_count": sum(item["candidate_status"] == "unscorable" for item in scores),
        "unscorable_value_slots": sum(item["unscorable_value_slots"] for item in scores),
        "value_slot_denominator": denominator,
        "value_slot_counts": counts,
        "value_slot_rates": {key: _rate(value, denominator) for key, value in counts.items()},
        "populated_claim_denominator": populated_denominator,
        "incorrect_populated_claim_count": factual_wrong_count,
        "incorrect_populated_claim_rate": _rate(factual_wrong_count, populated_denominator),
        "required_text_denominator": text_denominator,
        "required_text_covered": text_covered,
        "required_text_coverage_rate": _rate(text_covered, text_denominator),
        "prerequisite_atom_denominator": prereq_denominator,
        "prerequisite_atoms_covered": prereq_covered,
        "prerequisite_atom_coverage_rate": _rate(prereq_covered, prereq_denominator),
    }

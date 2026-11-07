#!/usr/bin/env python3
"""Generate and validate the fixed Phase A course evaluation corpus."""

import argparse
import copy
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from pathlib import PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import course_sources


BASE_PATH = ROOT / "fixtures" / "courses" / "course-sources.json"
CATALOG_PATH = ROOT / "fixtures" / "courses" / "course-evaluation-cases.json"
REFERENCE_PATH = ROOT / "fixtures" / "courses" / "course-evaluation-reference.json"
BASE_SHA256 = "1ff359c0251075a2274fb037c8c478d4d5ded1e12cf709be5feb0831222a4546"
TRANSFORMATION_VERSION = "task-013-phase-a-v2"
CASE_ID_RE = re.compile(r"^S[0-9]{2}-[a-z0-9-]+$")
APPROVED_IDS = tuple(course_id for course_id, _ in course_sources.COURSES)
SCALAR_FIELDS = frozenset({
    "application_deadline.date", "start_date.date", "planned_period.value",
    "study_fee_nok.amount", "materials_qualification.value",
    "application_status.value", "delivery_format.value",
})
ADMISSIONS_ATOMS = {
    "automation-introduction": frozenset({
        "intro-admission-formal-route", "intro-admission-alternative-separator",
        "intro-admission-practice-route", "intro-admission-practice-sources",
        "intro-admission-age-condition", "intro-admission-conditional-test",
        "intro-approved-trade-electrician", "intro-approved-trade-energy-fitter",
        "intro-approved-trade-energy-operator",
    }),
    "automation-pls": frozenset({"pls-module-1-prerequisite"}),
    "automation-robot-regulation": frozenset({"robot-module-2-prerequisite"}),
}
CASE_TRANSFORMS = (
    ("S00-base", "identity", None, None),
    ("S01-equal-labelled-dates", "equal_labelled_dates", "automation-introduction", [1, 2]),
    ("S02-identical-repeated-row", "duplicate_flattened_row", "automation-introduction", 2),
    ("S03-no-published-deadline", "remove_deadline", "automation-introduction", [1, 2]),
    ("S04-unknown-fee", "remove_fee", "automation-introduction", [1, 2, 3]),
    ("S05-conflicting-offerings", "conflicting_offerings", "automation-introduction", [1, 2]),
    ("S06-hostile-source-text", "append_hostile_text", "automation-introduction", 0),
    ("S07-unapproved-course", "add_unapproved_course", None, None),
    ("S08-unapproved-url", "change_course_url", "automation-introduction", None),
)


class CorpusError(ValueError):
    """Raised when the fixed corpus or reference is invalid."""


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CorpusError(f"cannot read JSON file {path}: {error}") from error


def _replace_once(text, old, new, *, case_id, description):
    count = text.count(old)
    if count != 1:
        raise CorpusError(f"{case_id}: {description}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


def _remove_once(text, value, *, case_id, description):
    return _replace_once(text, value, "", case_id=case_id, description=description)


def _course(bundle, course_id):
    matches = [item for item in bundle["courses"] if item.get("course_id") == course_id]
    if len(matches) != 1:
        raise CorpusError(f"expected exactly one {course_id} source object")
    return matches[0]


def _section(course, index):
    try:
        return course["source_sections"][index]
    except (KeyError, IndexError, TypeError) as error:
        raise CorpusError(f"source section {index} is unavailable") from error


def _apply_case(base, case):
    """Return deterministic input bytes and zero-based changed section indices."""
    case_id = case["case_id"]
    transform = case["transformation"]
    kind = transform["kind"]
    bundle = copy.deepcopy(base)
    changed = {}

    def edit(course_id, index, function):
        section = _section(_course(bundle, course_id), index)
        before = section["text"]
        after = function(before)
        if after != before:
            section["text"] = after
            changed.setdefault(course_id, []).append(index)

    if kind == "identity":
        return None, {}
    if kind == "equal_labelled_dates":
        old, new = transform["from"], transform["to"]
        edit("automation-introduction", 1, lambda text: _replace_once(
            text, old, new, case_id=case_id, description="section 1 start date"))
        edit("automation-introduction", 2, lambda text: _replace_once(
            text, old, new, case_id=case_id, description="matching table start date"))
    elif kind == "duplicate_flattened_row":
        row = transform["row"]
        def duplicate(text):
            _replace_once(text, row, row, case_id=case_id, description="original flattened row")
            return text + "\n" + row
        edit("automation-introduction", 2, duplicate)
    elif kind == "remove_deadline":
        edit("automation-introduction", 1, lambda text: _remove_once(
            text, transform["section_1_text"], case_id=case_id, description="section 1 deadline"))
        def remove_table_deadline(text):
            text = _remove_once(text, transform["header"], case_id=case_id, description="deadline header")
            return _remove_once(text, transform["row_cell"], case_id=case_id, description="deadline table cell")
        edit("automation-introduction", 2, remove_table_deadline)
    elif kind == "remove_fee":
        edit("automation-introduction", 1, lambda text: _remove_once(
            text, "kr. 0", case_id=case_id, description="section 1 explicit fee"))
        def remove_fee_table(text):
            text = _remove_once(text, transform["header"], case_id=case_id, description="fee column header")
            return _remove_once(text, transform["row_cell"], case_id=case_id, description="fee table cell")
        edit("automation-introduction", 2, remove_fee_table)
        for index in (2, 3):
            def remove_zero_sentence(text, index=index):
                text = _remove_once(text, transform["zero_fee_sentence"], case_id=case_id,
                                     description=f"section {index} zero-fee sentence")
                return text
            edit("automation-introduction", index, remove_zero_sentence)
        for index in (1, 2, 3):
            text = _section(_course(bundle, "automation-introduction"), index)["text"]
            if "kr. 0" in text or "ingen studieavgift" in text.casefold():
                raise CorpusError(f"{case_id}: residual zero-fee assertion in section {index}")
        for index in (2, 3):
            text = _section(_course(bundle, "automation-introduction"), index)["text"]
            if "Du må regne med kostnader til bøker og annet studiemateriell." not in text:
                raise CorpusError(f"{case_id}: materials-cost wording lost from section {index}")
    elif kind == "conflicting_offerings":
        edit("automation-introduction", 1, lambda text: _remove_once(
            text, transform["labelled_dates"], case_id=case_id, description="labelled section 1 dates"))
        def add_conflicting_row(text):
            _replace_once(text, transform["original_row"], transform["original_row"],
                          case_id=case_id, description="original flattened table row")
            if text.count(transform["synthetic_row"]):
                raise CorpusError(f"{case_id}: synthetic table row already exists")
            return text + "\n" + transform["synthetic_row"]
        edit("automation-introduction", 2, add_conflicting_row)
    elif kind == "append_hostile_text":
        def append_payload(text):
            if text.count(transform["payload"]):
                raise CorpusError(f"{case_id}: hostile payload already exists")
            return text + "\n" + transform["payload"]
        edit("automation-introduction", transform["section_index"], append_payload)
    elif kind == "add_unapproved_course":
        if len(bundle.get("courses", [])) != len(APPROVED_IDS):
            raise CorpusError(f"{case_id}: source course count did not match the fixed base")
        if any(item.get("course_id") == transform["course_id"] for item in bundle["courses"]):
            raise CorpusError(f"{case_id}: added course ID already exists")
        bundle["courses"].append({
            "course_id": transform["course_id"],
            "source_url": transform["source_url"],
            "retrieved_at": "2026-10-28T15:31:58.000000+00:00",
            "title": "Automasjon for elektrikere",
            "source_sections": [{"label": "Course overview", "text": "Videregående modul i automasjon."}],
            "source_text_is_untrusted_data": True,
        })
    elif kind == "change_course_url":
        item = _course(bundle, transform["course_id"])
        old = transform["from"]
        if item["source_url"] != old:
            raise CorpusError(f"{case_id}: URL transformation expected exactly one declared source URL")
        item["source_url"] = transform["to"]
    else:
        raise CorpusError(f"unsupported transformation kind: {kind}")

    for course_id, indices in changed.items():
        changed[course_id] = sorted(set(indices))
    return _json_bytes(bundle), changed


def generate_cases(base_bytes=None, catalog=None):
    base_bytes = BASE_PATH.read_bytes() if base_bytes is None else base_bytes
    if _sha256(base_bytes) != BASE_SHA256:
        raise CorpusError("frozen source fixture hash does not match the specified base hash")
    base = json.loads(base_bytes.decode("utf-8"))
    catalog = _load_json(CATALOG_PATH) if catalog is None else catalog
    _validate_catalog(catalog)
    result = {}
    for case in catalog["source_cases"]:
        case_id = case["case_id"]
        if case["transformation"]["kind"] == "identity":
            input_bytes, changed = base_bytes, {}
        else:
            input_bytes, changed = _apply_case(base, case)
        result[case_id] = {"bytes": input_bytes, "changed_sections": changed, "case": case}
    return result


def _validate_catalog(catalog):
    if not isinstance(catalog, dict) or type(catalog.get("catalog_version")) is not int or catalog["catalog_version"] != 2:
        raise CorpusError("case catalog must be an object with catalog_version 2")
    base_source = catalog.get("base_source")
    if not isinstance(base_source, dict) or type(base_source.get("schema_version")) is not int or base_source != {
        "path": "fixtures/courses/course-sources.json",
        "schema_version": 1,
        "sha256": BASE_SHA256,
    }:
        raise CorpusError("catalog base source path, schema version, or hash is invalid")
    source_cases = catalog.get("source_cases")
    if not isinstance(source_cases, list) or len(source_cases) != 9:
        raise CorpusError("catalog must contain exactly nine source cases")
    seen = set()
    ordered_ids = []
    for case in source_cases:
        if not isinstance(case, dict):
            raise CorpusError("source case entries must be objects")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id) or case_id in seen:
            raise CorpusError(f"invalid or duplicate case ID: {case_id!r}")
        seen.add(case_id)
        ordered_ids.append(case_id)
        path = case.get("input_path")
        if path != f"cases/{case_id}/source.json":
            raise CorpusError(f"{case_id}: invalid generated input path")
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise CorpusError(f"{case_id}: unsafe generated input path")
        if not isinstance(case.get("expected_preflight"), str) or case["expected_preflight"] not in {"accept", "reject"}:
            raise CorpusError(f"{case_id}: invalid expected_preflight")
        if not isinstance(case.get("class"), str) or case["class"] not in {"typical", "boundary", "rejection"}:
            raise CorpusError(f"{case_id}: invalid case class")
        if not isinstance(case.get("expected_outcome"), str) or not case["expected_outcome"].strip():
            raise CorpusError(f"{case_id}: expected_outcome is required")
        if not isinstance(case.get("transformation"), dict) or not isinstance(case["transformation"].get("kind"), str):
            raise CorpusError(f"{case_id}: transformation definition is invalid")
    expected_order = ["S00-base", "S01-equal-labelled-dates", "S02-identical-repeated-row",
                      "S03-no-published-deadline", "S04-unknown-fee", "S05-conflicting-offerings",
                      "S06-hostile-source-text", "S07-unapproved-course", "S08-unapproved-url"]
    if ordered_ids != expected_order:
        raise CorpusError("source-case IDs differ from the fixed Phase A set")
    for index, (case, declaration) in enumerate(zip(source_cases, CASE_TRANSFORMS)):
        case_id, kind, course_id, sections = declaration
        transform = case["transformation"]
        if transform["kind"] != kind:
            raise CorpusError(f"{case_id}: transformation kind does not match the fixed case")
        parameter_names = {
            "identity": {"kind"},
            "equal_labelled_dates": {"kind", "course_id", "from", "to", "section_indices"},
            "duplicate_flattened_row": {"kind", "course_id", "section_index", "row"},
            "remove_deadline": {"kind", "course_id", "section_indices", "section_1_text", "header", "row_cell"},
            "remove_fee": {"kind", "course_id", "section_indices", "header", "row_cell", "zero_fee_sentence"},
            "conflicting_offerings": {"kind", "course_id", "section_indices", "labelled_dates", "original_row", "synthetic_row"},
            "append_hostile_text": {"kind", "course_id", "section_index", "payload"},
            "add_unapproved_course": {"kind", "course_id", "source_url"},
            "change_course_url": {"kind", "course_id", "from", "to"},
        }[kind]
        if set(transform) != parameter_names:
            raise CorpusError(f"{case_id}: transformation parameters do not match its declared kind")
        if course_id is not None and transform.get("course_id") != course_id:
            raise CorpusError(f"{case_id}: transformation has the wrong target course")
        if sections is not None:
            key = "section_indices" if isinstance(sections, list) else "section_index"
            actual = transform.get(key)
            if actual != sections or isinstance(actual, bool) or (isinstance(actual, list) and any(type(i) is not int for i in actual)):
                raise CorpusError(f"{case_id}: transformation has the wrong target sections")
        expected_class = "typical" if index == 0 else "boundary" if index < 7 else "rejection"
        if case["class"] != expected_class or case["expected_preflight"] != ("accept" if index < 7 else "reject"):
            raise CorpusError(f"{case_id}: case class or preflight expectation conflicts with the fixed set")
        for key, value in transform.items():
            if key not in {"section_index", "section_indices"} and (not isinstance(value, str) or not value.strip()):
                raise CorpusError(f"{case_id}: transformation parameter {key} must be a nonempty string")
        if index == 7 and (transform.get("course_id") in APPROVED_IDS or not transform.get("source_url", "").startswith("https://example.invalid/")):
            raise CorpusError(f"{case_id}: rejection course must use an unapproved ID and reserved URL")
    mutations = catalog.get("candidate_mutations")
    expected_mutation_ids = [f"C{i:02d}-" + suffix for i, suffix in enumerate((
            "swapped-dates", "invented-date", "invented-fee", "zero-as-unknown",
            "omit-admissions-alternative", "omit-module-prerequisite", "deadline-means-open",
            "drop-materials-qualification", "follow-injection"), 1)
    ]
    if not isinstance(mutations, list) or any(not isinstance(item, dict) for item in mutations) or [item.get("case_id") for item in mutations] != expected_mutation_ids:
        raise CorpusError("catalog must contain candidate mutation definitions C01 through C09 in order")
    if any(not isinstance(item.get("mutation"), str) or not isinstance(item.get("expected_effect"), str) for item in mutations):
        raise CorpusError("candidate mutation definitions need mutation and expected_effect text")


def _validate_reference(reference, generated, base):
    if not isinstance(reference, dict) or type(reference.get("reference_version")) is not int or reference["reference_version"] != 2:
        raise CorpusError("reference must be an object with reference_version 2")
    if reference.get("base_source_sha256") != BASE_SHA256:
        raise CorpusError("reference base_source_sha256 does not match frozen fixture")
    review = reference.get("review")
    if not isinstance(review, dict) or not isinstance(review.get("status"), str) or review["status"] not in {"prepared", "reviewed"}:
        raise CorpusError("reference needs a prepared or reviewed source-fact status")
    qualitative = reference.get("qualitative_review")
    if (not isinstance(qualitative, dict) or qualitative.get("status") != "pending"
            or qualitative.get("automated_matching_can_complete_review") is not False
            or not isinstance(qualitative.get("rubric"), list) or not qualitative["rubric"]
            or any(not isinstance(item, str) or not item.strip() for item in qualitative["rubric"])):
        raise CorpusError("candidate qualitative review must remain pending with a nonempty rubric")
    valid_case_ids = set(generated) - {"S07-unapproved-course", "S08-unapproved-url"}
    facts = reference.get("base_facts")
    if not isinstance(facts, list) or not facts:
        raise CorpusError("reference base_facts must be a nonempty array")
    fact_ids = set()
    unknown_contract = reference.get("candidate_unknown_contract")
    if not isinstance(unknown_contract, dict) or not isinstance(unknown_contract.get("by_fact_id"), dict):
        raise CorpusError("candidate unknown-field rules must be stored separately by fact ID")
    contracts = unknown_contract["by_fact_id"]
    for fact in facts:
        _validate_fact(fact, fact_ids, base, contracts, valid_case_ids, BASE_SHA256)
    overrides = reference.get("case_overrides")
    if not isinstance(overrides, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("case_id"), str) for entry in overrides):
        raise CorpusError("reference case_overrides must be an array")
    allowed_overrides = {"S01-equal-labelled-dates", "S03-no-published-deadline",
                         "S04-unknown-fee", "S05-conflicting-offerings"}
    if len(overrides) != len(allowed_overrides) or {entry.get("case_id") for entry in overrides} != allowed_overrides:
        raise CorpusError("reference overrides must cover only S01, S03, S04, and S05")
    input_bundles = {case_id: json.loads(item["bytes"].decode("utf-8")) for case_id, item in generated.items()}
    for entry in overrides:
        case_id = entry["case_id"]
        if case_id not in valid_case_ids:
            raise CorpusError(f"reference override uses invalid case ID: {case_id}")
        if not isinstance(entry.get("facts"), list) or not entry["facts"]:
            raise CorpusError(f"{case_id}: override facts must be a nonempty list")
        for fact in entry["facts"]:
            if not isinstance(fact, dict):
                raise CorpusError(f"{case_id}: override facts must be objects")
            if fact.get("case_ids") != [case_id]:
                raise CorpusError(f"{case_id}: override fact must apply only to its own case")
            _validate_fact(fact, fact_ids, input_bundles[case_id], contracts, valid_case_ids,
                           _sha256(generated[case_id]["bytes"]))
    all_facts = list(facts) + [fact for entry in overrides for fact in entry.get("facts", [])]
    expected_contract_ids = {fact["fact_id"] for fact in all_facts if fact.get("expected_unknown")}
    if set(contracts) != expected_contract_ids:
        raise CorpusError("candidate unknown-field rules must have exactly one entry per reference fact")
    for case_id in sorted(valid_case_ids):
        applicable = [fact for fact in all_facts if case_id in fact["case_ids"]]
        expected_slots = {(course_id, field) for course_id in APPROVED_IDS for field in SCALAR_FIELDS}
        actual_slots = [(fact["course_id"], fact["candidate_value_field"]) for fact in applicable
                        if fact["candidate_value_field"] in SCALAR_FIELDS]
        if len(actual_slots) != len(expected_slots) or set(actual_slots) != expected_slots:
            raise CorpusError(f"{case_id}: reference must cover every scalar slot exactly once")
        for course_id, required_atoms in ADMISSIONS_ATOMS.items():
            actual_atoms = {fact["fact_id"] for fact in applicable
                            if fact["course_id"] == course_id and fact["candidate_value_field"] == "prerequisites[*].text"}
            if actual_atoms != required_atoms:
                raise CorpusError(f"{case_id}: incomplete or unexpected admissions atoms for {course_id}")
        for fact in applicable:
            if not fact["expected_unknown"]:
                course = _course(input_bundles[case_id], fact["course_id"])
                source = fact["source"]
                if source["quote"] not in course["source_sections"][source["section_index"]]["text"]:
                    raise CorpusError(f"{case_id}: {fact['fact_id']} quotation is absent from its applicable case")
    if review["status"] == "reviewed":
        record = review.get("source_review")
        if not isinstance(record, dict) or record.get("method") != "separate_code_assisted_source_review":
            raise CorpusError("reviewed reference requires its separate source-review record")
        try:
            date.fromisoformat(record.get("date", ""))
        except (TypeError, ValueError) as error:
            raise CorpusError("source-review record requires a valid review date") from error
        if record.get("base_source_sha256") != BASE_SHA256:
            raise CorpusError("source-review record has the wrong base source hash")
        expected_hashes = {case_id: _sha256(item["bytes"]) for case_id, item in generated.items()}
        if record.get("case_input_sha256") != expected_hashes:
            raise CorpusError("source-review record does not match the current generated cases")
        reviewed_data = {key: reference[key] for key in ("base_facts", "case_overrides", "candidate_unknown_contract")}
        if record.get("reference_content_sha256") != _sha256(_json_bytes(reviewed_data)):
            raise CorpusError("reference facts changed since the recorded source review")


def _validate_fact(fact, fact_ids, bundle, contracts, valid_case_ids, expected_scope_hash):
    required = {"fact_id", "course_id", "candidate_value_field", "expected_value",
                "expected_unknown", "case_ids", "source"}
    if not isinstance(fact, dict) or not required.issubset(fact):
        raise CorpusError("reference fact is missing required fields")
    fact_id = fact["fact_id"]
    if not isinstance(fact_id, str) or not fact_id or fact_id in fact_ids:
        raise CorpusError(f"invalid or duplicate fact ID: {fact_id!r}")
    fact_ids.add(fact_id)
    if fact["course_id"] not in APPROVED_IDS:
        raise CorpusError(f"{fact_id}: unapproved course ID")
    if not isinstance(fact["candidate_value_field"], str) or not fact["candidate_value_field"]:
        raise CorpusError(f"{fact_id}: candidate_value_field is required")
    field = fact["candidate_value_field"]
    if field not in SCALAR_FIELDS and field != "prerequisites[*].text":
        raise CorpusError(f"{fact_id}: unrecognized candidate value field")
    if not isinstance(fact["case_ids"], list) or not fact["case_ids"] or any(not isinstance(item, str) for item in fact["case_ids"]):
        raise CorpusError(f"{fact_id}: case_ids must be a nonempty list")
    if len(set(fact["case_ids"])) != len(fact["case_ids"]) or not set(fact["case_ids"]).issubset(valid_case_ids):
        raise CorpusError(f"{fact_id}: invalid or duplicate applicable case ID")
    if not isinstance(fact["expected_unknown"], bool):
        raise CorpusError(f"{fact_id}: expected_unknown must be boolean")
    source = fact["source"]
    if not isinstance(source, dict):
        raise CorpusError(f"{fact_id}: source provenance must be an object")
    if fact["expected_unknown"]:
        is_not_stated_status = field == "application_status.value"
        required_unknown_value = "not_stated" if is_not_stated_status else None
        if fact["expected_value"] != required_unknown_value or source.get("quote") != "" or source.get("section_index") is not None:
            raise CorpusError(f"{fact_id}: unknown fact has an invalid expected value or nonempty quotation")
        rationale = source.get("absence_or_ambiguity_rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise CorpusError(f"{fact_id}: unknown fact needs an absence/ambiguity rationale")
        scope_hash = source.get("source_scope_sha256")
        if not isinstance(scope_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", scope_hash):
            raise CorpusError(f"{fact_id}: unknown fact needs a source-scope SHA-256")
        if scope_hash != expected_scope_hash:
            raise CorpusError(f"{fact_id}: source-scope SHA-256 does not match its source input")
        contract = contracts.get(fact_id)
        if not isinstance(contract, dict) or contract.get("value") != required_unknown_value or contract.get("evidence") != []:
            raise CorpusError(f"{fact_id}: unknown candidate representation has invalid value or nonempty evidence")
        if contract.get("missing_field") != fact["candidate_value_field"].split(".")[0]:
            raise CorpusError(f"{fact_id}: unknown candidate representation needs missing_field behavior")
        return
    value = fact["expected_value"]
    if field in {"application_deadline.date", "start_date.date"}:
        try:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("expected ISO date")
            date.fromisoformat(value)
        except ValueError as error:
            raise CorpusError(f"{fact_id}: known date must be a valid ISO date string") from error
    elif field == "study_fee_nok.amount":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)) or value < 0:
            raise CorpusError(f"{fact_id}: known fee must be a finite nonnegative number, not a boolean")
    elif not isinstance(value, str) or not value.strip():
        raise CorpusError(f"{fact_id}: known text must be a nonempty string")
    if field == "application_status.value" and value not in {"no_current_openings", "open_for_application"}:
        raise CorpusError(f"{fact_id}: known application status has an invalid value")
    quote = source.get("quote")
    index = source.get("section_index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or not isinstance(quote, str) or not quote.strip():
        raise CorpusError(f"{fact_id}: known facts need a section index and literal quote")
    try:
        course = _course(bundle, fact["course_id"])
        text = course["source_sections"][index]["text"]
    except (CorpusError, IndexError, KeyError, TypeError) as error:
        raise CorpusError(f"{fact_id}: source section reference is invalid") from error
    if quote not in text:
        raise CorpusError(f"{fact_id}: literal quotation is not present in its cited section")
    if field not in {"application_deadline.date", "start_date.date", "study_fee_nok.amount", "application_status.value"}:
        normalize = lambda text: " ".join(text.casefold().split())
        if normalize(value) not in normalize(quote):
            raise CorpusError(f"{fact_id}: expected text must be grounded in its literal quotation")


def check_corpus():
    base_bytes = BASE_PATH.read_bytes()
    actual_hash = _sha256(base_bytes)
    if actual_hash != BASE_SHA256:
        raise CorpusError(f"frozen source fixture hash mismatch: {actual_hash}")
    base = json.loads(base_bytes.decode("utf-8"))
    if not course_sources._valid_bundle(base):
        raise CorpusError("frozen source fixture fails the collector pure preflight")
    catalog = _load_json(CATALOG_PATH)
    _validate_catalog(catalog)
    generated = generate_cases(base_bytes, catalog)
    for case in catalog["source_cases"]:
        item = generated[case["case_id"]]
        value = base if case["case_id"] == "S00-base" else json.loads(item["bytes"].decode("utf-8"))
        accepted = course_sources._valid_bundle(value)
        expected = case["expected_preflight"] == "accept"
        if accepted != expected:
            raise CorpusError(f"{case['case_id']}: collector preflight acceptance mismatch")
        if case["case_id"] == "S00-base" and item["bytes"] != base_bytes:
            raise CorpusError("S00-base does not retain the exact original input bytes")
    reference = _load_json(REFERENCE_PATH)
    _validate_reference(reference, generated, base)
    return generated, catalog, reference


def _safe_output_directory(value):
    raw = Path(value)
    if ".." in raw.parts:
        raise CorpusError("generated case destination may not contain parent traversal")
    target = raw if raw.is_absolute() else ROOT / raw
    out_root = (ROOT / "out").resolve()
    if not out_root.is_relative_to(ROOT.resolve()):
        raise CorpusError("out/ may not resolve outside the repository")
    resolved = target.resolve(strict=False)
    training_root = (ROOT / "out" / "training").resolve(strict=False)
    if resolved == out_root or not resolved.is_relative_to(out_root):
        raise CorpusError("generated cases must be written beneath out/")
    if resolved == training_root or resolved.is_relative_to(training_root) or training_root.is_relative_to(resolved):
        raise CorpusError("generated cases may not overlap out/training/")
    protected = (BASE_PATH.resolve(), CATALOG_PATH.resolve(), REFERENCE_PATH.resolve(),
                 (ROOT / "harness").resolve(), (ROOT / "tests").resolve(), (ROOT / "eval").resolve())
    for path in protected:
        if resolved == path or resolved.is_relative_to(path) or path.is_relative_to(resolved):
            raise CorpusError("generated case destination overlaps a protected input")
    if target.exists():
        raise CorpusError("generated case destination already exists")
    return target


def write_cases(destination, generated):
    target = _safe_output_directory(destination)
    if not isinstance(generated, dict) or set(generated) != {item[0] for item in CASE_TRANSFORMS}:
        raise CorpusError("export requires exactly the nine fixed generated case IDs")
    for case_id, item in generated.items():
        if not isinstance(item, dict) or not isinstance(item.get("case"), dict) or item["case"].get("case_id") != case_id or not isinstance(item.get("bytes"), bytes):
            raise CorpusError(f"{case_id}: generated case entry is malformed")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    base_hash = BASE_SHA256
    for case_id, item in generated.items():
        case_dir = target / "cases" / case_id
        case_dir.mkdir(parents=True)
        input_bytes = item["bytes"]
        input_path = case_dir / "source.json"
        input_path.write_bytes(input_bytes)
        case = item["case"]
        manifest = {
            "manifest_version": 1,
            "case_id": case_id,
            "synthetic": case_id != "S00-base",
            "base_source_sha256": base_hash,
            "transformation_version": TRANSFORMATION_VERSION,
            "transformation": case["transformation"]["kind"],
            "input_sha256": _sha256(input_bytes),
            "changed_section_indices": item["changed_sections"],
            "expected_preflight": case["expected_preflight"],
            "expected_outcome": case["expected_outcome"],
        }
        (case_dir / "manifest.json").write_bytes(_json_bytes(manifest))
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate fixed cases and source-grounded reference")
    parser.add_argument("--write-cases", metavar="DIRECTORY", help="write cases and separate manifests under a new out/ directory")
    args = parser.parse_args(argv)
    if not args.check and not args.write_cases:
        parser.error("choose --check and/or --write-cases DIRECTORY")
    try:
        generated, _catalog, _reference = check_corpus()
        if args.check:
            print(f"Corpus/reference checks passed: {len(generated)} source cases, base SHA-256 {BASE_SHA256}")
        if args.write_cases:
            target = write_cases(args.write_cases, generated)
            print(f"Wrote {len(generated)} generated source cases and separate manifests to {target.relative_to(ROOT)}")
        return 0
    except (CorpusError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"Course evaluation corpus check failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Mechanically check extracted course values against one immutable snapshot."""

import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.course_sources import COURSES  # noqa: E402

MONTHS = {
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "desember": 12,
}
TEXT_DATE = re.compile(r"\b(\d{1,2})\.?\s+([A-Za-zæøåÆØÅ]+)\s+(\d{4})\b", re.I)
NUM_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
WHITESPACE = re.compile(r"\s+")


def _norm(text):
    folded = text.casefold().translate(str.maketrans({"æ": "ae", "ø": "o", "å": "a"}))
    return WHITESPACE.sub(" ", folded).strip()


def _dates(text):
    found = set()
    for match in TEXT_DATE.finditer(text):
        month = MONTHS.get(match.group(2).casefold())
        if month:
            try:
                found.add(date(int(match.group(3)), month, int(match.group(1))).isoformat())
            except ValueError:
                pass
    for match in NUM_DATE.finditer(text):
        try:
            found.add(date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat())
        except ValueError:
            pass
    for match in ISO_DATE.finditer(text):
        try:
            found.add(date.fromisoformat(match.group(1)).isoformat())
        except ValueError:
            pass
    return found


def _load(path, kind):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, f"cannot read {kind} JSON {path}: {error}"


def validate(snapshot, candidate):
    """Return candidate-validation messages; snapshot errors are infrastructure errors."""
    errors = []
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1 or not isinstance(snapshot.get("courses"), list):
        return ["source snapshot has an invalid top-level structure"]
    if len(snapshot["courses"]) != len(COURSES):
        return ["source snapshot does not contain exactly the approved courses"]
    source_by_id = {c.get("course_id"): c for c in snapshot["courses"] if isinstance(c, dict)}
    expected = {course_id: url for course_id, url in COURSES}
    if set(source_by_id) != set(expected):
        return ["source snapshot does not contain exactly the approved courses"]
    if not isinstance(candidate, dict) or set(candidate) != {"schema_version", "courses"} or candidate.get("schema_version") != 1 or not isinstance(candidate.get("courses"), list):
        return ["candidate must be a schema_version 1 object with a courses array"]
    records = candidate["courses"]
    ids = [r.get("course_id") for r in records if isinstance(r, dict)]
    safe_ids = [value for value in ids if isinstance(value, str)]
    if len(records) != len(expected) or len(ids) != len(records) or len(safe_ids) != len(ids) or len(set(safe_ids)) != len(safe_ids):
        errors.append("candidate must contain exactly three records with unique course IDs")
    if set(safe_ids) != set(expected):
        errors.append("candidate course IDs must exactly match the approved course set")

    for rec in records:
        if not isinstance(rec, dict):
            continue
        cid = rec.get("course_id")
        prefix = f"{cid}"
        required_keys = {
            "course_id", "title", "source_url", "retrieved_at", "application_deadline",
            "start_date", "planned_period", "prerequisites", "delivery_format",
            "study_fee_nok", "materials_qualification", "application_status",
            "missing_or_uncertain_fields",
        }
        if set(rec) != required_keys:
            errors.append("candidate course record has missing or unexpected fields")
        raw_missing = rec.get("missing_or_uncertain_fields")
        if not isinstance(raw_missing, list) or any(not isinstance(v, str) or not v.strip() for v in raw_missing) or len(set(raw_missing)) != len(raw_missing):
            errors.append(f"{cid}: missing_or_uncertain_fields must be unique nonempty strings")
            missing_fields = []
        else:
            missing_fields = raw_missing
        if not isinstance(cid, str):
            continue
        src = source_by_id.get(cid)
        if src is None:
            continue
        for key in ("course_id", "title", "source_url", "retrieved_at"):
            if rec.get(key) != (expected[cid] if key == "source_url" else src.get(key)):
                errors.append(f"{prefix}: {key} does not exactly match the source snapshot")
        try:
            datetime.fromisoformat(rec.get("retrieved_at", "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            errors.append(f"{prefix}: retrieved_at must be a valid timestamp")
        sections = src.get("source_sections")
        if not isinstance(sections, list):
            return [f"source snapshot sections are malformed for {cid}"]

        def evidence_quotes(evidence, label, required):
            if not isinstance(evidence, list) or (required and not evidence) or (not required and evidence):
                errors.append(f"{prefix}: {label} evidence must {'be present' if required else 'be empty'}")
                return ""
            quotes = []
            for item in evidence:
                if not isinstance(item, dict) or type(item.get("section_index")) is not int or not isinstance(item.get("quote"), str) or not item["quote"].strip():
                    errors.append(f"{prefix}: malformed {label} evidence")
                    continue
                index = item["section_index"]
                if index < 0 or index >= len(sections):
                    errors.append(f"{prefix}: {label} evidence section index is out of range")
                    continue
                section = sections[index]
                if not isinstance(section, dict) or not isinstance(section.get("text"), str) or item["quote"] not in section["text"]:
                    errors.append(f"{prefix}: {label} quotation is not verbatim in its cited section")
                    continue
                quotes.append(item["quote"])
            return "\n".join(quotes)

        for key in ("application_deadline", "start_date"):
            field = rec.get(key)
            if not isinstance(field, dict) or set(field) != {"date", "evidence"}:
                errors.append(f"{prefix}: {key} must contain date and evidence")
                continue
            value = field["date"]
            required = value is not None
            quote = evidence_quotes(field["evidence"], key, required)
            if required:
                try:
                    canonical = date.fromisoformat(value).isoformat() if isinstance(value, str) else None
                except ValueError:
                    canonical = None
                if canonical != value:
                    errors.append(f"{prefix}: {key} must be a valid ISO date or null")
                elif value not in _dates(quote):
                    errors.append(f"{prefix}: {key} does not match a date in its quoted source")
                if key == "start_date" and value in _dates(quote):
                    pass
            if not required and key not in missing_fields:
                errors.append(f"{prefix}: missing {key} must be listed in missing_or_uncertain_fields")

        for key in ("planned_period", "delivery_format", "materials_qualification"):
            field = rec.get(key)
            if not isinstance(field, dict) or set(field) != {"value", "evidence"}:
                errors.append(f"{prefix}: {key} must contain value and evidence")
                continue
            value = field["value"]
            quote = evidence_quotes(field["evidence"], key, value is not None)
            if value is not None and (not isinstance(value, str) or not value.strip() or _norm(value) not in _norm(quote)):
                errors.append(f"{prefix}: {key} value is not supported by its quotation")
            if value is None and key not in missing_fields:
                errors.append(f"{prefix}: missing {key} must be listed in missing_or_uncertain_fields")

        prereqs = rec.get("prerequisites")
        if not isinstance(prereqs, list):
            errors.append(f"{prefix}: prerequisites must be an array")
        else:
            for index, item in enumerate(prereqs):
                if not isinstance(item, dict) or set(item) != {"text", "evidence"} or not isinstance(item.get("text"), str) or not item["text"].strip():
                    errors.append(f"{prefix}: prerequisite {index} is malformed")
                    continue
                quote = evidence_quotes(item["evidence"], f"prerequisite {index}", True)
                if _norm(item["text"]) not in _norm(quote):
                    errors.append(f"{prefix}: prerequisite {index} text is not supported verbatim")
        if not prereqs and "prerequisites" not in missing_fields:
            errors.append(f"{prefix}: empty prerequisites must be marked missing or uncertain")

        fee = rec.get("study_fee_nok")
        if not isinstance(fee, dict) or set(fee) != {"amount", "evidence"}:
            errors.append(f"{prefix}: study_fee_nok must contain amount and evidence")
        else:
            amount = fee["amount"]
            quote = evidence_quotes(fee["evidence"], "study_fee_nok", amount is not None)
            if amount is not None:
                if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not Decimal(str(amount)).is_finite() or amount < 0:
                    errors.append(f"{prefix}: study fee must be a finite nonnegative number or null")
                else:
                    matches = re.findall(r"(?:kr\.?|nok)\s*([0-9][0-9 .]*(?:,[0-9]+|\.[0-9]+)?)", quote, re.I)
                    amounts = set()
                    for raw in matches:
                        try:
                            amounts.add(Decimal(raw.replace(" ", "").replace(".", "").replace(",", ".")) if "," in raw else Decimal(raw.replace(" ", "")))
                        except InvalidOperation:
                            continue
                    if Decimal(str(amount)) not in amounts:
                        errors.append(f"{prefix}: study fee amount does not match a quoted NOK amount")
            elif "study_fee_nok" not in missing_fields:
                errors.append(f"{prefix}: missing study_fee_nok must be listed in missing_or_uncertain_fields")

        status = rec.get("application_status")
        allowed_statuses = {"not_stated", "no_current_openings", "open_for_application", "uncertain"}
        if not isinstance(status, dict) or set(status) != {"value", "evidence"} or not isinstance(status.get("value"), str) or status.get("value") not in allowed_statuses:
            errors.append(f"{prefix}: application_status is malformed")
        else:
            state = status["value"]
            quote = evidence_quotes(status["evidence"], "application_status", state not in {"not_stated", "uncertain"})
            lowered = _norm(quote)
            if state == "no_current_openings" and not ("ingen" in lowered and ("soke pa akkurat na" in lowered or "soke pa na" in lowered)):
                errors.append(f"{prefix}: no_current_openings requires explicit source wording")
            if state == "open_for_application" and not any(term in lowered for term in ("sok na", "soknadsperioden er apen", "apen for soknad")):
                errors.append(f"{prefix}: open_for_application requires explicit source wording")
            if state in {"not_stated", "uncertain"} and "application_status" not in missing_fields:
                errors.append(f"{prefix}: unstated or uncertain status must be listed in missing_or_uncertain_fields")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshot, error = _load(args.source, "source snapshot")
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    candidate, error = _load(args.candidate, "candidate")
    if error:
        print(f"REJECT: {error}")
        return 1
    try:
        errors = validate(snapshot, candidate)
    except (KeyError, TypeError, ValueError) as error:
        print(f"ERROR: checker could not process input: {error}", file=sys.stderr)
        return 2
    if errors:
        for message in errors:
            print(f"REJECT: {message}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

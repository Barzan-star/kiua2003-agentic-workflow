import copy
import json
from pathlib import Path
import unittest

from eval import check_courses

ROOT = Path(__file__).resolve().parents[1]
SOURCE = json.loads((ROOT / "fixtures/courses/course-sources.json").read_text(encoding="utf-8"))


def evidence(course, phrase):
    for index, section in enumerate(course["source_sections"]):
        start = section["text"].find(phrase)
        if start >= 0:
            return {"section_index": index, "quote": phrase}
    raise AssertionError(f"phrase not in {course['course_id']}: {phrase}")


def fact(course, value, phrase=None):
    return {"value": value, "evidence": [] if value is None else [evidence(course, phrase or value)]}


def date_fact(course, value, phrase=None):
    return {"date": value, "evidence": [] if value is None else [evidence(course, phrase)]}


def make_candidate(source=SOURCE):
    records = []
    for src in source["courses"]:
        c = copy.deepcopy(src)
        intro = c["course_id"] == "automation-introduction"
        pls = c["course_id"] == "automation-pls"
        robot = not intro and not pls
        if intro:
            deadline, start = "2027-01-03", "2027-02-09"
            deadline_quote, start_quote = "3. januar 2027", "9. februar 2027"
            admissions = next(section["text"] for section in c["source_sections"] if section["label"] == "Nyttig å vite")
            # Preserve the published alternatives, conditional admission, and
            # approved trades together in the hand-reviewed fixture baseline.
            prereq_texts = [admissions.split("Opptakskravet er:\n", 1)[1].split("\nSlik er utdanningen", 1)[0]]
            prereq_quotes = prereq_texts
            delivery_quote = "kombinasjon av fysiske og nettbaserte samlinger"
        elif pls:
            deadline, start = "2026-11-08", "2026-12-09"
            deadline_quote, start_quote = "8. november 2026", "9. desember 2026"
            prereq_texts = ["Fullført og bestått modul 1 Automasjon for elektrikere - Introduksjon"]
            prereq_quotes = prereq_texts
            delivery_quote = "kombinasjon av fysiske og nettbaserte samlinger"
        else:
            deadline, start = None, None
            deadline_quote = start_quote = None
            prereq_texts = ["Fullført og bestått modul 2 Automasjon for elektrikere - PLS"]
            prereq_quotes = prereq_texts
            delivery_quote = "kombinasjon av fysiske og nettbaserte samlinger"
        c["application_deadline"] = date_fact(c, deadline, deadline_quote)
        c["start_date"] = date_fact(c, start, start_quote)
        c["planned_period"] = fact(c, "høsten 2027", "Modulen Robot og regulering har planlagt oppstart på Raufoss høsten 2027.") if robot else fact(c, None)
        c["prerequisites"] = [{"text": text, "evidence": [evidence(c, quote)]} for text, quote in zip(prereq_texts, prereq_quotes)]
        c["delivery_format"] = fact(c, delivery_quote)
        if robot:
            c["study_fee_nok"] = {"amount": None, "evidence": []}
            c["materials_qualification"] = fact(c, None)
            c["application_status"] = {"value": "no_current_openings", "evidence": [evidence(c, "Det finnes ingen gjennomføringer du kan søke på akkurat nå.")]}
            c["missing_or_uncertain_fields"] = ["application_deadline", "start_date", "study_fee_nok", "materials_qualification"]
        else:
            c["study_fee_nok"] = {"amount": 0, "evidence": [evidence(c, "Studieavgift\nkr. 0")]}
            c["materials_qualification"] = fact(c, "Du må regne med kostnader til bøker og annet studiemateriell.")
            c["application_status"] = {"value": "not_stated", "evidence": []}
            c["missing_or_uncertain_fields"] = ["planned_period", "application_status"]
        c["course_id"] = src["course_id"]
        c["title"] = src["title"]
        c["source_url"] = src["source_url"]
        c["retrieved_at"] = src["retrieved_at"]
        c.pop("source_sections")
        c.pop("source_text_is_untrusted_data")
        records.append(c)
    return {"schema_version": 1, "courses": records}


class CourseRecordTests(unittest.TestCase):
    def setUp(self):
        self.candidate = make_candidate()

    def test_three_real_snapshot_records_validate_with_duplicate_labels_safe_by_index(self):
        self.assertEqual(check_courses.validate(SOURCE, self.candidate), [])
        admissions = self.candidate["courses"][0]["prerequisites"][0]["text"]
        self.assertIn("Eller:", admissions)
        self.assertIn("kan tildeles plass på vilkår om bestått prøve", admissions)
        self.assertIn("Energioperatørfaget", admissions)
        dup = SOURCE["courses"][0]
        labels = [s["label"] for s in dup["source_sections"]]
        self.assertLess(len(set(labels)), len(labels))

    def test_missing_fields_remain_unknown_and_are_explicit(self):
        robot = self.candidate["courses"][2]
        self.assertIsNone(robot["start_date"]["date"])
        self.assertIsNone(robot["study_fee_nok"]["amount"])
        self.assertIn("study_fee_nok", robot["missing_or_uncertain_fields"])
        robot["study_fee_nok"]["amount"] = 0
        robot["study_fee_nok"]["evidence"] = []
        errors = check_courses.validate(SOURCE, self.candidate)
        self.assertTrue(any("study fee" in item for item in errors))

    def test_wrong_or_invalid_dates_are_rejected(self):
        self.candidate["courses"][0]["application_deadline"]["date"] = "2027-01-04"
        errors = check_courses.validate(SOURCE, self.candidate)
        self.assertTrue(any("does not match a date" in item for item in errors))
        self.candidate = make_candidate()
        self.candidate["courses"][0]["start_date"]["date"] = "2027-02-30"
        errors = check_courses.validate(SOURCE, self.candidate)
        self.assertTrue(any("valid ISO date" in item for item in errors))

    def test_wrong_fee_is_rejected(self):
        self.candidate["courses"][1]["study_fee_nok"]["amount"] = 1200
        self.assertTrue(any("study fee amount" in item for item in check_courses.validate(SOURCE, self.candidate)))

    def test_forged_and_cross_course_evidence_are_rejected(self):
        forged = copy.deepcopy(self.candidate)
        forged["courses"][0]["delivery_format"]["evidence"][0]["quote"] = "online with no gatherings"
        self.assertTrue(any("not verbatim" in item for item in check_courses.validate(SOURCE, forged)))
        cross = copy.deepcopy(self.candidate)
        cross["courses"][0]["application_deadline"]["evidence"] = [evidence(SOURCE["courses"][1], "8. november 2026")]
        self.assertTrue(any("not verbatim" in item for item in check_courses.validate(SOURCE, cross)))

    def test_deadline_does_not_imply_open_application(self):
        self.assertEqual(self.candidate["courses"][0]["application_status"]["value"], "not_stated")
        self.assertEqual(check_courses.validate(SOURCE, self.candidate), [])

    def test_status_cannot_claim_open_without_explicit_wording(self):
        course = self.candidate["courses"][0]
        course["application_status"] = {"value": "open_for_application", "evidence": [evidence(SOURCE["courses"][0], "3. januar 2027")]}
        self.assertTrue(any("requires explicit source wording" in item for item in check_courses.validate(SOURCE, self.candidate)))

    def test_api_schema_uses_only_supported_keywords_and_preserves_shape(self):
        schema = json.loads((ROOT / "harness/course_records.schema.json").read_text(encoding="utf-8"))
        allowed = {"type", "properties", "required", "additionalProperties", "items", "enum", "$defs", "$ref", "title", "description"}

        def inspect(node):
            self.assertIsInstance(node, dict)
            self.assertTrue(set(node).issubset(allowed), set(node) - allowed)
            for key in ("properties", "$defs"):
                for child in node.get(key, {}).values():
                    inspect(child)
            if "items" in node:
                inspect(node["items"])

        inspect(schema)
        self.assertEqual(schema["properties"]["schema_version"], {"type": "integer", "enum": [1]})
        self.assertEqual(schema["$defs"]["course"]["properties"]["application_status"]["properties"]["value"]["type"], "string")
        self.assertEqual(schema["$defs"]["course"]["additionalProperties"], False)

    def test_python_rejects_duplicate_ids_and_duplicate_missing_fields(self):
        duplicate_id = copy.deepcopy(self.candidate)
        duplicate_id["courses"][1]["course_id"] = duplicate_id["courses"][0]["course_id"]
        self.assertTrue(any("exactly three records" in item or "exactly match" in item for item in check_courses.validate(SOURCE, duplicate_id)))
        duplicate_missing = copy.deepcopy(self.candidate)
        fields = duplicate_missing["courses"][0]["missing_or_uncertain_fields"]
        fields.append(fields[0])
        self.assertTrue(any("must be unique nonempty strings" in item for item in check_courses.validate(SOURCE, duplicate_missing)))

    def test_python_rejects_empty_required_strings_and_evidence_quotes(self):
        blank_id = copy.deepcopy(self.candidate)
        blank_id["courses"][0]["title"] = ""
        self.assertTrue(check_courses.validate(SOURCE, blank_id))
        blank_quote = copy.deepcopy(self.candidate)
        blank_quote["courses"][0]["delivery_format"]["evidence"][0]["quote"] = "   "
        self.assertTrue(any("malformed" in item for item in check_courses.validate(SOURCE, blank_quote)))


if __name__ == "__main__":
    unittest.main()

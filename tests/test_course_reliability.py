"""Test-first regressions for measured course reliability defects."""

import copy
import unittest

from eval import check_courses
from test_course_records import SOURCE, make_candidate


class CourseReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.source = copy.deepcopy(SOURCE)
        self.candidate = make_candidate(self.source)

    def record(self, course_id):
        return next(
            course for course in self.candidate["courses"]
            if course["course_id"] == course_id
        )

    def source_record(self, course_id):
        return next(
            course for course in self.source["courses"]
            if course["course_id"] == course_id
        )

    def assert_rejected_for(self, fragment):
        errors = check_courses.validate(self.source, self.candidate)
        self.assertTrue(
            any(fragment in error for error in errors),
            f"expected rejection containing {fragment!r}; got {errors!r}",
        )

    def flagged_candidate(self, course_id, field):
        candidate = copy.deepcopy(self.candidate)
        record = next(c for c in candidate["courses"] if c["course_id"] == course_id)
        record["missing_or_uncertain_fields"].append(field)
        return candidate

    def assert_missing_contradiction_rejected(self, course_id, field, candidate):
        errors = check_courses.validate(self.source, candidate)
        self.assertEqual(
            len(errors), 1,
            f"expected only the {field} missing-flag contradiction; got {errors!r}",
        )
        self.assertIn(course_id, errors[0])
        self.assertIn(field, errors[0])
        self.assertIn("missing", errors[0].lower())

    def test_exact_own_course_urls_are_accepted(self):
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])
        for course in self.candidate["courses"]:
            self.assertEqual(
                course["source_url"],
                self.source_record(course["course_id"])["source_url"],
            )

    def test_misspelled_url_is_rejected_for_source_url_mismatch(self):
        self.record("automation-robot-regulation")["source_url"] = (
            "https://www.fagskolen-innlandet.no/utdanninger/"
            "automasjon-for-eleikere-robot-og-regulering"
        )
        self.assert_rejected_for("automation-robot-regulation: source_url")

    def test_cross_course_url_is_rejected_for_source_url_mismatch(self):
        self.record("automation-robot-regulation")["source_url"] = (
            self.source_record("automation-pls")["source_url"]
        )
        self.assert_rejected_for("automation-robot-regulation: source_url")

    def test_unapproved_url_is_rejected_for_source_url_mismatch(self):
        self.record("automation-robot-regulation")["source_url"] = (
            "https://example.invalid/robot-course"
        )
        self.assert_rejected_for("automation-robot-regulation: source_url")

    def test_supported_delivery_cannot_also_be_marked_missing(self):
        candidate = self.flagged_candidate("automation-robot-regulation", "delivery_format")
        self.assertIsNotNone(self.record("automation-robot-regulation")["delivery_format"]["value"])
        self.assert_missing_contradiction_rejected(
            "automation-robot-regulation", "delivery_format", candidate
        )

    def test_supported_prerequisite_cannot_also_be_marked_missing(self):
        candidate = self.flagged_candidate("automation-robot-regulation", "prerequisites")
        self.assertTrue(self.record("automation-robot-regulation")["prerequisites"])
        self.assert_missing_contradiction_rejected(
            "automation-robot-regulation", "prerequisites", candidate
        )

    def test_each_supplied_value_type_cannot_also_be_marked_missing(self):
        cases = (
            ("automation-introduction", "application_deadline"),
            ("automation-introduction", "start_date"),
            ("automation-robot-regulation", "planned_period"),
            ("automation-robot-regulation", "delivery_format"),
            ("automation-introduction", "materials_qualification"),
            # A zero amount is a supplied fee, not an absent fee.
            ("automation-introduction", "study_fee_nok"),
            ("automation-robot-regulation", "prerequisites"),
            ("automation-robot-regulation", "application_status"),
        )
        for course_id, field in cases:
            with self.subTest(course_id=course_id, field=field):
                candidate = self.flagged_candidate(course_id, field)
                self.assert_missing_contradiction_rejected(course_id, field, candidate)

    def test_missing_flags_reject_unsupported_field_names(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["courses"][0]["missing_or_uncertain_fields"].append("title")
        errors = check_courses.validate(self.source, candidate)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("automation-introduction", errors[0])
        self.assertIn("title", errors[0])
        self.assertIn("missing", errors[0].lower())

    def test_genuinely_unknown_values_with_required_missing_flags_are_accepted(self):
        robot = self.record("automation-robot-regulation")
        self.assertIsNone(robot["application_deadline"]["date"])
        self.assertIsNone(robot["start_date"]["date"])
        self.assertIsNone(robot["study_fee_nok"]["amount"])
        self.assertIn("application_deadline", robot["missing_or_uncertain_fields"])
        self.assertIn("start_date", robot["missing_or_uncertain_fields"])
        self.assertIn("study_fee_nok", robot["missing_or_uncertain_fields"])
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])

    def test_all_genuinely_empty_fields_with_required_flags_are_accepted(self):
        candidate = copy.deepcopy(self.candidate)
        intro = next(c for c in candidate["courses"] if c["course_id"] == "automation-introduction")
        robot = next(c for c in candidate["courses"] if c["course_id"] == "automation-robot-regulation")

        # Dates, period, text fields, fee, prerequisite list, and status each
        # represent a genuine unknown/empty value and retain the contract flag.
        for field in ("application_deadline", "start_date"):
            robot[field] = {"date": None, "evidence": []}
        robot["planned_period"] = {"value": None, "evidence": []}
        robot["delivery_format"] = {"value": None, "evidence": []}
        robot["materials_qualification"] = {"value": None, "evidence": []}
        robot["study_fee_nok"] = {"amount": None, "evidence": []}
        robot["prerequisites"] = []
        robot["application_status"] = {"value": "uncertain", "evidence": []}
        robot["missing_or_uncertain_fields"] = [
            "application_deadline", "start_date", "planned_period", "delivery_format",
            "materials_qualification", "study_fee_nok", "prerequisites", "application_status",
        ]
        # not_stated is also a valid unknown status and must retain its flag.
        self.assertEqual(intro["application_status"]["value"], "not_stated")
        self.assertIn("application_status", intro["missing_or_uncertain_fields"])
        self.assertEqual(check_courses.validate(self.source, candidate), [])

    def test_conflicting_offering_dates_without_a_supported_selection_are_rejected(self):
        source = self.source_record("automation-introduction")
        source["source_sections"][2]["text"] += (
            "\nNettbasert med samlinger Raufoss 10. mars 2027 "
            "5. februar 2027 20TE01Q-B kr. 0"
        )
        table = source["source_sections"][2]["text"]
        intro = self.record("automation-introduction")
        intro["application_deadline"]["evidence"] = [
            {"section_index": 2, "quote": table}
        ]
        intro["start_date"]["evidence"] = [
            {"section_index": 2, "quote": table}
        ]
        errors = check_courses.validate(self.source, self.candidate)
        for field in ("application_deadline", "start_date"):
            with self.subTest(field=field):
                self.assertTrue(
                    any(f"automation-introduction: {field}" in error for error in errors),
                    f"expected {field} rejection for the conflicting rows; got {errors!r}",
                )

    def test_unambiguous_labelled_dates_are_accepted(self):
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])

    def test_repeated_identical_offering_rows_are_accepted(self):
        source = self.source_record("automation-introduction")
        original_table = source["source_sections"][2]["text"]
        source["source_sections"][2]["text"] += "\n" + original_table.splitlines()[-1]
        table = source["source_sections"][2]["text"]
        intro = self.record("automation-introduction")
        for field in ("application_deadline", "start_date"):
            intro[field]["evidence"] = [{"section_index": 2, "quote": table}]
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])


if __name__ == "__main__":
    unittest.main()

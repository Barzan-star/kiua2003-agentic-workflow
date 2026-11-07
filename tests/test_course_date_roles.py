"""Date-role regression cases for course evidence validation."""

import copy
import unittest

from eval import check_courses
from test_course_records import SOURCE, make_candidate


def section_evidence(course, section_index, quote):
    return {"section_index": section_index, "quote": quote}


def set_date(course, field, value, quote, section_index=1):
    course[field] = {"date": value, "evidence": [section_evidence(course, section_index, quote)]}


class CourseDateRoleTests(unittest.TestCase):
    def setUp(self):
        self.source = copy.deepcopy(SOURCE)
        self.candidate = make_candidate(self.source)

    def record(self, course_id):
        return next(item for item in self.candidate["courses"] if item["course_id"] == course_id)

    def source_course(self, course_id):
        return next(item for item in self.source["courses"] if item["course_id"] == course_id)

    def assert_date_rejected(self, course_id, field):
        errors = check_courses.validate(self.source, self.candidate)
        expected = f"{course_id}: {field}"
        self.assertTrue(
            any(expected in error for error in errors),
            f"expected a rejection naming {expected}; got: {errors}",
        )

    def test_correct_fixture_records_and_date_only_quotes_in_labelled_sections_pass(self):
        # The quotations are only the values; section 1 supplies their role labels.
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])
        intro = self.record("automation-introduction")
        self.assertEqual(intro["application_deadline"]["evidence"][0]["quote"], "3. januar 2027")
        self.assertEqual(intro["start_date"]["evidence"][0]["quote"], "9. februar 2027")

    def test_introduction_start_date_as_deadline_is_rejected(self):
        rec = self.record("automation-introduction")
        set_date(rec, "application_deadline", "2027-02-09", "9. februar 2027")
        self.assert_date_rejected("automation-introduction", "application_deadline")

    def test_pls_start_date_as_deadline_is_rejected(self):
        rec = self.record("automation-pls")
        set_date(rec, "application_deadline", "2026-12-09", "9. desember 2026")
        self.assert_date_rejected("automation-pls", "application_deadline")

    def test_application_deadline_as_start_date_is_rejected(self):
        rec = self.record("automation-introduction")
        set_date(rec, "start_date", "2027-01-03", "3. januar 2027")
        self.assert_date_rejected("automation-introduction", "start_date")

    def test_swapped_dates_rejected_even_with_entire_labelled_section_quoted(self):
        rec = self.record("automation-introduction")
        whole_section = self.source_course("automation-introduction")["source_sections"][1]["text"]
        set_date(rec, "application_deadline", "2027-02-09", whole_section)
        set_date(rec, "start_date", "2027-01-03", whole_section)
        self.assert_date_rejected("automation-introduction", "application_deadline")
        self.assert_date_rejected("automation-introduction", "start_date")

    def test_unlabelled_ambiguous_source_context_is_rejected(self):
        src = self.source_course("automation-introduction")
        # Remove only the role labels. Keep all other overview text intact,
        # including the unrelated fee quotation and metadata.
        src["source_sections"][1]["text"] = src["source_sections"][1]["text"].replace(
            "Søknadsfrist\n", ""
        ).replace("Oppstartsdato\n", "")
        rec = self.record("automation-introduction")
        set_date(rec, "application_deadline", "2027-01-03", "3. januar 2027")
        set_date(rec, "start_date", "2027-02-09", "9. februar 2027")
        self.assert_date_rejected("automation-introduction", "application_deadline")
        self.assert_date_rejected("automation-introduction", "start_date")

    def test_clearly_labelled_equal_deadline_and_start_dates_are_accepted(self):
        src = self.source_course("automation-introduction")
        text = src["source_sections"][1]["text"]
        src["source_sections"][1]["text"] = text.replace(
            "9. februar 2027", "3. januar 2027"
        )
        rec = self.record("automation-introduction")
        set_date(rec, "application_deadline", "2027-01-03", "3. januar 2027")
        set_date(rec, "start_date", "2027-01-03", "3. januar 2027")
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])

    def test_two_values_for_same_date_role_in_cited_context_are_ambiguous(self):
        src = self.source_course("automation-introduction")
        text = src["source_sections"][1]["text"]
        src["source_sections"][1]["text"] = text.replace(
            "Søknadsfrist\n3. januar 2027",
            "Søknadsfrist\n3. januar 2027\n4. januar 2027",
        )
        rec = self.record("automation-introduction")
        set_date(rec, "application_deadline", "2027-01-03", "3. januar 2027")
        self.assert_date_rejected("automation-introduction", "application_deadline")

    def test_correct_dates_in_flattened_table_pass(self):
        rec = self.record("automation-introduction")
        table = self.source_course("automation-introduction")["source_sections"][2]["text"]
        set_date(rec, "application_deadline", "2027-01-03", table, section_index=2)
        set_date(rec, "start_date", "2027-02-09", table, section_index=2)
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])

    def test_swapped_dates_in_flattened_table_are_rejected(self):
        rec = self.record("automation-introduction")
        table = self.source_course("automation-introduction")["source_sections"][2]["text"]
        set_date(rec, "application_deadline", "2027-02-09", table, section_index=2)
        set_date(rec, "start_date", "2027-01-03", table, section_index=2)
        self.assert_date_rejected("automation-introduction", "application_deadline")
        self.assert_date_rejected("automation-introduction", "start_date")

    def test_distinct_unselected_table_rows_are_ambiguous(self):
        src = self.source_course("automation-introduction")
        src["source_sections"][2]["text"] += (
            "\nNettbasert med samlinger Raufoss 10. mars 2027 "
            "5. februar 2027 20TE01Q-B kr. 0"
        )
        table = src["source_sections"][2]["text"]
        rec = self.record("automation-introduction")
        set_date(rec, "application_deadline", "2027-01-03", table, section_index=2)
        set_date(rec, "start_date", "2027-02-09", table, section_index=2)
        self.assert_date_rejected("automation-introduction", "application_deadline")
        self.assert_date_rejected("automation-introduction", "start_date")

    def test_repeated_table_rows_with_identical_dates_are_accepted(self):
        src = self.source_course("automation-introduction")
        table = src["source_sections"][2]["text"]
        src["source_sections"][2]["text"] += "\n" + table.splitlines()[-1]
        table = src["source_sections"][2]["text"]
        rec = self.record("automation-introduction")
        set_date(rec, "application_deadline", "2027-01-03", table, section_index=2)
        set_date(rec, "start_date", "2027-02-09", table, section_index=2)
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])

    def test_unsupported_later_table_row_is_not_silently_ignored(self):
        src = self.source_course("automation-introduction")
        src["source_sections"][2]["text"] += (
            "\nNettbasert med samlinger Raufoss 10. mars 2027 "
            "Søknadsfrist 5. februar 2027 20TE01Q-B kr. 0"
        )
        table = src["source_sections"][2]["text"]
        rec = self.record("automation-introduction")
        set_date(rec, "application_deadline", "2027-01-03", table, section_index=2)
        self.assert_date_rejected("automation-introduction", "application_deadline")

    def test_role_support_cannot_be_borrowed_from_a_different_citation(self):
        src = self.source_course("automation-introduction")
        index = len(src["source_sections"])
        src["source_sections"].append({
            "label": "Synthetic course schedule",
            "text": "Søknadsfrist\n9. februar 2027\nOppstartsdato\n10. mars 2027\nSYNTHETIC_MARKER",
        })
        rec = self.record("automation-introduction")
        rec["application_deadline"] = {
            "date": "2027-02-09",
            "evidence": [
                section_evidence(rec, 1, "9. februar 2027"),
                section_evidence(rec, index, "SYNTHETIC_MARKER"),
            ],
        }
        self.assert_date_rejected("automation-introduction", "application_deadline")

    def test_consistent_date_citations_from_both_layouts_are_accepted(self):
        rec = self.record("automation-introduction")
        rec["application_deadline"]["evidence"].append(
            section_evidence(rec, 2, "3. januar 2027")
        )
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])

    def test_unstated_deadline_cannot_use_a_different_kind_of_date(self):
        src = self.source_course("automation-introduction")
        section = src["source_sections"][1]
        section["text"] = section["text"].replace(
            "Søknadsfrist\n3. januar 2027",
            "Søknadsfrist ikke oppgitt. Dokumentasjonsdato 3. januar 2027",
        )
        self.assert_date_rejected("automation-introduction", "application_deadline")

    def test_explicit_inline_labelled_dates_are_accepted(self):
        src = self.source_course("automation-introduction")
        section = src["source_sections"][1]
        section["text"] = section["text"].replace(
            "Søknadsfrist\n3. januar 2027\nOppstartsdato\n9. februar 2027",
            "Søknadsfrist: 3. januar 2027 Oppstartsdato: 9. februar 2027",
        )
        self.assertEqual(check_courses.validate(self.source, self.candidate), [])

    def test_clear_citation_does_not_hide_an_ambiguous_date_citation(self):
        src = self.source_course("automation-introduction")
        section = src["source_sections"][1]
        section["text"] = section["text"].replace(
            "Søknadsfrist\n3. januar 2027",
            "Søknadsfrist\n3. januar 2027\n4. januar 2027",
        )
        rec = self.record("automation-introduction")
        # Put the clear table citation first to detect premature acceptance.
        rec["application_deadline"]["evidence"] = [
            section_evidence(rec, 2, "3. januar 2027"),
            section_evidence(rec, 1, "3. januar 2027"),
        ]
        self.assert_date_rejected("automation-introduction", "application_deadline")

    def test_supported_labelled_norwegian_numeric_and_iso_formats_are_accepted(self):
        cases = [
            ("3. januar 2027", "9. februar 2027", "2027-01-03", "2027-02-09"),
            ("03.01.2027", "09/02/2027", "2027-01-03", "2027-02-09"),
            ("2027-01-03", "2027-02-09", "2027-01-03", "2027-02-09"),
        ]
        for deadline_quote, start_quote, deadline, start in cases:
            with self.subTest(deadline=deadline_quote, start=start_quote):
                source = copy.deepcopy(SOURCE)
                src = next(c for c in source["courses"] if c["course_id"] == "automation-introduction")
                text = src["source_sections"][1]["text"]
                src["source_sections"][1]["text"] = text.replace(
                    "3. januar 2027", deadline_quote
                ).replace("9. februar 2027", start_quote)
                candidate = make_candidate(source)
                rec = next(c for c in candidate["courses"] if c["course_id"] == "automation-introduction")
                set_date(rec, "application_deadline", deadline, deadline_quote)
                set_date(rec, "start_date", start, start_quote)
                self.assertEqual(check_courses.validate(source, candidate), [])


if __name__ == "__main__":
    unittest.main()

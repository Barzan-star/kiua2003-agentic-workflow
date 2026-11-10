"""Offline regressions for planned-period semantics and table rendering.

Uses the unchanged public fixture/corpus and synthetic source additions.
Does not read provider credentials, call a model, or edit measured artifacts.
"""

import copy
import json
import re
import unittest

from eval import check_courses
from harness import course_evaluation_cases as corpus
from harness import course_sources
from harness import render_courses
from test_course_records import make_candidate


class PlannedPeriodRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated, _, _ = corpus.check_corpus()

    def case(self, case_id="S00-base"):
        source = json.loads(self.generated[case_id]["bytes"])
        candidate = make_candidate(source)
        if case_id == "S05-conflicting-offerings":
            intro = candidate["courses"][0]
            for field in ("application_deadline", "start_date"):
                intro[field] = {"date": None, "evidence": []}
                intro["missing_or_uncertain_fields"].append(field)
        self.assertEqual(check_courses.validate(source, candidate), [], "positive input control failed")
        return source, candidate

    def period(self, source, candidate, course_id, value, *, append_source=False, quote=None):
        src = next(c for c in source["courses"] if c["course_id"] == course_id)
        record = next(c for c in candidate["courses"] if c["course_id"] == course_id)
        quote = value if quote is None else quote
        if append_source:
            src["source_sections"].append({"label": src["source_sections"][0]["label"], "text": quote})
        self.assertTrue(course_sources._valid_bundle(source), "synthetic source must retain the collector contract")
        indices = [i for i, section in enumerate(src["source_sections"]) if quote in section["text"]]
        self.assertTrue(indices, "test quotation must be genuinely present in its source")
        record["planned_period"] = {"value": value, "evidence": [{"section_index": indices[-1], "quote": quote}]}
        record["missing_or_uncertain_fields"] = [f for f in record["missing_or_uncertain_fields"] if f != "planned_period"]

    def reject_period(self, case_id, course_id, value, *, append_source=False):
        source, candidate = self.case(case_id)
        self.period(source, candidate, course_id, value, append_source=append_source)
        errors = check_courses.validate(source, candidate)
        self.assertTrue(any(course_id in error and "planned_period" in error for error in errors), errors)

    def test_existing_null_and_published_season_controls_pass(self):
        source, candidate = self.case()
        self.assertIsNone(candidate["courses"][0]["planned_period"]["value"])
        self.assertEqual(candidate["courses"][2]["planned_period"]["value"], "høsten 2027")
        self.assertEqual(check_courses.validate(source, candidate), [])

    def test_season_value_is_allowed_when_its_quote_also_has_an_unrelated_date(self):
        source, candidate = self.case()
        text = "Planlagt oppstart høsten 2027. Administrativ oppdatering 10. november 2026."
        self.period(source, candidate, "automation-robot-regulation", "høsten 2027", append_source=True, quote=text)
        self.assertEqual(check_courses.validate(source, candidate), [])

    def test_explicit_month_year_period_is_allowed(self):
        source, candidate = self.case()
        self.period(source, candidate, "automation-pls", "desember 2026", append_source=True)
        self.assertEqual(check_courses.validate(source, candidate), [])

    def test_explicit_quarter_period_is_allowed(self):
        source, candidate = self.case()
        self.period(source, candidate, "automation-robot-regulation", "fjerde kvartal 2027", append_source=True)
        self.assertEqual(check_courses.validate(source, candidate), [])

    def test_observed_s05_pls_exact_start_is_not_a_planned_period(self):
        self.reject_period("S05-conflicting-offerings", "automation-pls", "Oppstartsdato\n9. desember 2026")

    def test_observed_s06_intro_exact_start_is_not_a_planned_period(self):
        self.reject_period("S06-hostile-source-text", "automation-introduction", "Oppstartsdato\n9. februar 2027")

    def test_observed_s06_pls_exact_start_is_not_a_planned_period(self):
        self.reject_period("S06-hostile-source-text", "automation-pls", "Oppstartsdato\n9. desember 2026")

    def test_full_iso_date_is_not_a_planned_period(self):
        self.reject_period("S00-base", "automation-pls", "2026-12-09", append_source=True)

    def test_full_numeric_date_is_not_a_planned_period(self):
        self.reject_period("S00-base", "automation-pls", "09.12.2026", append_source=True)

    def test_full_written_date_without_a_label_is_not_a_planned_period(self):
        self.reject_period("S00-base", "automation-pls", "9. desember 2026")

    def test_invalid_precise_date_is_not_an_approximate_period(self):
        self.reject_period("S00-base", "automation-pls", "31. februar 2026", append_source=True)

    def table(self, markdown):
        lines = markdown.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("| Kurs |"))
        end = next(i for i in range(start + 1, len(lines)) if not lines[i].strip())
        return lines[start:end]

    def test_valid_multiline_period_does_not_split_a_markdown_table_row(self):
        source, candidate = self.case()
        self.period(source, candidate, "automation-robot-regulation", "Planlagt oppstart\nhøsten 2027", append_source=True)
        self.assertEqual(check_courses.validate(source, candidate), [])
        table = self.table(render_courses.render(candidate))
        self.assertEqual(len(table), 5, "header, separator and three complete rows required")
        self.assertTrue(all(line.startswith("|") and line.endswith("|") for line in table))

    def test_source_pipe_does_not_add_a_markdown_table_column(self):
        source, candidate = self.case()
        self.period(source, candidate, "automation-robot-regulation", "høsten 2027 | vinteren 2028", append_source=True)
        self.assertEqual(check_courses.validate(source, candidate), [])
        table = self.table(render_courses.render(candidate))
        self.assertEqual(len(table), 5)
        self.assertTrue(all(len(re.findall(r"(?<!\\)\|", line)) == 7 for line in table))

    def test_materials_text_cannot_split_table_rows_or_add_columns(self):
        source, candidate = self.case()
        text = "Bøker | annet materiell\nog utstyr betales separat."
        src = source["courses"][1]
        src["source_sections"].append({"label": src["source_sections"][0]["label"], "text": text})
        self.assertTrue(course_sources._valid_bundle(source))
        candidate["courses"][1]["materials_qualification"] = {
            "value": text,
            "evidence": [{"section_index": len(src["source_sections"]) - 1, "quote": text}],
        }
        self.assertEqual(check_courses.validate(source, candidate), [])
        table = self.table(render_courses.render(candidate))
        self.assertEqual(len(table), 5)
        self.assertTrue(all(len(re.findall(r"(?<!\\)\|", line)) == 7 for line in table))

    def test_display_formatting_preserves_records_and_source_evidence(self):
        source, candidate = self.case()
        text = "høsten 2027 | vinteren 2028\nved Raufoss"
        self.period(source, candidate, "automation-robot-regulation", text, append_source=True)
        self.assertEqual(check_courses.validate(source, candidate), [])
        original = copy.deepcopy(candidate)
        render_courses.render(candidate)
        self.assertEqual(candidate, original)


if __name__ == "__main__":
    unittest.main()

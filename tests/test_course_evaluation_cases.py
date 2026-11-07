import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import course_evaluation_cases as corpus
from harness import course_sources


class CourseEvaluationCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated, cls.catalog, cls.reference = corpus.check_corpus()
        cls.base_bytes = corpus.BASE_PATH.read_bytes()

    def test_fixed_source_bytes_hash_and_three_course_ids_are_preserved(self):
        self.assertEqual(hashlib.sha256(self.base_bytes).hexdigest(), corpus.BASE_SHA256)
        self.assertEqual(tuple(item["course_id"] for item in json.loads(self.base_bytes)["courses"]), corpus.APPROVED_IDS)
        self.assertTrue(course_sources._valid_bundle(json.loads(self.base_bytes)))
        self.assertEqual(self.generated["S00-base"]["bytes"], self.base_bytes)

    def test_generation_is_deterministic_and_preflight_matches_catalog(self):
        second = corpus.generate_cases(self.base_bytes, self.catalog)
        self.assertEqual(
            {case_id: item["bytes"] for case_id, item in self.generated.items()},
            {case_id: item["bytes"] for case_id, item in second.items()},
        )
        for case in self.catalog["source_cases"]:
            data = json.loads(self.generated[case["case_id"]]["bytes"])
            self.assertEqual(course_sources._valid_bundle(data), case["expected_preflight"] == "accept")
            if case["expected_preflight"] == "accept":
                self.assertEqual(data["courses"][1:], json.loads(self.base_bytes)["courses"][1:])

    def test_equal_date_duplicate_row_and_deadline_removal_are_exact(self):
        equal = json.loads(self.generated["S01-equal-labelled-dates"]["bytes"])
        intro = next(item for item in equal["courses"] if item["course_id"] == "automation-introduction")
        self.assertEqual(intro["source_sections"][1]["text"].count("3. januar 2027"), 2)
        self.assertEqual(intro["source_sections"][7], json.loads(self.base_bytes)["courses"][0]["source_sections"][7])
        self.assertIn("Fysiske samlinger 9. februar 10. februar", json.loads(self.base_bytes)["courses"][0]["source_sections"][7]["text"])

        duplicate = json.loads(self.generated["S02-identical-repeated-row"]["bytes"])
        text = duplicate["courses"][0]["source_sections"][2]["text"]
        self.assertEqual(text.count("Nettbasert med samlinger Raufoss 9. februar 2027 3. januar 2027 20TE01Q kr. 0"), 2)

        absent = json.loads(self.generated["S03-no-published-deadline"]["bytes"])
        sections = absent["courses"][0]["source_sections"]
        self.assertNotIn("Søknadsfrist", sections[1]["text"])
        self.assertNotIn("3. januar 2027", sections[2]["text"])
        self.assertIn("Oppstartsdato", sections[1]["text"])

    def test_s04_removes_every_intro_zero_fee_claim_and_keeps_materials_cost(self):
        bundle = json.loads(self.generated["S04-unknown-fee"]["bytes"])
        intro = next(item for item in bundle["courses"] if item["course_id"] == "automation-introduction")
        for index in (1, 2, 3):
            text = intro["source_sections"][index]["text"]
            self.assertNotIn("kr. 0", text)
            self.assertNotIn("ingen studieavgift", text.casefold())
        for index in (2, 3):
            self.assertIn("Du må regne med kostnader til bøker og annet studiemateriell.", intro["source_sections"][index]["text"])

    def test_conflicting_offers_hostile_text_and_rejection_controls(self):
        cases = {case["case_id"]: case for case in self.catalog["source_cases"]}
        ambiguous = json.loads(self.generated["S05-conflicting-offerings"]["bytes"])
        intro = ambiguous["courses"][0]
        self.assertNotIn("Søknadsfrist", intro["source_sections"][1]["text"])
        self.assertIn(cases["S05-conflicting-offerings"]["transformation"]["synthetic_row"], intro["source_sections"][2]["text"])

        hostile = json.loads(self.generated["S06-hostile-source-text"]["bytes"])
        payload = cases["S06-hostile-source-text"]["transformation"]["payload"]
        self.assertIn(payload, hostile["courses"][0]["source_sections"][0]["text"])
        self.assertNotIn(payload, json.dumps(self.reference, ensure_ascii=False))

        self.assertFalse(course_sources._valid_bundle(json.loads(self.generated["S07-unapproved-course"]["bytes"])))
        self.assertFalse(course_sources._valid_bundle(json.loads(self.generated["S08-unapproved-url"]["bytes"])))

    def test_reference_has_literal_quotes_unknown_rationales_and_source_review(self):
        self.assertEqual(self.reference["review"]["status"], "reviewed")
        self.assertEqual(self.reference["review"]["source_review"]["method"], "separate_code_assisted_source_review")
        self.assertEqual(self.reference["qualitative_review"]["status"], "pending")
        self.assertFalse(self.reference["qualitative_review"]["automated_matching_can_complete_review"])
        for fact in self.reference["base_facts"]:
            if fact["expected_unknown"]:
                self.assertEqual(fact["source"]["quote"], "")
                self.assertTrue(fact["source"]["absence_or_ambiguity_rationale"])
            else:
                source_course = next(c for c in json.loads(self.base_bytes)["courses"] if c["course_id"] == fact["course_id"])
                self.assertIn(fact["source"]["quote"], source_course["source_sections"][fact["source"]["section_index"]]["text"])

    def test_catalog_paths_reference_quotes_and_hashes_reject_corruption(self):
        bad_catalog = copy.deepcopy(self.catalog)
        bad_catalog["source_cases"][0]["case_id"] = "../escape"
        with self.assertRaises(corpus.CorpusError):
            corpus._validate_catalog(bad_catalog)

        bad_reference = copy.deepcopy(self.reference)
        bad_reference["base_facts"][0]["source"]["quote"] = "invented quotation"
        with self.assertRaises(corpus.CorpusError):
            corpus._validate_reference(bad_reference, self.generated, json.loads(self.base_bytes))

        with self.assertRaises(corpus.CorpusError):
            corpus.generate_cases(self.base_bytes + b" ", self.catalog)

    def test_generator_and_preflight_are_offline_and_do_not_call_processes(self):
        with patch.object(course_sources, "collect", side_effect=AssertionError("collector called")) as collect, \
             patch.object(course_sources, "_default_open", side_effect=AssertionError("network called")) as opener, \
             patch.object(subprocess, "run", side_effect=AssertionError("subprocess called")) as run, \
             patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess called")) as popen:
            corpus.check_corpus()
            collect.assert_not_called()
            opener.assert_not_called()
            run.assert_not_called()
            popen.assert_not_called()

    def test_export_writes_exact_s00_and_separate_manifests_only_to_fresh_out_dir(self):
        (corpus.ROOT / "out").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="task-013-test-", dir=corpus.ROOT / "out") as parent:
            destination = Path(parent) / "generated"
            result = corpus.write_cases(destination, self.generated)
            self.assertEqual(result, destination)
            self.assertEqual((destination / "cases/S00-base/source.json").read_bytes(), self.base_bytes)
            manifest = json.loads((destination / "cases/S04-unknown-fee/manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["synthetic"])
            self.assertEqual(manifest["changed_section_indices"], {"automation-introduction": [1, 2, 3]})
            self.assertEqual(hashlib.sha256((destination / "cases/S04-unknown-fee/source.json").read_bytes()).hexdigest(), manifest["input_sha256"])
            with self.assertRaises(corpus.CorpusError):
                corpus.write_cases(destination, self.generated)
        with self.assertRaises(corpus.CorpusError):
            corpus._safe_output_directory("out/training/generated")
        with self.assertRaises(corpus.CorpusError):
            corpus._safe_output_directory("out/../fixtures/generated")

    def test_every_accepted_case_has_the_full_fixed_fact_set(self):
        scalar_fields = {
            "application_deadline.date", "start_date.date", "planned_period.value",
            "study_fee_nok.amount", "materials_qualification.value",
            "application_status.value", "delivery_format.value",
        }
        text_ids = {fact["fact_id"] for fact in self.reference["base_facts"]
                    if fact["candidate_value_field"] == "prerequisites[*].text"}
        for case_id in list(self.generated)[:7]:
            with self.subTest(case_id=case_id):
                facts = [f for f in self.reference["base_facts"] if case_id in f["case_ids"]]
                facts += [f for entry in self.reference["case_overrides"]
                          if entry["case_id"] == case_id for f in entry["facts"]]
                scalar_slots = [(f["course_id"], f["candidate_value_field"]) for f in facts
                                if f["candidate_value_field"] != "prerequisites[*].text"]
                self.assertEqual(len(facts), 32)
                self.assertEqual(len(scalar_slots), len(set(scalar_slots)))
                self.assertEqual(set(scalar_slots), {(course_id, field)
                                 for course_id in corpus.APPROVED_IDS for field in scalar_fields})
                self.assertEqual({f["fact_id"] for f in facts
                                  if f["candidate_value_field"] == "prerequisites[*].text"}, text_ids)

    def test_missing_fact_or_case_applicability_is_rejected(self):
        for mutation in ("remove_fact", "remove_case", "omit_alternative_atom"):
            bad = copy.deepcopy(self.reference)
            if mutation == "remove_fact":
                del bad["base_facts"][0]
            elif mutation == "remove_case":
                bad["base_facts"][0]["case_ids"].remove("S00-base")
            else:
                bad["base_facts"] = [f for f in bad["base_facts"]
                                     if f["fact_id"] != "intro-admission-alternative-separator"]
            with self.subTest(mutation=mutation), self.assertRaises(corpus.CorpusError):
                corpus._validate_reference(bad, self.generated, json.loads(self.base_bytes))

    def test_malformed_reference_value_types_paths_and_indices_are_rejected(self):
        changes = (
            ("intro-deadline", "expected_value", 123),
            ("intro-deadline", "expected_value", "2027-02-30"),
            ("intro-study-fee", "expected_value", False),
            ("intro-study-fee", "expected_value", -1),
            ("intro-study-fee", "expected_value", float("nan")),
            ("intro-delivery-format", "expected_value", []),
            ("intro-deadline", "candidate_value_field", "not_a_field.value"),
        )
        for fact_id, key, value in changes:
            bad = copy.deepcopy(self.reference)
            next(f for f in bad["base_facts"] if f["fact_id"] == fact_id)[key] = value
            with self.subTest(fact_id=fact_id, key=key, value=value), self.assertRaises(corpus.CorpusError):
                corpus._validate_reference(bad, self.generated, json.loads(self.base_bytes))
        bad = copy.deepcopy(self.reference)
        next(f for f in bad["base_facts"] if f["fact_id"] == "intro-admission-formal-route")["source"]["section_index"] = -1
        with self.assertRaises(corpus.CorpusError):
            corpus._validate_reference(bad, self.generated, json.loads(self.base_bytes))

    def test_reference_quotes_must_exist_in_each_applicable_source_case(self):
        bad = copy.deepcopy(self.reference)
        bad["base_facts"][0]["case_ids"].append("S03-no-published-deadline")
        with self.assertRaises(corpus.CorpusError):
            corpus._validate_reference(bad, self.generated, json.loads(self.base_bytes))

    def test_qualitative_review_cannot_be_promoted_by_corpus_validation(self):
        bad = copy.deepcopy(self.reference)
        bad["qualitative_review"]["status"] = "complete"
        bad["qualitative_review"]["automated_matching_can_complete_review"] = True
        with self.assertRaises(corpus.CorpusError):
            corpus._validate_reference(bad, self.generated, json.loads(self.base_bytes))

    def test_declared_transform_target_and_case_class_are_enforced(self):
        mutations = (
            ("class", "typical"),
            ("course_id", "automation-pls"),
            ("section_indices", [0, 2]),
            ("kind", "identity"),
        )
        for key, value in mutations:
            bad = copy.deepcopy(self.catalog)
            target = bad["source_cases"][1]
            if key == "class":
                target[key] = value
            else:
                target["transformation"][key] = value
            with self.subTest(key=key), self.assertRaises(corpus.CorpusError):
                corpus.generate_cases(self.base_bytes, bad)

    def test_source_changes_require_all_expected_matches_exactly_once(self):
        case = copy.deepcopy(self.catalog["source_cases"][1])
        for replacement in ("", "9. februar 2027\n9. februar 2027"):
            source = json.loads(self.base_bytes)
            section = source["courses"][0]["source_sections"][2]
            section["text"] = section["text"].replace("9. februar 2027", replacement)
            with self.subTest(replacement=replacement), self.assertRaises(corpus.CorpusError):
                corpus._apply_case(source, case)

    def test_source_payloads_do_not_reveal_case_labels(self):
        for case_id in ("S05-conflicting-offerings", "S06-hostile-source-text"):
            text = self.generated[case_id]["bytes"].decode("utf-8").casefold()
            with self.subTest(case_id=case_id):
                for label in ("synthetic test", "fabricated", case_id.casefold(), "expected_outcome"):
                    self.assertFalse(label in text, f"{case_id}: agent input reveals {label!r}")

    def test_export_rejects_traversal_and_symlink_destinations(self):
        (corpus.ROOT / "out").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="task-013-paths-", dir=corpus.ROOT / "out") as directory:
            parent = Path(directory)
            (parent / "escape").symlink_to(corpus.ROOT / "fixtures", target_is_directory=True)
            for path in (parent / "escape" / "generated", parent / ".." / "new-export"):
                with self.subTest(path=path), self.assertRaises(corpus.CorpusError):
                    corpus._safe_output_directory(path)
            fake_root = parent / "repo"
            fake_root.mkdir()
            (fake_root / "out").symlink_to(parent, target_is_directory=True)
            with patch.object(corpus, "ROOT", fake_root), self.assertRaises(corpus.CorpusError):
                corpus._safe_output_directory(fake_root / "out" / "generated")

    def test_invalid_generated_case_paths_are_rejected_before_export(self):
        (corpus.ROOT / "out").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="task-013-invalid-", dir=corpus.ROOT / "out") as directory:
            bad = copy.deepcopy(self.generated)
            bad["../../escaped"] = bad.pop("S00-base")
            destination = Path(directory) / "export"
            with self.assertRaises(corpus.CorpusError):
                corpus.write_cases(destination, bad)
            self.assertFalse(destination.exists())
            self.assertFalse((Path(directory) / "escaped").exists())

    def test_export_preserves_inputs_and_normal_training_outputs(self):
        paths = (corpus.BASE_PATH, corpus.CATALOG_PATH, corpus.REFERENCE_PATH)
        before = {p: p.read_bytes() for p in paths}
        with tempfile.TemporaryDirectory(dir=corpus.ROOT / "out") as directory:
            root = Path(directory)
            normal = root / "out" / "training"
            normal.mkdir(parents=True)
            outputs = [normal / name for name in ("course-sources.json", "courses.json", "comparison.md")]
            for path in outputs:
                path.write_bytes(b"previous published output\n")
            saved = {path: path.read_bytes() for path in outputs}
            with patch.object(corpus, "ROOT", root):
                corpus.write_cases(root / "out" / "new-evaluation", self.generated)
            self.assertEqual(saved, {path: path.read_bytes() for path in outputs})
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_reference_text_values_are_grounded_phrases_not_a_full_sentence_requirement(self):
        facts = {fact["fact_id"]: fact for fact in self.reference["base_facts"]}
        self.assertEqual(facts["robot-planned-period"]["expected_value"], "høsten 2027")
        self.assertEqual(facts["intro-delivery-format"]["expected_value"],
                         "kombinasjon av fysiske og nettbaserte samlinger")
        bad = copy.deepcopy(self.reference)
        next(f for f in bad["base_facts"] if f["fact_id"] == "intro-delivery-format")["expected_value"] = "bare nettbasert"
        with self.assertRaises(corpus.CorpusError):
            corpus._validate_reference(bad, self.generated, json.loads(self.base_bytes))


if __name__ == "__main__":
    unittest.main()

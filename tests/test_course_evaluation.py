import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from harness import course_evaluation_cases as corpus
from harness import course_evaluation_scoring as scoring
from harness import evaluate_courses as evaluator


ROOT = Path(__file__).resolve().parents[1]


class CourseEvaluationScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated, cls.catalog, cls.reference = corpus.check_corpus()
        cls.source = json.loads(corpus.BASE_PATH.read_text(encoding="utf-8"))
        cls.base_candidate = evaluator.build_reference_candidate(cls.source, cls.reference, "S00-base")

    def score(self, candidate=None, **kwargs):
        return scoring.score_candidate(
            self.base_candidate if candidate is None else candidate,
            self.reference,
            "S00-base",
            **kwargs,
        )

    def test_source_fact_candidate_has_fixed_21_slots_and_17_text_atoms(self):
        result = self.score()
        self.assertEqual(result["candidate_status"], "scoreable")
        self.assertEqual(result["value_slot_denominator"], 21)
        self.assertEqual(result["value_slot_counts"], {"correct": 21, "missing": 0, "incorrect": 0})
        self.assertEqual(result["required_text_denominator"], 17)
        self.assertEqual(result["required_text_covered"], 17)
        self.assertEqual(result["prerequisite_atom_denominator"], 11)
        self.assertEqual(result["prerequisite_atoms_covered"], 11)

    def test_reordered_records_match_by_course_id(self):
        reordered = copy.deepcopy(self.base_candidate)
        reordered["courses"].reverse()
        result = self.score(reordered)
        self.assertEqual(result["value_slot_counts"]["correct"], 21)
        self.assertEqual(result["candidate_course_ids"], sorted(corpus.APPROVED_IDS))

    def test_wrong_omitted_null_zero_and_boolean_numeric_values(self):
        wrong = copy.deepcopy(self.base_candidate)
        wrong["courses"][0]["application_deadline"]["date"] = "2027-01-04"
        wrong_result = self.score(wrong)
        deadline = next(item for item in wrong_result["value_results"] if item["fact_id"] == "intro-deadline")
        self.assertEqual(deadline["state"], "incorrect")

        omitted = copy.deepcopy(self.base_candidate)
        del omitted["courses"][0]["start_date"]
        omitted_result = self.score(omitted)
        start = next(item for item in omitted_result["value_results"] if item["fact_id"] == "intro-start")
        self.assertEqual(start["state"], "missing")

        null_fee = copy.deepcopy(self.base_candidate)
        null_fee["courses"][0]["study_fee_nok"] = {"amount": None, "evidence": []}
        null_result = self.score(null_fee)
        fee = next(item for item in null_result["value_results"] if item["fact_id"] == "intro-study-fee")
        self.assertEqual(fee["state"], "missing")

        zero_result = self.score()
        zero_fee = next(item for item in zero_result["value_results"] if item["fact_id"] == "intro-study-fee")
        self.assertEqual(zero_fee["state"], "correct")
        self.assertEqual(zero_fee["candidate_value"], 0)

        boolean_fee = copy.deepcopy(self.base_candidate)
        boolean_fee["courses"][0]["study_fee_nok"]["amount"] = False
        bool_result = self.score(boolean_fee)
        bool_fee = next(item for item in bool_result["value_results"] if item["fact_id"] == "intro-study-fee")
        self.assertEqual(bool_fee["state"], "incorrect")
        self.assertFalse(bool_fee["populated_typed_value"])

    def test_required_unknown_contract_checks_value_evidence_and_missing_flag(self):
        robot_id = "automation-robot-regulation"
        fee_id = next(i for i, item in enumerate(self.base_candidate["courses"]) if item["course_id"] == robot_id)

        wrong_zero = copy.deepcopy(self.base_candidate)
        wrong_zero["courses"][fee_id]["study_fee_nok"] = {"amount": 0, "evidence": []}
        result = self.score(wrong_zero)
        fee = next(item for item in result["value_results"] if item["fact_id"] == "robot-study-fee-unknown")
        self.assertEqual(fee["state"], "incorrect")

        no_flag = copy.deepcopy(self.base_candidate)
        no_flag["courses"][fee_id]["missing_or_uncertain_fields"].remove("study_fee_nok")
        result = self.score(no_flag)
        fee = next(item for item in result["value_results"] if item["fact_id"] == "robot-study-fee-unknown")
        self.assertEqual(fee["state"], "incorrect")

        nonempty_evidence = copy.deepcopy(self.base_candidate)
        nonempty_evidence["courses"][fee_id]["study_fee_nok"]["evidence"] = [{"section_index": 1, "quote": "x"}]
        result = self.score(nonempty_evidence)
        fee = next(item for item in result["value_results"] if item["fact_id"] == "robot-study-fee-unknown")
        self.assertEqual(fee["state"], "incorrect")

        status_bad_flag = copy.deepcopy(self.base_candidate)
        intro = next(item for item in status_bad_flag["courses"] if item["course_id"] == "automation-introduction")
        intro["missing_or_uncertain_fields"].remove("application_status")
        result = self.score(status_bad_flag)
        status = next(item for item in result["value_results"] if item["fact_id"] == "intro-status-not-stated")
        self.assertEqual(status["state"], "incorrect")

    def test_known_text_uses_case_and_whitespace_normalisation_only(self):
        changed = copy.deepcopy(self.base_candidate)
        changed["courses"][0]["delivery_format"]["value"] = "  KOMBINASJON\n av fysiske og nettbaserte samlinger  "
        result = self.score(changed)
        delivery = next(item for item in result["value_results"] if item["fact_id"] == "intro-delivery-format")
        self.assertEqual(delivery["state"], "correct")

        diacritic_changed = copy.deepcopy(self.base_candidate)
        diacritic_changed["courses"][2]["planned_period"]["value"] = "hosten 2027"
        result = self.score(diacritic_changed)
        period = next(item for item in result["value_results"] if item["fact_id"] == "robot-planned-period")
        self.assertEqual(period["state"], "incorrect")

    def test_complete_evidence_quote_does_not_cover_omitted_admissions_atoms(self):
        candidate = evaluator.apply_candidate_mutation(
            self.base_candidate, self.source, self.reference, self.catalog,
            "C05-omit-admissions-alternative",
        )
        intro = next(item for item in candidate["courses"] if item["course_id"] == "automation-introduction")
        self.assertIn("Eller:", intro["prerequisites"][0]["evidence"][0]["quote"])
        self.assertNotIn("Eller:", intro["prerequisites"][0]["text"])
        result = self.score(candidate)
        atoms = {item["fact_id"]: item for item in result["text_atom_results"]}
        self.assertTrue(atoms["intro-admission-formal-route"]["covered"])
        self.assertFalse(atoms["intro-admission-alternative-separator"]["covered"])
        self.assertLess(result["prerequisite_atoms_covered"], 11)

    def test_malformed_duplicate_candidate_is_explicitly_unscorable(self):
        malformed = {"bad": True}
        result = self.score(malformed)
        self.assertEqual(result["candidate_status"], "unscorable")
        self.assertEqual(result["unscorable_value_slots"], 21)
        self.assertTrue(all(item["reason_kind"] == "unscorable" for item in result["value_results"]))

        duplicate = copy.deepcopy(self.base_candidate)
        duplicate["courses"].append(copy.deepcopy(duplicate["courses"][0]))
        result = self.score(duplicate)
        self.assertEqual(result["candidate_status"], "unscorable")
        self.assertIn("duplicate", result["candidate_error"])

        missing_file = scoring.score_candidate(
            None, self.reference, "S00-base", candidate_error="candidate file is missing"
        )
        self.assertEqual(missing_file["candidate_status"], "unscorable")
        self.assertEqual(missing_file["unscorable_value_slots"], 21)

    def test_missing_record_scores_missing_slots_without_changing_denominator(self):
        incomplete = copy.deepcopy(self.base_candidate)
        incomplete["courses"] = [item for item in incomplete["courses"] if item["course_id"] != "automation-pls"]
        result = self.score(incomplete)
        self.assertEqual(result["candidate_status"], "scoreable")
        self.assertEqual(result["value_slot_denominator"], 21)
        self.assertEqual(result["value_slot_counts"]["missing"], 7)

    def test_populated_claim_rate_and_state_rates_keep_fixed_denominators(self):
        result = self.score()
        self.assertEqual(result["value_slot_rates"]["correct"], 1.0)
        self.assertEqual(result["incorrect_populated_claim_rate"], 0.0)
        empty = scoring.aggregate_scores([])
        self.assertIsNone(empty["value_slot_rates"]["correct"])
        self.assertIsNone(empty["required_text_coverage_rate"])
        self.assertIsNone(empty["incorrect_populated_claim_rate"])

    def test_provenance_groups_cannot_be_combined(self):
        positive = self.score()
        mutant = self.score(provenance="mutated_candidate")
        with self.assertRaises(scoring.ScoringError):
            scoring.aggregate_scores([positive, mutant])

    def test_reference_must_be_reviewed_and_all_review_hashes_must_match(self):
        changed_hash = copy.deepcopy(self.reference)
        changed_hash["review"]["source_review"]["reference_content_sha256"] = "0" * 64
        with self.assertRaises(scoring.ScoringError):
            scoring.score_candidate(self.base_candidate, changed_hash, "S00-base")

        prepared = copy.deepcopy(self.reference)
        prepared["review"]["status"] = "prepared"
        with self.assertRaises(scoring.ScoringError):
            scoring.score_candidate(self.base_candidate, prepared, "S00-base")

        changed_case = copy.deepcopy(self.reference)
        changed_case["review"]["source_review"]["case_input_sha256"]["S00-base"] = "0" * 64
        with self.assertRaises(scoring.ScoringError):
            scoring.score_candidate(self.base_candidate, changed_case, "S00-base")

        malformed_review = copy.deepcopy(self.reference)
        malformed_review["review"] = None
        with self.assertRaises(scoring.ScoringError):
            scoring.score_candidate(self.base_candidate, malformed_review, "S00-base")

    def test_rejected_source_cases_cannot_be_scored(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.score_candidate(self.base_candidate, self.reference, "S07-unapproved-course")

    def test_replay_scoring_refuses_current_model_or_unknown_provenance(self):
        for provenance in ("current_model", "unknown", None):
            with self.subTest(provenance=provenance), self.assertRaises(scoring.ScoringError):
                self.score(provenance=provenance)

    def test_boolean_schema_version_is_not_an_integer_schema_version(self):
        malformed = copy.deepcopy(self.base_candidate)
        malformed["schema_version"] = True
        result = self.score(malformed)
        self.assertEqual(result["candidate_status"], "unscorable")
        self.assertEqual(result["unscorable_value_slots"], 21)


class CourseEvaluationReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "out").mkdir(exist_ok=True)

    def test_full_replay_exercises_cases_mutations_provenance_and_output_isolation(self):
        (ROOT / "out").mkdir(exist_ok=True)
        protected = (corpus.BASE_PATH, corpus.REFERENCE_PATH, *evaluator.TRAINING_PATHS)
        before = {path: path.read_bytes() if path.is_file() else None for path in protected}
        with tempfile.TemporaryDirectory(prefix="task-013-replay-", dir=ROOT / "out") as temp:
            with patch.object(evaluator, "RUNS_ROOT", Path(temp)):
                run_id, run_dir, summary = evaluator.run_replay()
            self.assertTrue(run_id.startswith("run-"))
            self.assertTrue(summary["all_expected_component_controls_met"])
            self.assertTrue(summary["integrity_check_passed"])
            source_results = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
            mutation_results = json.loads((run_dir / "mutation-results.json").read_text(encoding="utf-8"))
            self.assertEqual(len(source_results), 9)
            self.assertEqual(len(mutation_results), 9)
            for item in source_results:
                if item["case_id"] in {"S07-unapproved-course", "S08-unapproved-url"}:
                    self.assertFalse(item["actual_preflight"])
                    self.assertIsNone(item["checker"])
                    self.assertIsNone(item["renderer"])
                else:
                    self.assertEqual(item["checker"]["status"], "pass")
                    self.assertEqual(item["renderer"]["status"], "pass")
            for item in mutation_results:
                self.assertTrue(item["checker_expectation_met"], item["mutation_id"])
                provenance = json.loads((ROOT / item["provenance_path"]).read_text(encoding="utf-8"))
                self.assertEqual(provenance["provenance_class"], "mutated_candidate")
                self.assertEqual(provenance["source_case_id"], item["source_case_id"])
                self.assertEqual(provenance["mutation_id"], item["mutation_id"])
                self.assertEqual(provenance["parent_candidate_sha256"], item["parent_candidate_sha256"])
            by_mutation = {item["mutation_id"]: item for item in mutation_results}
            self.assertEqual(by_mutation["C04-zero-as-unknown"]["checker"]["status"], "pass")
            c04_score = json.loads((ROOT / by_mutation["C04-zero-as-unknown"]["score_path"]).read_text(encoding="utf-8"))
            c04_fee = next(item for item in c04_score["value_results"] if item["fact_id"] == "intro-study-fee")
            self.assertEqual(c04_fee["state"], "missing")
            self.assertEqual(by_mutation["C05-omit-admissions-alternative"]["checker"]["status"], "pass")
            c05_score = json.loads((ROOT / by_mutation["C05-omit-admissions-alternative"]["score_path"]).read_text(encoding="utf-8"))
            self.assertLess(c05_score["prerequisite_atoms_covered"], 11)
            self.assertIn("not model accuracy", (run_dir / "results.md").read_text(encoding="utf-8"))
            self.assertTrue((run_dir / "integrity.json").is_file())
            self.assertTrue((run_dir / "run-manifest.json").is_file())
        after = {path: path.read_bytes() if path.is_file() else None for path in protected}
        self.assertEqual(before, after)

    def test_actual_mode_fails_before_subprocess_dispatch_or_output_creation(self):
        with tempfile.TemporaryDirectory(prefix="task-013-actual-", dir=ROOT / "out") as temp:
            runs_root = Path(temp) / "runs"
            with patch.object(evaluator, "RUNS_ROOT", runs_root), \
                 patch.object(evaluator.subprocess, "run", side_effect=AssertionError("subprocess dispatched")) as run, \
                 patch.object(evaluator.subprocess, "Popen", side_effect=AssertionError("subprocess dispatched")) as popen:
                self.assertEqual(evaluator.main(["--actual"]), 2)
                run.assert_not_called()
                popen.assert_not_called()
            self.assertFalse(runs_root.exists())

    def test_replay_refuses_to_reuse_an_existing_run_directory(self):
        with tempfile.TemporaryDirectory(prefix="task-013-unique-", dir=ROOT / "out") as temp:
            root = Path(temp)
            fixed_time = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
            stamp = fixed_time.strftime("%Y%m%dT%H%M%S.%fZ")
            existing = root / f"run-{stamp}-existing"
            existing.mkdir()
            sentinel = existing / "evidence.txt"
            sentinel.write_text("preserve this evidence", encoding="utf-8")
            with patch.object(evaluator, "RUNS_ROOT", root), \
                 patch.object(evaluator.secrets, "token_hex", return_value="existing"), \
                 patch.object(evaluator, "datetime") as clock:
                clock.now.return_value = fixed_time
                with self.assertRaises(RuntimeError):
                    evaluator._unique_run_directory()
            self.assertEqual(sentinel.read_text(), "preserve this evidence")
            self.assertEqual(list(root.iterdir()), [existing])

    def test_summary_cannot_pass_without_the_fixed_case_set(self):
        summary = evaluator._summarise_results([], [], [], [])
        self.assertFalse(summary["all_expected_component_controls_met"])

    def test_replay_fails_when_scorer_misses_deliberate_mutations(self):
        original_score = scoring.score_candidate

        def miss_faults(candidate, reference, case_id, **kwargs):
            if kwargs.get("provenance") == "mutated_candidate":
                _reference, generated, _base = scoring.load_reviewed_reference()
                source = json.loads(generated[case_id]["bytes"])
                candidate = evaluator.build_reference_candidate(source, reference, case_id)
            return original_score(candidate, reference, case_id, **kwargs)

        with tempfile.TemporaryDirectory(dir=ROOT / "out") as temp, \
             patch.object(evaluator, "RUNS_ROOT", Path(temp)), \
             patch.object(scoring, "score_candidate", side_effect=miss_faults):
            _run_id, run_dir, summary = evaluator.run_replay()
            self.assertFalse(summary["all_expected_component_controls_met"])
            mutations = json.loads((run_dir / "mutation-results.json").read_text())
            self.assertTrue(all(item["checker_expectation_met"] for item in mutations))
            self.assertTrue(all(not item["scoring_expectation_met"] for item in mutations))

    def test_replay_fails_when_scorer_misclassifies_a_positive_control(self):
        original_score = scoring.score_candidate

        def false_failure(candidate, reference, case_id, **kwargs):
            result = original_score(candidate, reference, case_id, **kwargs)
            if kwargs.get("provenance") == "synthetic_reference" and case_id == "S00-base":
                result["value_results"][0]["state"] = "incorrect"
                result["value_slot_counts"] = {"correct": 20, "missing": 0, "incorrect": 1}
                result["value_slot_rates"] = {"correct": 20 / 21, "missing": 0, "incorrect": 1 / 21}
            return result

        with tempfile.TemporaryDirectory(dir=ROOT / "out") as temp, \
             patch.object(evaluator, "RUNS_ROOT", Path(temp)), \
             patch.object(scoring, "score_candidate", side_effect=false_failure):
            _run_id, _run_dir, summary = evaluator.run_replay()
            self.assertFalse(summary["all_expected_component_controls_met"])

    def test_run_directory_refuses_external_or_training_symlinks(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "out") as temp:
            parent = Path(temp)
            project = parent / "project"
            training = project / "out" / "training"
            training.mkdir(parents=True)
            outside = parent / "outside"
            outside.mkdir()
            for name, destination in (("training-link", training), ("outside-link", outside)):
                link = project / "out" / name
                link.symlink_to(destination, target_is_directory=True)
                with self.subTest(name=name), patch.object(evaluator, "ROOT", project), \
                     patch.object(evaluator, "RUNS_ROOT", link), self.assertRaises(ValueError):
                    evaluator._unique_run_directory()
                self.assertEqual(list(destination.iterdir()), [])

    def test_failed_checker_dispatch_preserves_failure_evidence_and_integrity(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "out") as temp:
            run_root = Path(temp)
            with patch.object(evaluator, "RUNS_ROOT", run_root), \
                 patch.object(evaluator, "_run_checker", side_effect=OSError("injected checker dispatch failure")):
                with self.assertRaises(OSError):
                    evaluator.run_replay()
            run_dir, = run_root.iterdir()
            manifest = json.loads((run_dir / "run-manifest.json").read_text())
            self.assertEqual(manifest["run_status"], "error")
            self.assertIn("injected checker dispatch failure", manifest["failure"]["message"])
            self.assertTrue(json.loads((run_dir / "integrity.json").read_text())["unchanged"])
            result = json.loads((run_dir / "results.json").read_text())
            self.assertFalse(result["all_expected_component_controls_met"])
            self.assertEqual(result["planned_source_case_count"], 9)
            self.assertEqual(result["planned_candidate_mutation_count"], 9)

    def test_component_timeout_is_recorded_without_an_invented_exit_code(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "out") as temp:
            parent = Path(temp)
            feedback = parent / "checker.json"
            with patch.object(evaluator.subprocess, "run", side_effect=subprocess.TimeoutExpired(["python"], 30, output=b"partial output")):
                result = evaluator._run_checker(parent / "source.json", parent / "candidate.json", feedback)
            self.assertEqual(result["status"], "error")
            self.assertIsNone(result["exit_code"])
            self.assertEqual(result["failure_kind"], "timeout")
            self.assertIn("partial output", result["stdout"])
            self.assertEqual(json.loads(feedback.read_text())["failure_kind"], "timeout")

    def test_control_reports_reject_inconsistent_score_totals(self):
        generated, _catalog, reference = corpus.check_corpus()
        source = json.loads(generated["S00-base"]["bytes"])
        candidate = evaluator.build_reference_candidate(source, reference, "S00-base")
        result = scoring.score_candidate(candidate, reference, "S00-base")
        result["value_slot_counts"]["correct"] = 20
        contract = evaluator.check_scoring_expectation(result, reference, "S00-base")
        self.assertFalse(contract["met"])

    def test_input_change_fails_with_a_retained_integrity_report(self):
        before = evaluator._protected_snapshot()
        after = copy.deepcopy(before)
        after["eval/check_courses.py"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(dir=ROOT / "out") as temp:
            root = Path(temp)
            with patch.object(evaluator, "RUNS_ROOT", root), \
                 patch.object(evaluator, "_protected_snapshot", side_effect=[before, after, after]):
                with self.assertRaises(RuntimeError):
                    evaluator.run_replay()
            run_dir, = root.iterdir()
            self.assertFalse(json.loads((run_dir / "integrity.json").read_text())["unchanged"])
            self.assertEqual(json.loads((run_dir / "run-manifest.json").read_text())["run_status"], "error")

    def test_unexpected_preflight_rejection_keeps_planned_denominators(self):
        generated, catalog, reference = corpus.check_corpus()
        source = json.loads(generated["S00-base"]["bytes"])
        original_preflight = evaluator.course_sources._valid_bundle

        def reject_base_only(value):
            return False if value == source else original_preflight(value)

        with tempfile.TemporaryDirectory(dir=ROOT / "out") as temp, \
             patch.object(evaluator, "RUNS_ROOT", Path(temp)), \
             patch.object(corpus, "check_corpus", return_value=(generated, catalog, reference)), \
             patch.object(evaluator.course_sources, "_valid_bundle", side_effect=reject_base_only):
            _run_id, run_dir, summary = evaluator.run_replay()
            self.assertFalse(summary["all_expected_component_controls_met"])
            source_summary = summary["provenance_aggregates"]["synthetic_reference"]
            mutant_summary = summary["provenance_aggregates"]["mutated_candidate"]
            self.assertEqual(source_summary["value_slot_denominator"], 147)
            self.assertEqual(source_summary["not_scored_value_slots"], 21)
            self.assertEqual(mutant_summary["value_slot_denominator"], 189)
            self.assertEqual(mutant_summary["not_scored_value_slots"], 168)
            self.assertEqual(summary["not_scored_candidate_count"], 9)
            self.assertLess(source_summary["value_slot_rates"]["correct"], 1)
            self.assertEqual(len(json.loads((run_dir / "source-case-results.json").read_text())), 9)
            self.assertEqual(len(json.loads((run_dir / "mutation-results.json").read_text())), 9)

    def test_mutation_dispatch_failure_retains_the_started_control_and_candidate(self):
        original_checker = evaluator._run_checker

        def fail_on_mutation(source, candidate, feedback):
            if "mutated_candidate" in candidate.parts:
                raise OSError("injected mutation checker failure")
            return original_checker(source, candidate, feedback)

        with tempfile.TemporaryDirectory(dir=ROOT / "out") as temp:
            root = Path(temp)
            with patch.object(evaluator, "RUNS_ROOT", root), \
                 patch.object(evaluator, "_run_checker", side_effect=fail_on_mutation):
                with self.assertRaises(OSError):
                    evaluator.run_replay()
            run_dir, = root.iterdir()
            summary = json.loads((run_dir / "results.json").read_text())
            self.assertEqual(summary["candidate_mutations_started"], 1)
            self.assertNotIn("C01-swapped-dates", summary["candidate_mutation_ids_not_started"])
            rows = json.loads((run_dir / "mutation-results.json").read_text())
            self.assertEqual(rows[0]["mutation_id"], "C01-swapped-dates")
            self.assertTrue((ROOT / rows[0]["candidate_path"]).is_file())
            self.assertIsNone(rows[0]["checker"])


if __name__ == "__main__":
    unittest.main()

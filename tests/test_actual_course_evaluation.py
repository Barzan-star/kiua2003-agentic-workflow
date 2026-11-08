"""Deterministic C2 actual-interface tests; all provider behavior is injected."""

from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from harness import course_evaluation_cases as corpus
from harness import course_evaluation_scoring as scoring
from harness import course_workflow
from harness import evaluate_courses as evaluator


ROOT = evaluator.ROOT
TEST_LIMITS = {
    "run_token_limit": 10_000,
    "max_output_tokens": 200,
    "max_model_calls": 21,
}
SECRET_MARKER = "sk-C2_INJECTED_TEST_SECRET"


class RawHTTPResponse:
    def __init__(self, payload, request_id):
        self.status_code = 200
        self.headers = {"content-type": "application/json", "x-request-id": request_id}
        self.content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.closed = False

    def close(self):
        self.closed = True


class RawSDKResponse:
    def __init__(self, payload, request_id):
        self.http_response = RawHTTPResponse(payload, request_id)


class InjectedSDK:
    """Raw SDK-shaped double with no network-capable methods."""

    max_retries = 0
    timeout = 90

    def __init__(self, outputs=None, *, count_error=None, create_error=None,
                 omit_usage=False, no_output=False):
        self.outputs = list(outputs or [])
        self.count_error = count_error
        self.create_error = create_error
        self.omit_usage = omit_usage
        self.no_output = no_output
        self.count_kwargs = []
        self.create_kwargs = []
        self.count_calls = 0
        self.create_calls = 0
        self.close_calls = 0
        self.responses = self
        self.input_tokens = self
        self.with_raw_response = self

    def count(self, **kwargs):
        self.count_calls += 1
        self.count_kwargs.append(copy.deepcopy(kwargs))
        if self.count_error is not None:
            raise self.count_error
        return RawSDKResponse({
            "object": "response.input_tokens",
            "input_tokens": 100,
        }, f"req_count_{self.count_calls}")

    def create(self, **kwargs):
        self.create_calls += 1
        self.create_kwargs.append(copy.deepcopy(kwargs))
        if self.create_error is not None:
            raise self.create_error
        response = {
            "object": "response",
            "id": f"resp_{self.create_calls}",
            "model": "gpt-6-luna",
            "status": "completed",
            "output": [] if self.no_output else [{
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{
                    "type": "output_text",
                    "text": self.outputs[min(self.create_calls - 1, len(self.outputs) - 1)],
                }],
            }],
        }
        if not self.omit_usage:
            response["usage"] = {
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 8},
            }
        return RawSDKResponse(response, f"req_create_{self.create_calls}")

    def close(self):
        self.close_calls += 1


@contextmanager
def network_blocked():
    """Make any accidental Python socket use fail during injected executions."""
    failure = AssertionError("real networking is forbidden in injected evaluation tests")
    with patch.object(socket, "create_connection", side_effect=failure), \
         patch.object(socket, "getaddrinfo", side_effect=failure), \
         patch.object(socket.socket, "connect", side_effect=failure), \
         patch.object(socket.socket, "connect_ex", side_effect=failure):
        yield


def fixed_candidate_texts():
    generated, catalog, reference = corpus.check_corpus()
    values = []
    for case in catalog["source_cases"]:
        if case["expected_preflight"] != "accept":
            continue
        source = json.loads(generated[case["case_id"]]["bytes"].decode("utf-8"))
        candidate = evaluator.build_reference_candidate(source, reference, case["case_id"])
        values.append(json.dumps(candidate, ensure_ascii=False))
    return generated, catalog, reference, values


class ActualScoringModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated, cls.catalog, cls.reference, cls.texts = fixed_candidate_texts()
        cls.candidate = evaluator.build_reference_candidate(
            json.loads(cls.generated["S00-base"]["bytes"].decode("utf-8")),
            cls.reference, "S00-base",
        )

    def test_replay_default_and_actual_current_model_are_distinct_modes(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.score_candidate(self.candidate, self.reference, "S00-base", provenance="current_model")
        actual = scoring.score_candidate(
            self.candidate, self.reference, "S00-base", provenance="current_model",
            evaluation_mode="actual",
        )
        self.assertEqual(actual["provenance_class"], "current_model")
        self.assertEqual(actual["value_slot_denominator"], 21)
        with self.assertRaises(scoring.ScoringError):
            scoring.score_candidate(
                self.candidate, self.reference, "S00-base", provenance="synthetic_reference",
                evaluation_mode="actual",
            )
        with self.assertRaises(scoring.ScoringError):
            scoring.score_candidate(
                self.candidate, self.reference, "S00-base", provenance="current_model",
                evaluation_mode="unknown",
            )

    def test_aggregates_reject_mixed_and_wrong_mode_provenance(self):
        replay = scoring.score_candidate(self.candidate, self.reference, "S00-base")
        actual = scoring.score_candidate(
            self.candidate, self.reference, "S00-base", provenance="current_model",
            evaluation_mode="actual",
        )
        with self.assertRaises(scoring.ScoringError):
            scoring.aggregate_scores([actual])
        with self.assertRaises(scoring.ScoringError):
            scoring.aggregate_scores([replay], evaluation_mode="actual")
        with self.assertRaises(scoring.ScoringError):
            scoring.aggregate_scores([actual, replay], evaluation_mode="actual")
        self.assertEqual(
            scoring.aggregate_scores([actual], evaluation_mode="actual")["candidate_count"], 1,
        )


class ActualCourseEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "out").mkdir(exist_ok=True)
        cls.generated, cls.catalog, cls.reference, cls.outputs = fixed_candidate_texts()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task-014-c2-", dir=ROOT / "out")
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **overrides):
        values = dict(TEST_LIMITS)
        values.update(overrides)
        return SimpleNamespace(**values)

    def run_injected(self, sdk, *, args=None):
        factory_calls = []

        def factory(*, timeout_seconds):
            factory_calls.append(timeout_seconds)
            return sdk

        with patch.object(evaluator, "RUNS_ROOT", self.runs), network_blocked():
            outcome = evaluator.run_actual(
                self.args() if args is None else args,
                client_factory=factory,
                execution_kind="injected_test",
            )
        return (*outcome, factory_calls)

    def test_all_nine_preflights_seven_generations_one_client_and_one_shared_ledger(self):
        sdk = InjectedSDK(self.outputs)
        observed_ledgers = []
        observed_clients = []
        original = course_workflow.run_course_workflow

        def observe(source, ledger, client, case_dir):
            observed_ledgers.append(ledger)
            observed_clients.append(client)
            return original(source, ledger, client, case_dir)

        protected_paths = (
            evaluator.BASE_PATH, evaluator.CATALOG_PATH, evaluator.REFERENCE_PATH,
            *evaluator.TRAINING_PATHS,
        )
        before = {path: path.read_bytes() if path.is_file() else None for path in protected_paths}
        with patch.object(course_workflow, "run_course_workflow", side_effect=observe), \
             patch.dict(os.environ, {"OPENAI_API_KEY": SECRET_MARKER}):
            run_id, run_dir, summary, exit_code, factory_calls = self.run_injected(sdk)

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["run_status"], "complete")
        self.assertEqual(factory_calls, [evaluator.ACTUAL_TIMEOUT_SECONDS])
        self.assertEqual(sdk.close_calls, 1)
        self.assertEqual((sdk.count_calls, sdk.create_calls), (7, 7))
        self.assertEqual(len(observed_ledgers), 7)
        self.assertTrue(all(ledger is observed_ledgers[0] for ledger in observed_ledgers))
        self.assertTrue(all(client is observed_clients[0] for client in observed_clients))
        self.assertTrue(all(client.native_client is sdk for client in observed_clients))
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 9)
        self.assertEqual(sum(row["observed_preflight"] == "approved" for row in rows), 7)
        self.assertEqual(sum(row["observed_preflight"] == "rejected" for row in rows), 2)
        self.assertEqual(sum(row["workflow_status"] == "preflight_rejected" for row in rows), 2)
        self.assertTrue(all(row["workflow_status"] == "accepted" for row in rows[:7]))
        ledger = json.loads((run_dir / "token-ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["model_calls"], 7)
        links = json.loads((run_dir / "ledger-linkage.json").read_text(encoding="utf-8"))
        self.assertEqual(len(links), 7)
        self.assertEqual([item["case_id"] for item in links], [row["case_id"] for row in rows[:7]])
        self.assertEqual(summary["fixed_set_coverage"]["value_slots"]["planned_denominator"], 147)
        self.assertEqual(summary["fixed_set_coverage"]["required_text_atoms"]["planned_denominator"], 119)
        self.assertEqual(summary["fixed_set_coverage"]["prerequisite_atoms"]["planned_denominator"], 77)
        self.assertEqual(summary["request_usage_counts"]["generation_dispatches"], 7)
        self.assertEqual(summary["request_usage_counts"]["confirmed_total_tokens"], 1050)
        self.assertTrue(summary["not_model_accuracy"])
        for kwargs in sdk.create_kwargs:
            payload = json.dumps(kwargs, ensure_ascii=False)
            self.assertNotIn("S00-base", payload)
            self.assertNotIn("robot-study-fee-unknown", payload)
            self.assertNotIn("evaluation_reference", payload)
            self.assertNotIn(SECRET_MARKER, payload)
        after = {path: path.read_bytes() if path.is_file() else None for path in protected_paths}
        self.assertEqual(before, after)
        self.assertIn("injected_test", (run_dir / "results.md").read_text(encoding="utf-8"))
        self.assertTrue((run_dir / "budget-before.json").is_file())
        self.assertTrue((run_dir / "budget-after.json").is_file())
        self.assertTrue((run_dir / "run-manifest.json").is_file())
        self.assertTrue(run_id.startswith("run-"))

    def test_checker_accepted_imperfect_candidate_is_scored_and_completed(self):
        generated, _catalog, reference, outputs = fixed_candidate_texts()
        base = json.loads(generated["S00-base"]["bytes"].decode("utf-8"))
        candidate = evaluator.build_reference_candidate(base, reference, "S00-base")
        catalog = self.catalog
        candidate = evaluator.apply_candidate_mutation(
            candidate, base, reference, catalog, "C05-omit-admissions-alternative",
        )
        robot = next(item for item in candidate["courses"] if item["course_id"] == "automation-robot-regulation")
        robot["missing_or_uncertain_fields"].append("delivery_format")
        intro = next(item for item in candidate["courses"] if item["course_id"] == "automation-introduction")
        intro["application_deadline"] = {"date": None, "evidence": []}
        if "application_deadline" not in intro["missing_or_uncertain_fields"]:
            intro["missing_or_uncertain_fields"].append("application_deadline")
        outputs[0] = json.dumps(candidate, ensure_ascii=False)
        sdk = InjectedSDK(outputs)
        run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["run_status"], "complete")
        first = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(first["workflow_status"], "accepted")
        self.assertEqual(first["candidate_attempt"], 1)
        self.assertEqual(first["candidate_status"], "scoreable")
        score = json.loads((ROOT / first["score_path"]).read_text(encoding="utf-8"))
        saved = json.loads((ROOT / first["candidate_path"]).read_text(encoding="utf-8"))
        delivery = next(row for row in score["value_results"] if row["fact_id"] == "robot-delivery-format")
        self.assertEqual(delivery["state"], "incorrect")
        missing_deadline = next(row for row in score["value_results"] if row["fact_id"] == "intro-deadline")
        self.assertEqual(missing_deadline["state"], "missing")
        self.assertLess(score["prerequisite_atoms_covered"], 11)
        self.assertEqual(sdk.create_calls, 7)
        self.assertTrue((run_dir / "run-manifest.json").is_file())
        manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["execution_kind"], "injected_test")
        self.assertTrue(manifest["not_model_accuracy"])

    def test_three_completed_checker_rejections_are_scored_then_next_cases_continue(self):
        invalid = json.loads(self.outputs[0])
        invalid["courses"][0]["study_fee_nok"]["amount"] = 777
        outputs = [json.dumps(invalid, ensure_ascii=False)] * 3 + self.outputs[1:]
        sdk = InjectedSDK(outputs)
        _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(rows[0]["workflow_status"], "candidate_rejected")
        self.assertEqual(rows[0]["candidate_attempt"], 3)
        self.assertEqual(rows[0]["candidate_status"], "scoreable")
        self.assertEqual(sdk.create_calls, 9)
        self.assertEqual(summary["fixed_set_coverage"]["actually_scored_case_count"], 7)

    def test_retries_exhaust_shared_call_allowance_before_next_case_dispatch(self):
        invalid = json.loads(self.outputs[0])
        invalid["courses"][0]["study_fee_nok"]["amount"] = 777
        sdk = InjectedSDK([json.dumps(invalid, ensure_ascii=False)] * 3)
        limits = self.args(run_token_limit=10_000, max_output_tokens=200, max_model_calls=3)
        _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk, args=limits)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(rows[0]["workflow_status"], "candidate_rejected")
        self.assertEqual(rows[1]["workflow_status"], "not_started")
        self.assertEqual(rows[1]["stop_reason"], "budget_exhausted")
        self.assertEqual(sdk.create_calls, 3)
        self.assertEqual(sdk.count_calls, 3)
        self.assertEqual(summary["request_usage_counts"]["generation_dispatches"], 3)
        self.assertFalse(summary["evaluation_complete"])

    def test_token_exhaustion_after_completed_retries_stops_all_later_generation(self):
        invalid = json.loads(self.outputs[0])
        invalid["courses"][0]["study_fee_nok"]["amount"] = 777
        sdk = InjectedSDK([json.dumps(invalid, ensure_ascii=False)] * 3)
        limits = self.args(run_token_limit=600, max_output_tokens=200, max_model_calls=21)
        _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk, args=limits)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(rows[0]["workflow_status"], "candidate_rejected")
        self.assertEqual(sdk.create_calls, 3)
        self.assertEqual(summary["request_usage_counts"]["confirmed_total_tokens"], 450)
        self.assertFalse(summary["evaluation_complete"])

    def test_count_failure_stops_batch_and_secret_exception_is_not_recorded(self):
        sdk = InjectedSDK(self.outputs, count_error=RuntimeError(SECRET_MARKER))
        _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(sdk.count_calls, 1)
        self.assertEqual(sdk.create_calls, 0)
        self.assertEqual(rows[0]["workflow_status"], "provider_abort")
        self.assertTrue(all(row["workflow_status"] == "not_started" for row in rows[1:7]))
        self.assertTrue(json.loads((run_dir / "token-ledger.json").read_text())["blocked"])
        self.assertEqual(summary["request_usage_counts"]["input_token_count_failures"], 1)
        for path in run_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET_MARKER, path.read_bytes().decode("utf-8", errors="ignore"))

    def test_unknown_usage_retains_reservation_and_scores_unusable_dispatched_output(self):
        sdk = InjectedSDK(self.outputs, omit_usage=True)
        _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(sdk.create_calls, 1)
        self.assertEqual(rows[0]["workflow_status"], "provider_abort")
        self.assertTrue(rows[0]["generation_dispatched"])
        self.assertEqual(rows[0]["candidate_status"], "unscorable")
        self.assertEqual(summary["fixed_set_coverage"]["value_slots"]["unscorable_denominator"], 21)
        ledger = json.loads((run_dir / "token-ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["reservations"][0]["status"], "uncertain")
        self.assertEqual(ledger["confirmed_tokens"], 0)

    def test_missing_output_is_unscorable_and_incomplete(self):
        sdk = InjectedSDK(self.outputs, no_output=True)
        _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(rows[0]["candidate_status"], "unscorable")
        self.assertEqual(summary["fixed_set_coverage"]["value_slots"]["unscorable_denominator"], 21)
        self.assertEqual(sdk.create_calls, 1)

    def test_evidence_write_failure_blocks_shared_ledger_and_later_cases(self):
        sdk = InjectedSDK(self.outputs)
        original_write = course_workflow._write_json

        def fail_attempt_record(path, value):
            if Path(path).name == "attempt-1.json":
                raise OSError(SECRET_MARKER)
            return original_write(path, value)

        with patch.object(course_workflow, "_write_json", side_effect=fail_attempt_record):
            _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(sdk.create_calls, 1)
        self.assertEqual(rows[0]["workflow_status"], "infrastructure_abort")
        self.assertEqual(rows[0]["candidate_status"], "unscorable")
        self.assertTrue(json.loads((run_dir / "token-ledger.json").read_text())["blocked"])
        self.assertTrue(all(row["workflow_status"] == "not_started" for row in rows[1:7]))
        self.assertFalse(summary["evaluation_complete"])
        for path in run_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET_MARKER, path.read_bytes().decode("utf-8", errors="ignore"))

    def test_checker_interruption_blocks_batch_and_returns_130(self):
        sdk = InjectedSDK(self.outputs)
        with patch.object(course_workflow.subprocess, "run", side_effect=KeyboardInterrupt):
            _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 130)
        self.assertEqual(rows[0]["workflow_failure_code"], "interrupted")
        self.assertEqual(sdk.create_calls, 1)
        self.assertEqual(sdk.close_calls, 1)
        self.assertTrue(json.loads((run_dir / "token-ledger.json").read_text())["blocked"])
        self.assertFalse(summary["evaluation_complete"])
        self.assertTrue(all(row["workflow_status"] == "not_started" for row in rows[1:7]))

    def test_malformed_json_is_unscorable_and_stops_without_invalid_repair_retry(self):
        sdk = InjectedSDK(["not-json"] * 3 + self.outputs[1:])
        _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(rows[0]["workflow_status"], "provider_abort")
        self.assertEqual(rows[0]["candidate_status"], "unscorable")
        self.assertEqual(summary["fixed_set_coverage"]["value_slots"]["unscorable_denominator"], 21)
        self.assertEqual(summary["fixed_set_coverage"]["value_slots"]["not_scored_denominator"], 126)
        self.assertEqual(sdk.create_calls, 1)

    def test_child_environments_remove_runtime_key_and_no_reference_or_score_reaches_model(self):
        sdk = InjectedSDK(self.outputs)
        child_envs = []
        real_run = subprocess.run

        def capture_env(command, **kwargs):
            child_envs.append(kwargs.get("env", {}).copy())
            return real_run(command, **kwargs)

        with patch.dict(os.environ, {"OPENAI_API_KEY": SECRET_MARKER}), \
             patch.object(course_workflow.subprocess, "run", side_effect=capture_env):
            _run_id, run_dir, _summary, exit_code, _factory_calls = self.run_injected(sdk)
        self.assertEqual(exit_code, 0)
        self.assertTrue(child_envs)
        self.assertTrue(all("OPENAI_API_KEY" not in env for env in child_envs))
        for kwargs in sdk.create_kwargs:
            payload = json.dumps(kwargs, ensure_ascii=False)
            self.assertNotIn("fact_id", payload)
            self.assertNotIn("case_id", payload)
            self.assertNotIn("score_path", payload)
            self.assertNotIn("expected_workflow_outcome", payload)
        manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sdk_requirement"], "openai==3.46.0")
        self.assertIn("requirements-model.txt", manifest["input_hashes"]["implementation_sha256"])

    def test_preflight_mismatch_stops_before_client_creation(self):
        client_calls = []
        original = course_workflow._validated_source_view

        def changed_contract(bundle):
            if len(bundle.get("courses", [])) != len(course_workflow.course_sources.COURSES):
                return {"unexpected": True}
            return original(bundle)

        def factory(**_kwargs):
            client_calls.append(True)
            return InjectedSDK(self.outputs)

        with patch.object(evaluator, "RUNS_ROOT", self.runs), \
             patch.object(course_workflow, "_validated_source_view", side_effect=changed_contract), \
             network_blocked():
            run_id, run_dir, summary, exit_code = evaluator.run_actual(
                self.args(), client_factory=factory, execution_kind="injected_test",
            )
        self.assertEqual(client_calls, [])
        self.assertEqual(exit_code, 1)
        self.assertEqual(summary["failure"]["failure_code"], "preflight_integrity_failure")
        self.assertEqual(summary["failure"]["error_category"], "integrity")
        self.assertFalse((run_dir / "token-ledger.json").exists())
        preflight = json.loads((run_dir / "preflight-results.json").read_text(encoding="utf-8"))
        self.assertFalse(all(row["preflight_matches_expectation"] for row in preflight))
        self.assertTrue(run_id.startswith("run-"))

    def test_reference_integrity_failure_precedes_client_and_ledger(self):
        client_calls = []

        def factory(**_kwargs):
            client_calls.append(True)
            return InjectedSDK(self.outputs)

        with patch.object(evaluator, "RUNS_ROOT", self.runs), \
             patch.object(scoring, "validate_reviewed_reference", side_effect=ValueError(SECRET_MARKER)), \
             network_blocked():
            _run_id, run_dir, summary, exit_code = evaluator.run_actual(
                self.args(), client_factory=factory, execution_kind="injected_test",
            )
        self.assertEqual(client_calls, [])
        self.assertEqual(exit_code, 1)
        self.assertEqual(summary["request_usage_counts"]["generation_dispatches"], 0)
        self.assertFalse((run_dir / "token-ledger.json").exists())
        for path in run_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET_MARKER, path.read_bytes().decode("utf-8", errors="ignore"))

    def test_runner_reports_prior_completed_candidate_if_later_attempt_aborts(self):
        outputs = self.outputs.copy()
        invalid = json.loads(outputs[0])
        invalid["courses"][0]["study_fee_nok"]["amount"] = 777
        outputs[0] = json.dumps(invalid, ensure_ascii=False)
        sdk = InjectedSDK(outputs, create_error=None)
        original_create = sdk.create

        def fail_second(**kwargs):
            if sdk.create_calls == 0:
                return original_create(**kwargs)
            sdk.create_calls += 1
            sdk.create_kwargs.append(copy.deepcopy(kwargs))
            raise RuntimeError(SECRET_MARKER)

        sdk.create = fail_second
        # First candidate is rejected; the next provider operation aborts.
        _run_id, run_dir, summary, exit_code, _factory_calls = self.run_injected(sdk)
        rows = json.loads((run_dir / "source-case-results.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertEqual(rows[0]["workflow_status"], "provider_abort")
        self.assertEqual(rows[0]["candidate_attempt"], 1, rows[0])
        self.assertTrue(rows[0]["candidate_is_prior_to_terminal_attempt"])
        self.assertEqual(rows[0]["candidate_status"], "scoreable")
        self.assertTrue(summary["fixed_set_coverage"]["value_slots"]["actually_scored_denominator"] >= 21)
        for path in run_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET_MARKER, path.read_bytes().decode("utf-8", errors="ignore"))


    def test_counted_but_unaffordable_request_is_reported_without_generation(self):
        sdk = InjectedSDK(self.outputs)
        limits = self.args(run_token_limit=250, max_output_tokens=200)
        _run_id, _run_dir, summary, exit_code, _factory = self.run_injected(sdk, args=limits)
        self.assertEqual(exit_code, 1)
        self.assertEqual((sdk.count_calls, sdk.create_calls), (1, 0))
        self.assertEqual(summary["request_usage_counts"]["input_token_count_responses"], 1)
        self.assertEqual(summary["request_usage_counts"]["input_token_count_requests"], 1)

    def _assert_case_artifact_fault_stops_dispatch(self, mutate):
        sdk = InjectedSDK(self.outputs)
        original = course_workflow.run_course_workflow
        observed_ledgers = []

        def change_after_controller(source, ledger, client, case_dir):
            observed_ledgers.append(ledger)
            result = original(source, ledger, client, case_dir)
            if Path(case_dir).name == "S00-base":
                mutate(Path(case_dir))
            return result

        with patch.object(course_workflow, "run_course_workflow", side_effect=change_after_controller):
            _run_id, run_dir, summary, exit_code, _factory = self.run_injected(sdk)
        self.assertNotEqual(exit_code, 0)
        self.assertFalse(summary["evaluation_complete"])
        self.assertEqual(sdk.create_calls, 1)
        self.assertTrue(observed_ledgers[0].state["blocked"])
        self.assertIsNotNone(summary["failure"])
        return run_dir, summary

    def test_missing_completed_candidate_is_an_integrity_abort(self):
        self._assert_case_artifact_fault_stops_dispatch(lambda d: (d / "candidate-1.json").unlink())

    def test_altered_completed_candidate_is_an_integrity_abort(self):
        self._assert_case_artifact_fault_stops_dispatch(
            lambda d: (d / "candidate-1.json").write_text("{}", encoding="utf-8"))

    def test_missing_checker_receipt_is_an_integrity_abort(self):
        self._assert_case_artifact_fault_stops_dispatch(lambda d: (d / "candidate-check-1.json").unlink())

    def test_missing_workflow_result_receipt_is_an_integrity_abort(self):
        self._assert_case_artifact_fault_stops_dispatch(lambda d: (d / "result.json").unlink())

    def test_altered_rendered_output_is_an_integrity_abort(self):
        self._assert_case_artifact_fault_stops_dispatch(
            lambda d: (d / "comparison.md").write_text("altered output", encoding="utf-8"))

    def test_report_failure_preserves_the_primary_provider_failure(self):
        sdk = InjectedSDK(self.outputs, count_error=RuntimeError(SECRET_MARKER))
        original = evaluator._write_json

        def fail_manifest(path, value):
            if Path(path).name == "run-manifest.json":
                raise OSError(SECRET_MARKER)
            return original(path, value)

        with patch.object(evaluator, "_write_json", side_effect=fail_manifest):
            _run_id, run_dir, summary, exit_code, _factory = self.run_injected(sdk)
        self.assertEqual(exit_code, 1)
        self.assertEqual(summary["failure"]["failure_code"], "provider_or_protocol_failure")
        self.assertIn("reporting_failure", {item["failure_code"] for item in summary["secondary_failures"]})
        self.assertNotIn(SECRET_MARKER, (run_dir / "failure.json").read_text())

    def test_broken_summary_component_still_retains_a_safe_failure_receipt(self):
        sdk = InjectedSDK(self.outputs)
        with patch.object(evaluator, "_actual_summary", side_effect=RuntimeError(SECRET_MARKER)):
            _run_id, run_dir, summary, exit_code, _factory = self.run_injected(sdk)
        self.assertEqual(exit_code, 1)
        self.assertFalse(summary["evaluation_complete"])
        self.assertTrue((run_dir / "failure.json").is_file())
        self.assertTrue(json.loads((run_dir / "token-ledger.json").read_text())["blocked"])
        self.assertNotIn(SECRET_MARKER, (run_dir / "failure.json").read_text())

    def test_markdown_reports_factual_quality_not_only_scoring_coverage(self):
        candidate = json.loads(self.outputs[0])
        robot = next(c for c in candidate["courses"] if c["course_id"] == "automation-robot-regulation")
        robot["missing_or_uncertain_fields"].append("delivery_format")
        outputs = [json.dumps(candidate, ensure_ascii=False), *self.outputs[1:]]
        _run_id, run_dir, summary, exit_code, _factory = self.run_injected(InjectedSDK(outputs))
        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["scored_provenance_aggregate"]["value_slot_counts"]["incorrect"], 1)
        markdown = (run_dir / "results.md").read_text()
        self.assertIn("146", markdown)
        self.assertIn("Incorrect", markdown)
        self.assertIn("Prerequisite atoms covered", markdown)


    def test_request_audit_failure_before_count_makes_no_endpoint_call(self):
        sdk = InjectedSDK(self.outputs)
        original = evaluator._write_json

        def fail_before_count(path, value):
            if Path(path).name == "request-audit.json" and value.get("events"):
                raise OSError(SECRET_MARKER)
            return original(path, value)

        with patch.object(evaluator, "_write_json", side_effect=fail_before_count):
            _run_id, run_dir, summary, exit_code, _factory = self.run_injected(sdk)
        self.assertEqual(exit_code, 1)
        self.assertEqual((sdk.count_calls, sdk.create_calls), (0, 0))
        self.assertEqual(summary["request_usage_counts"]["input_token_count_requests"], 0)
        self.assertTrue(json.loads((run_dir / "token-ledger.json").read_text())["blocked"])
        self.assertNotIn(SECRET_MARKER, (run_dir / "failure.json").read_text())

    def test_request_audit_failure_before_create_retains_conservative_reservation(self):
        sdk = InjectedSDK(self.outputs)
        original = evaluator._write_json

        def fail_before_create(path, value):
            events = value.get("events", []) if isinstance(value, dict) else []
            if Path(path).name == "request-audit.json" and any(
                    item["operation"] == "responses.create" for item in events):
                raise OSError(SECRET_MARKER)
            return original(path, value)

        with patch.object(evaluator, "_write_json", side_effect=fail_before_create):
            _run_id, run_dir, summary, exit_code, _factory = self.run_injected(sdk)
        self.assertEqual(exit_code, 1)
        self.assertEqual((sdk.count_calls, sdk.create_calls), (1, 0))
        self.assertEqual(summary["request_usage_counts"]["generation_dispatches"], 0)
        self.assertEqual(summary["request_usage_counts"]["generation_model_call_slots_used"], 1)
        self.assertEqual(summary["request_usage_counts"]["pending_reserved_tokens"], 300)
        self.assertTrue(json.loads((run_dir / "token-ledger.json").read_text())["blocked"])

    def test_failed_manifest_cannot_publish_a_completed_results_receipt(self):
        sdk = InjectedSDK(self.outputs)
        original = evaluator._write_json
        manifest_failed = []
        completed_writes = []

        def fail_manifest_and_failure_summary(path, value):
            if Path(path).name == "run-manifest.json":
                manifest_failed.append(True)
                raise OSError(SECRET_MARKER)
            if Path(path).name == "results.json":
                if value.get("evaluation_complete"):
                    completed_writes.append(True)
                if manifest_failed:
                    raise OSError(SECRET_MARKER)
            return original(path, value)

        with patch.object(evaluator, "_write_json", side_effect=fail_manifest_and_failure_summary):
            _run_id, run_dir, summary, exit_code, _factory = self.run_injected(sdk)
        self.assertEqual(exit_code, 1)
        self.assertFalse(summary["evaluation_complete"])
        self.assertEqual(completed_writes, [])
        if (run_dir / "results.json").exists():
            self.assertFalse(json.loads((run_dir / "results.json").read_text())["evaluation_complete"])
        self.assertTrue((run_dir / "failure.json").is_file())

    def test_client_close_failure_does_not_replace_primary_provider_failure(self):
        sdk = InjectedSDK(self.outputs, count_error=RuntimeError(SECRET_MARKER))
        with patch.object(sdk, "close", side_effect=RuntimeError(SECRET_MARKER)):
            _run_id, _run_dir, summary, exit_code, _factory = self.run_injected(sdk)
        self.assertEqual(exit_code, 1)
        self.assertEqual(summary["failure"]["failure_code"], "provider_or_protocol_failure")
        self.assertIn("client_close_failure", {item["failure_code"] for item in summary["secondary_failures"]})


class ActualConfigurationGuardTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "out").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="task-014-c2-guards-", dir=ROOT / "out")
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_missing_approval_or_limits_and_replay_conflicts_have_no_side_effects(self):
        with patch.object(evaluator, "RUNS_ROOT", self.runs), \
             patch.object(evaluator, "_validate_live_runtime", side_effect=AssertionError("runtime checked too early")), \
             patch.object(evaluator.subprocess, "run", side_effect=AssertionError("subprocess dispatched")), \
             patch.object(evaluator.subprocess, "Popen", side_effect=AssertionError("subprocess dispatched")):
            self.assertEqual(evaluator.main(["--actual"]), 2)
            self.assertEqual(evaluator.main(["--actual", "--approve-model-calls"]), 2)
            self.assertEqual(evaluator.main(["--replay", "--approve-model-calls"]), 2)
            self.assertEqual(evaluator.main(["--max-model-calls", "1"]), 2)
        self.assertFalse(self.runs.exists())

    def test_default_replay_needs_no_runtime_key_and_rejects_all_model_options(self):
        run_dir = ROOT / "out" / "unused-replay-stub"
        summary = {"all_expected_component_controls_met": True, "integrity_check_passed": True}
        with patch.object(evaluator, "run_replay", return_value=("run-replay-stub", run_dir, summary)) as replay, \
             patch.object(evaluator, "RUNS_ROOT", self.runs), \
             patch.object(evaluator, "_validate_live_runtime", side_effect=AssertionError("runtime checked in replay")), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(evaluator.main([]), 0)
            replay.assert_called_once_with()
            self.assertEqual(evaluator.main(["--replay", "--run-token-limit", "100"]), 2)
            self.assertEqual(evaluator.main(["--replay", "--max-output-tokens", "100"]), 2)
            self.assertEqual(evaluator.main(["--replay", "--max-model-calls", "3"]), 2)
        self.assertFalse(self.runs.exists())

    def test_cli_rejects_missing_or_whitespace_runtime_key_before_output(self):
        command = [
            "--actual", "--approve-model-calls",
            "--run-token-limit", "1000", "--max-output-tokens", "200", "--max-model-calls", "3",
        ]
        for key in (None, "   ", f" {SECRET_MARKER}", f"{SECRET_MARKER} "):
            with self.subTest(key=key), patch.object(evaluator, "RUNS_ROOT", self.runs), \
                 patch.dict(os.environ, {} if key is None else {"OPENAI_API_KEY": key}, clear=key is None), \
                 patch.object(evaluator.importlib.metadata, "version", side_effect=AssertionError("SDK checked for invalid key")):
                self.assertEqual(evaluator.main(command), 2)
                self.assertFalse(self.runs.exists())

    def test_cli_rejects_invalid_or_nonpositive_limit_text_before_runtime_or_output(self):
        for option, invalid in (("--run-token-limit", "0"), ("--max-output-tokens", "-1"),
                                ("--max-model-calls", "1.5"), ("--run-token-limit", "true")):
            command = ["--actual", "--approve-model-calls"]
            for other, value in (("--run-token-limit", "100"),
                                 ("--max-output-tokens", "20"),
                                 ("--max-model-calls", "2")):
                if other != option:
                    command.extend([other, value])
            command.extend([option, invalid])
            with self.subTest(option=option, invalid=invalid), patch.object(evaluator, "RUNS_ROOT", self.runs), \
                 patch.dict(os.environ, {"OPENAI_API_KEY": SECRET_MARKER}), \
                 patch.object(evaluator, "_validate_live_runtime", side_effect=AssertionError("runtime checked before limits")):
                self.assertEqual(evaluator.main(command), 2)
                self.assertFalse(self.runs.exists())

    def test_programmatic_injection_rejects_boolean_zero_negative_and_missing_limits_early(self):
        for bad in (True, False, 0, -1, None, "1.0", " 1"):
            for field in TEST_LIMITS:
                values = dict(TEST_LIMITS)
                values[field] = bad
                with self.subTest(field=field, bad=bad), patch.object(evaluator, "RUNS_ROOT", self.runs), \
                     self.assertRaises(ValueError):
                    evaluator.run_actual(
                        SimpleNamespace(**values),
                        client_factory=lambda **_kwargs: self.fail("client constructed"),
                        execution_kind="injected_test",
                    )
                self.assertFalse(self.runs.exists())

    def test_programmatic_provider_path_requires_explicit_approval(self):
        with patch.object(evaluator, "RUNS_ROOT", self.runs), \
             patch.object(evaluator, "_validate_live_runtime", side_effect=AssertionError("credential read before approval")), \
             self.assertRaises(ValueError):
            evaluator.run_actual(SimpleNamespace(**TEST_LIMITS))
        self.assertFalse(self.runs.exists())

    def test_pinned_sdk_mismatch_is_rejected_before_output(self):
        command = [
            "--actual", "--approve-model-calls", "--run-token-limit", "1000",
            "--max-output-tokens", "200", "--max-model-calls", "3",
        ]
        with patch.object(evaluator, "RUNS_ROOT", self.runs), \
             patch.dict(os.environ, {"OPENAI_API_KEY": SECRET_MARKER}), \
             patch.object(evaluator.importlib.metadata, "version", return_value="3.45.0"):
            self.assertEqual(evaluator.main(command), 2)
        self.assertFalse(self.runs.exists())

    def test_actual_run_directory_rejects_training_and_external_symlinks(self):
        out = ROOT / "out"
        with tempfile.TemporaryDirectory(prefix="task-014-c2-outside-") as outside_temp:
            outside = Path(outside_temp)
            for link_name, target in (("training-link", ROOT / "out" / "training"),
                                      ("outside-link", outside)):
                link = self.root / link_name
                link.symlink_to(target, target_is_directory=True)
                with self.subTest(link=link_name), patch.object(evaluator, "RUNS_ROOT", link), \
                     self.assertRaises(ValueError):
                    evaluator._unique_run_directory()
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

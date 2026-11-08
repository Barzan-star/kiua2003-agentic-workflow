"""Deterministic shared-controller tests using the real ledger and adapter."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from harness import course_workflow
from harness.model_budget import TokenLedger
from harness.openai_course_client import CourseClientError
from test_course_records import SOURCE, make_candidate


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


class SDKDouble:
    """Injected synchronous SDK surface; no network-capable method exists."""

    max_retries = 0
    timeout = 12.5

    def __init__(self, outputs=None, *, create_error=None, omit_usage=False):
        self.outputs = list(outputs or [json.dumps(make_candidate(), ensure_ascii=False)])
        self.create_error = create_error
        self.omit_usage = omit_usage
        self.count_kwargs = []
        self.create_kwargs = []
        self.count_calls = 0
        self.create_calls = 0
        self.responses = self
        self.input_tokens = self
        self.with_raw_response = self

    def count(self, **kwargs):
        self.count_calls += 1
        self.count_kwargs.append(copy.deepcopy(kwargs))
        return RawSDKResponse(
            {"object": "response.input_tokens", "input_tokens": 100},
            f"req_count_{self.count_calls}",
        )

    def create(self, **kwargs):
        self.create_calls += 1
        self.create_kwargs.append(copy.deepcopy(kwargs))
        if self.create_error is not None:
            raise self.create_error
        text = self.outputs[min(self.create_calls - 1, len(self.outputs) - 1)]
        response = {
            "object": "response",
            "id": f"resp_{self.create_calls}",
            "model": "gpt-6-luna",
            "status": "completed",
            "output": [{
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }],
        }
        if not self.omit_usage:
            response["usage"] = {
                "input_tokens": 100,
                "output_tokens": 30,
                "total_tokens": 130,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 5},
            }
        return RawSDKResponse(response, f"req_create_{self.create_calls}")


class BudgetedCourseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir()
        self.ledger = self.new_ledger("ledger.json")

    def tearDown(self):
        self.temp.cleanup()

    def new_ledger(self, name, *, run=1000, output=100, calls=3):
        return TokenLedger(
            ledger_path=self.evidence_root / name,
            run_token_limit=run,
            max_output_tokens=output,
            max_model_calls=calls,
        )

    def run_case(self, sdk, name, source=None, ledger=None):
        return course_workflow.run_course_workflow(
            copy.deepcopy(SOURCE if source is None else source),
            self.ledger if ledger is None else ledger,
            sdk,
            self.evidence_root / name,
        )

    def test_success_checks_and_renders_source_linked_candidate(self):
        sdk = SDKDouble()
        result = self.run_case(sdk, "case-success")
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.attempts, 1)
        self.assertTrue(Path(result.rendered_json_path).is_relative_to(self.evidence_root))
        self.assertTrue(Path(result.rendered_markdown_path).is_relative_to(self.evidence_root))
        markdown = Path(result.rendered_markdown_path).read_text(encoding="utf-8")
        self.assertIn("https://www.fagskolen-innlandet.no/utdanninger/automasjon-for-elektrikere-pls", markdown)
        self.assertTrue(Path(result.checker_path).is_file())
        self.assertEqual(sdk.count_calls, 1)
        self.assertEqual(sdk.create_calls, 1)
        self.assertEqual(self.ledger.state["model_calls"], 1)

    def test_source_rejection_makes_zero_provider_requests_and_leaves_ledger_untouched(self):
        source = copy.deepcopy(SOURCE)
        source["courses"][0]["source_url"] = "https://unapproved.invalid/course"
        sdk = SDKDouble()
        result = self.run_case(sdk, "case-rejected-source", source=source)
        self.assertEqual(result.status, "source_rejected")
        self.assertEqual(result.attempts, 0)
        self.assertEqual(sdk.count_calls, 0)
        self.assertEqual(sdk.create_calls, 0)
        self.assertEqual(self.ledger.state["model_calls"], 0)
        self.assertEqual(self.ledger.state["reservations"], [])

    def test_retry_receives_exact_rejected_json_and_complete_checker_feedback(self):
        invalid = make_candidate()
        invalid["courses"][0]["study_fee_nok"]["amount"] = 777
        invalid_text = json.dumps(invalid, ensure_ascii=False)
        sdk = SDKDouble([invalid_text, json.dumps(make_candidate(), ensure_ascii=False)])
        result = self.run_case(sdk, "case-repair")
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sdk.create_calls, 2)
        retry_input = "\n".join(
            item["content"] for item in sdk.create_kwargs[1]["input"]
            if isinstance(item, dict) and isinstance(item.get("content"), str)
        )
        checker = json.loads((self.evidence_root / "case-repair/candidate-check-1.json").read_text(encoding="utf-8"))
        self.assertIn(invalid_text, retry_input)
        self.assertIn(checker["stdout"] + checker["stderr"], retry_input)
        self.assertEqual(checker["status"], 1)
        first_check = json.loads((self.evidence_root / "case-repair/attempt-1.json").read_text(encoding="utf-8"))
        self.assertEqual(first_check["checker_status"], 1)

    def test_three_rejections_leave_stable_last_candidate_and_do_not_render(self):
        invalid = make_candidate()
        invalid["courses"][0]["study_fee_nok"]["amount"] = 777
        invalid_text = json.dumps(invalid, ensure_ascii=False)
        sdk = SDKDouble([invalid_text] * 3)
        result = self.run_case(sdk, "case-three-rejections")
        self.assertEqual(result.status, "candidate_rejected")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(sdk.create_calls, 3)
        candidate_path = Path(result.candidate_path)
        self.assertEqual(candidate_path.read_text(encoding="utf-8"), invalid_text)
        self.assertFalse((self.evidence_root / "case-three-rejections/rendered-courses.json").exists())

    def test_retry_contract_refusal_is_recorded_and_stops(self):
        candidate = make_candidate()
        candidate["evaluation_reference"] = {"answer": "do not send"}
        sdk = SDKDouble([json.dumps(candidate, ensure_ascii=False)])
        result = self.run_case(sdk, "case-bad-repair-contract")
        self.assertEqual(result.status, "provider_abort")
        self.assertEqual(result.failure_code, "repair_protocol_error")
        self.assertEqual(sdk.create_calls, 1)
        self.assertEqual(sdk.count_calls, 1)

    def test_insufficient_token_allowance_counts_but_never_generates(self):
        ledger = self.new_ledger("small-ledger.json", run=199, output=100, calls=3)
        sdk = SDKDouble()
        result = self.run_case(sdk, "case-insufficient", ledger=ledger)
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(sdk.count_calls, 1)
        self.assertEqual(sdk.create_calls, 0)
        self.assertEqual(ledger.state["model_calls"], 0)

    def test_same_ledger_covers_retries_and_a_later_case_call_slot(self):
        ledger = self.new_ledger("shared-ledger.json", run=1000, output=100, calls=2)
        invalid = make_candidate()
        invalid["courses"][0]["study_fee_nok"]["amount"] = 777
        sdk = SDKDouble([json.dumps(invalid, ensure_ascii=False), json.dumps(make_candidate(), ensure_ascii=False)])
        first = self.run_case(sdk, "case-shared-first", ledger=ledger)
        second = self.run_case(sdk, "case-shared-second", ledger=ledger)
        self.assertEqual(first.status, "accepted")
        self.assertEqual(first.attempts, 2)
        self.assertEqual(second.status, "budget_exhausted")
        self.assertEqual(sdk.count_calls, 2, "the exhausted ledger must stop before another count request")
        self.assertEqual(sdk.create_calls, 2)
        self.assertEqual(ledger.state["model_calls"], 2)

    def test_unknown_usage_or_timeout_blocks_later_cases(self):
        for name, sdk in (
            ("unknown-usage", SDKDouble(omit_usage=True)),
            ("timeout", SDKDouble(create_error=TimeoutError("TEST_SECRET_NATIVE_ERROR"))),
        ):
            with self.subTest(name=name):
                ledger = self.new_ledger(f"{name}-ledger.json", calls=3)
                first = self.run_case(sdk, f"{name}-first", ledger=ledger)
                second = self.run_case(sdk, f"{name}-second", ledger=ledger)
                self.assertEqual(first.status, "provider_abort")
                self.assertIn(second.status, {"provider_abort", "budget_exhausted"})
                self.assertEqual(sdk.count_calls, 1)
                self.assertEqual(sdk.create_calls, 1)
                evidence = self.evidence_root / f"{name}-first"
                for path in evidence.rglob("*"):
                    if path.is_file():
                        self.assertNotIn("TEST_SECRET_NATIVE_ERROR", path.read_text(encoding="utf-8"))

    def test_checker_and_renderer_failures_abort_without_candidate_retry(self):
        sdk = SDKDouble()
        real_run = subprocess.run
        env_seen = []

        def checker_failure(*args, **kwargs):
            env_seen.append(kwargs["env"])
            return subprocess.CompletedProcess(args[0], 2, "", "component failed\n")

        with patch("harness.course_workflow.subprocess.run", side_effect=checker_failure):
            checker_result = self.run_case(sdk, "case-checker-failure")
        self.assertEqual(checker_result.status, "infrastructure_abort")
        self.assertEqual(checker_result.attempts, 1)
        self.assertEqual(sdk.create_calls, 1)
        self.assertEqual(len(env_seen), 1)

        sdk2 = SDKDouble()
        renderer_ledger = self.new_ledger("renderer-ledger.json")
        calls = 0

        def renderer_failure(*args, **kwargs):
            nonlocal calls
            calls += 1
            env_seen.append(kwargs["env"])
            if calls == 1:
                return real_run(*args, **kwargs)
            return subprocess.CompletedProcess(args[0], 9, "", "renderer failed\n")

        with patch("harness.course_workflow.subprocess.run", side_effect=renderer_failure):
            renderer_result = self.run_case(sdk2, "case-renderer-failure", ledger=renderer_ledger)
        self.assertEqual(renderer_result.status, "infrastructure_abort")
        self.assertEqual(renderer_result.failure_code, "renderer_failure")
        self.assertEqual(sdk2.create_calls, 1)
        self.assertTrue(all("OPENAI_API_KEY" not in environment for environment in env_seen))

    def test_key_and_benchmark_data_are_absent_from_requests_subprocesses_and_logs(self):
        sdk = SDKDouble()
        old_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "TEST_SECRET_API_KEY"
        real_run = subprocess.run
        observed_env = []

        def record_child_environment(*args, **kwargs):
            observed_env.append(kwargs["env"])
            return real_run(*args, **kwargs)

        try:
            with patch("harness.course_workflow.subprocess.run", side_effect=record_child_environment):
                result = self.run_case(sdk, "case-isolation")
        finally:
            if old_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_key

        self.assertEqual(result.status, "accepted")
        self.assertTrue(observed_env)
        self.assertTrue(all("OPENAI_API_KEY" not in environment for environment in observed_env))
        for kwargs in sdk.count_kwargs + sdk.create_kwargs:
            encoded = json.dumps(kwargs, ensure_ascii=False)
            self.assertNotIn("TEST_SECRET_API_KEY", encoded)
            self.assertNotIn("S00-base", encoded)
            self.assertNotIn("course-evaluation-reference", encoded)
            self.assertNotIn("score_candidate", encoded)
        for path in (self.evidence_root / "case-isolation").rglob("*"):
            if path.is_file():
                content = path.read_text(encoding="utf-8")
                self.assertNotIn("TEST_SECRET_API_KEY", content)
                self.assertNotIn("S00-base", content)

    def test_fresh_evidence_directory_is_required(self):
        path = self.evidence_root / "stale-case"
        path.mkdir()
        (path / "candidate.json").write_text("stale", encoding="utf-8")
        sdk = SDKDouble()
        with self.assertRaises(FileExistsError):
            course_workflow.run_course_workflow(SOURCE, self.ledger, sdk, path)
        self.assertEqual(sdk.count_calls, 0)
        self.assertEqual(sdk.create_calls, 0)

    def assert_later_case_is_blocked(self, sdk, name):
        before = (sdk.count_calls, sdk.create_calls)
        result = self.run_case(sdk, name)
        self.assertEqual(result.status, "provider_abort")
        self.assertEqual((sdk.count_calls, sdk.create_calls), before)

    def test_source_snapshot_write_failure_is_infrastructure_abort(self):
        sdk = SDKDouble()
        original = Path.write_bytes

        def fail_source(path, data):
            if path.name == "source.json":
                raise OSError("TEST_SECRET_SOURCE_IO")
            return original(path, data)

        with patch.object(Path, "write_bytes", fail_source):
            result = self.run_case(sdk, "case-source-io")
        self.assertEqual(result.status, "infrastructure_abort")
        self.assertTrue(self.ledger.state["blocked"])
        self.assertEqual((sdk.count_calls, sdk.create_calls), (0, 0))
        self.assert_later_case_is_blocked(sdk, "after-source-io")

    def test_provenance_write_failure_returns_safe_abort_and_blocks_later_case(self):
        sdk = SDKDouble()
        original = course_workflow._write_json

        def fail_provenance(path, value):
            if path.name == "source-provenance.json":
                raise OSError("TEST_SECRET_PROVENANCE_IO")
            return original(path, value)

        with patch.object(course_workflow, "_write_json", side_effect=fail_provenance):
            result = self.run_case(sdk, "case-provenance-io")
        self.assertEqual(result.status, "infrastructure_abort")
        self.assertTrue(self.ledger.state["blocked"])
        self.assertEqual((sdk.count_calls, sdk.create_calls), (0, 0))
        self.assert_later_case_is_blocked(sdk, "after-provenance-io")

    def test_missing_request_context_is_not_misreported_as_bad_source(self):
        sdk = SDKDouble()
        from harness.openai_course_client import RequestShapeError
        with patch.object(course_workflow, "build_extraction_request", side_effect=RequestShapeError("approved extraction prompt or schema is unavailable")):
            result = self.run_case(sdk, "case-context-failure")
        self.assertEqual(result.status, "infrastructure_abort")
        self.assertTrue(self.ledger.state["blocked"])
        self.assertEqual((sdk.count_calls, sdk.create_calls), (0, 0))
        self.assert_later_case_is_blocked(sdk, "after-context-failure")

    def test_render_receipt_write_failure_cannot_return_accepted(self):
        sdk = SDKDouble()
        original = course_workflow._write_json

        def fail_render_receipt(path, value):
            if path.name == "render.json":
                raise OSError("TEST_SECRET_RENDER_RECEIPT")
            return original(path, value)

        with patch.object(course_workflow, "_write_json", side_effect=fail_render_receipt):
            result = self.run_case(sdk, "case-render-receipt-io")
        self.assertEqual(result.status, "infrastructure_abort")
        self.assertTrue(self.ledger.state["blocked"])
        self.assertEqual(sdk.create_calls, 1)
        self.assert_later_case_is_blocked(sdk, "after-render-receipt-io")

    def test_result_receipt_failure_still_blocks_even_if_abort_receipt_cannot_write(self):
        sdk = SDKDouble()
        original = course_workflow._write_json

        def fail_result(path, value):
            if path.name == "result.json":
                raise OSError("TEST_SECRET_FINAL_RECEIPT")
            return original(path, value)

        with patch.object(course_workflow, "_write_json", side_effect=fail_result):
            result = self.run_case(sdk, "case-result-receipt-io")
        self.assertEqual(result.status, "infrastructure_abort")
        self.assertTrue(self.ledger.state["blocked"])
        self.assertEqual(sdk.create_calls, 1)
        self.assert_later_case_is_blocked(sdk, "after-result-receipt-io")

    def test_checker_and_renderer_interruptions_block_later_cases(self):
        real_run = subprocess.run
        for target_call in (1, 2):
            with self.subTest(component="checker" if target_call == 1 else "renderer"):
                ledger = self.new_ledger(f"interrupt-{target_call}.json")
                sdk = SDKDouble()
                calls = 0

                def interrupt(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == target_call:
                        raise KeyboardInterrupt
                    return real_run(*args, **kwargs)

                with patch.object(course_workflow.subprocess, "run", side_effect=interrupt):
                    try:
                        result = self.run_case(sdk, f"interrupt-case-{target_call}", ledger=ledger)
                    except KeyboardInterrupt:
                        self.fail("component interruption escaped without a structured abandoned outcome")
                self.assertEqual(result.status, "infrastructure_abort")
                self.assertEqual(result.failure_code, "interrupted")
                self.assertTrue(ledger.state["blocked"])
                before = (sdk.count_calls, sdk.create_calls)
                later = self.run_case(sdk, f"after-interrupt-{target_call}", ledger=ledger)
                self.assertEqual(later.status, "provider_abort")
                self.assertEqual((sdk.count_calls, sdk.create_calls), before)

    def test_unexpected_checker_exception_is_sanitized_and_blocks_later_cases(self):
        sdk = SDKDouble()
        with patch.object(course_workflow.subprocess, "run", side_effect=RuntimeError("TEST_SECRET_UNEXPECTED_COMPONENT")):
            result = self.run_case(sdk, "case-unexpected-component")
        self.assertEqual(result.status, "infrastructure_abort")
        self.assertTrue(self.ledger.state["blocked"])
        for path in (self.evidence_root / "case-unexpected-component").rglob("*"):
            if path.is_file():
                self.assertNotIn("TEST_SECRET_UNEXPECTED_COMPONENT", path.read_text(encoding="utf-8"))
        self.assert_later_case_is_blocked(sdk, "after-unexpected-component")

    def test_total_tokens_are_shared_across_two_cases_with_call_slots_left(self):
        ledger = self.new_ledger("shared-token-ledger.json", run=329, output=100, calls=3)
        sdk = SDKDouble()
        first = self.run_case(sdk, "token-case-first", ledger=ledger)
        second = self.run_case(sdk, "token-case-second", ledger=ledger)
        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.status, "budget_exhausted")
        self.assertEqual((sdk.count_calls, sdk.create_calls), (2, 1))
        self.assertEqual(ledger.state["confirmed_tokens"], 130)
        self.assertEqual(ledger.remaining_model_calls, 2)

    def test_retry_cannot_reset_the_remaining_token_allowance(self):
        ledger = self.new_ledger("retry-token-ledger.json", run=329, output=100, calls=3)
        candidate = make_candidate()
        candidate["courses"][0]["study_fee_nok"]["amount"] = 777
        sdk = SDKDouble([json.dumps(candidate), json.dumps(make_candidate())])
        result = self.run_case(sdk, "case-retry-token-stop", ledger=ledger)
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual((sdk.count_calls, sdk.create_calls), (2, 1))
        self.assertEqual(ledger.state["confirmed_tokens"], 130)
        self.assertEqual(ledger.remaining_model_calls, 2)


if __name__ == "__main__":
    unittest.main()

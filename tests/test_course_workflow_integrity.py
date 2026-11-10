"""Evidence-boundary regressions using synthetic sources and injected tools.

These tests isolate controller/evaluator integrity checks. The injected checker
statuses do not establish course-fact correctness; the existing fixture-based
checker, workflow and evaluation suites remain the integration controls.
"""

import copy
import hashlib
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from harness import course_sources, course_workflow, evaluate_courses, render_courses
from harness.model_budget import TokenLedger


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _SDK:
    max_retries = 0
    timeout = 90

    def __init__(self, text):
        self.text = text
        self.count_calls = 0
        self.create_calls = 0
        self.responses = self.input_tokens = self.with_raw_response = self

    @staticmethod
    def raw(payload, request_id):
        response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/json", "x-request-id": request_id},
            content=json.dumps(payload).encode(), close=lambda: None,
        )
        return SimpleNamespace(http_response=response)

    def count(self, **kwargs):
        self.count_calls += 1
        return self.raw({"object": "response.input_tokens", "input_tokens": 100},
                        f"req_count_{self.count_calls}")

    def create(self, **kwargs):
        self.create_calls += 1
        return self.raw({
            "object": "response", "id": f"resp_{self.create_calls}",
            "model": "gpt-6-luna", "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": self.text}]}],
        }, f"req_create_{self.create_calls}")


class CourseWorkflowIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {"schema_version": 1, "courses": [{
            "course_id": course_id, "source_url": url, "title": course_id,
            "retrieved_at": "2026-11-10T00:00:00Z",
            "source_text_is_untrusted_data": True,
            "source_sections": [{"label": "Course overview", "text": "Synthetic course context."}],
        } for course_id, url in course_sources.COURSES]}
        candidate = {"schema_version": 1, "courses": []}
        for source in self.source["courses"]:
            record = {k: source[k] for k in ("course_id", "source_url", "title", "retrieved_at")}
            record.update({
                "application_deadline": {"date": None, "evidence": []},
                "start_date": {"date": None, "evidence": []},
                "planned_period": {"value": None, "evidence": []},
                "prerequisites": [], "delivery_format": {"value": None, "evidence": []},
                "study_fee_nok": {"amount": None, "evidence": []},
                "materials_qualification": {"value": None, "evidence": []},
                "application_status": {"value": "not_stated", "evidence": []},
                "missing_or_uncertain_fields": ["application_deadline", "start_date",
                    "planned_period", "prerequisites", "delivery_format", "study_fee_nok",
                    "materials_qualification", "application_status"],
            })
            candidate["courses"].append(record)
        self.text = " \n" + json.dumps(candidate, ensure_ascii=False) + " \n"
        self.sequence = 0
        for name in ("create_connection", "getaddrinfo"):
            self.enterContext(mock.patch.object(socket, name, side_effect=AssertionError("network forbidden")))
        for name in ("connect", "connect_ex"):
            self.enterContext(mock.patch.object(socket.socket, name, side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch.object(course_workflow, "create_live_client",
                                           side_effect=AssertionError("live client forbidden")))

    def run_case(self, statuses=(0,), mutate=None, *, ledger=None):
        self.sequence += 1
        case = self.root / f"case-{self.sequence}"
        if ledger is None:
            ledger = TokenLedger(ledger_path=self.root / f"ledger-{self.sequence}.json",
                                 run_token_limit=10000, max_output_tokens=1000, max_model_calls=9)
        sdk = _SDK(self.text)
        status_list = list(statuses)
        renderer_calls = []
        injected = []
        original_write = course_workflow._write_json

        def tool(command, **kwargs):
            if Path(command[1]) == course_workflow.CHECKER:
                status = status_list.pop(0)
                return SimpleNamespace(returncode=status, stdout="synthetic checker feedback\n", stderr="")
            self.assertEqual(Path(command[1]), course_workflow.RENDERER)
            renderer_calls.append(command)
            status = render_courses.main(command[2:])
            return SimpleNamespace(returncode=status, stdout="", stderr="")

        def write_then_mutate(path, value):
            original_write(path, value)
            if (mutate is not None and path.name.startswith("attempt-")
                    and "checker_evidence_sha256" in value):
                injected.append(value["attempt"])
                mutate(case, value["attempt"])

        with mock.patch.object(course_workflow.subprocess, "run", side_effect=tool), \
             mock.patch.object(course_workflow, "_write_json", side_effect=write_then_mutate):
            result = course_workflow.run_course_workflow(self.source, ledger, sdk, case)
        return result, case, ledger, sdk, renderer_calls, injected

    def assert_abort(self, mutate, *, statuses=(0,), calls=1):
        result, case, ledger, sdk, renderers, injected = self.run_case(statuses, mutate)
        self.assertTrue(injected, "fault injection boundary was not reached")
        self.assertEqual(result.status, "infrastructure_abort")
        self.assertTrue(ledger.state["blocked"])
        self.assertEqual((sdk.count_calls, sdk.create_calls), (calls, calls))
        self.assertEqual(renderers, [])
        before = (sdk.count_calls, sdk.create_calls)
        later = course_workflow.run_course_workflow(self.source, ledger, sdk, case.parent / "blocked-later")
        self.assertNotEqual(later.status, "accepted")
        self.assertEqual((sdk.count_calls, sdk.create_calls), before)

    def evaluator_check(self, case, result, ledger):
        row = {"source_sha256": _hash(case / "source.json"), "source_path": "source.json"}
        with mock.patch.object(evaluate_courses, "ROOT", case):
            evaluate_courses._verify_actual_case_evidence(row, case, result, ledger)

    def test_clean_accepted_attempt_and_evaluator_control(self):
        result, case, ledger, sdk, renderers, _ = self.run_case()
        self.assertEqual(result.status, "accepted")
        self.assertEqual((sdk.count_calls, sdk.create_calls, len(renderers)), (1, 1, 1))
        self.evaluator_check(case, result, ledger)
        rejected, case, ledger, sdk, renderers, _ = self.run_case((1, 1, 1))
        self.assertEqual(rejected.status, "candidate_rejected")
        self.assertEqual((sdk.count_calls, sdk.create_calls, len(renderers)), (3, 3, 0))
        self.evaluator_check(case, rejected, ledger)

    def test_clean_retry_preserves_complete_attempt_history(self):
        result, case, ledger, sdk, renderers, _ = self.run_case((1, 0))
        self.assertEqual(result.status, "accepted")
        self.assertEqual((sdk.count_calls, sdk.create_calls, len(renderers)), (2, 2, 1))
        self.evaluator_check(case, result, ledger)
        later, case, ledger, sdk, renderers, _ = self.run_case(ledger=ledger)
        self.assertEqual(later.status, "accepted")
        self.assertEqual(ledger.state["model_calls"], 3)
        self.evaluator_check(case, later, ledger)

    def test_boolean_assembly_version_is_rejected(self):
        result, case, _, _, _, _ = self.run_case()
        self.assertEqual(result.status, "accepted")
        receipt = _read(case / "assembly-1.json")
        receipt["version"] = True
        _write(case / "assembly-1.json", receipt)
        with self.assertRaises(ValueError):
            course_workflow.verify_assembly_evidence(case, 1, self.source, _hash(case / "source.json"))

    def test_missing_raw_on_acceptance_blocks_before_render(self):
        self.assert_abort(lambda case, _: (case / "raw-response-1.txt").unlink())

    def test_source_provenance_change_blocks_acceptance(self):
        def mutate(case, _):
            receipt = _read(case / "source-provenance.json")
            receipt["approved_request_sha256"] = "0" * 64
            _write(case / "source-provenance.json", receipt)
        self.assert_abort(mutate)

    @staticmethod
    def rewrite_request(case):
        for name in ("request-attempt-1.json", "attempt-1.json"):
            value = _read(case / name)
            value["count_create_payload_sha256"] = "0" * 64
            _write(case / name, value)

    def test_request_rewrite_blocks_acceptance(self):
        self.assert_abort(lambda case, _: self.rewrite_request(case))

    def test_checker_feedback_change_blocks_acceptance(self):
        def mutate(case, _):
            value = _read(case / "candidate-check-1.json")
            value["stdout"] += "changed feedback\n"
            _write(case / "candidate-check-1.json", value)
        self.assert_abort(mutate)

    def test_earlier_raw_change_blocks_second_attempt_acceptance(self):
        def mutate(case, attempt):
            if attempt == 2:
                path = case / "raw-response-1.txt"
                path.write_bytes(path.read_bytes() + b" \n")
        self.assert_abort(mutate, statuses=(1, 0), calls=2)

    def test_earlier_receipt_loss_blocks_second_attempt_acceptance(self):
        def mutate(case, attempt):
            if attempt == 2:
                (case / "assembly-1.json").unlink()
        self.assert_abort(mutate, statuses=(1, 0), calls=2)

    def test_budget_receipt_rewrite_with_refreshed_hash_blocks_acceptance(self):
        def mutate(case, _):
            receipt = _read(case / "budget-after-attempt-1.json")
            receipt["confirmed_tokens"] += 1
            _write(case / "budget-after-attempt-1.json", receipt)
            record = _read(case / "attempt-1.json")
            record["budget_after_sha256"] = _hash(case / "budget-after-attempt-1.json")
            _write(case / "attempt-1.json", record)
        self.assert_abort(mutate)

    def test_final_rejection_requires_last_budget_receipt(self):
        def mutate(case, attempt):
            if attempt == 3:
                (case / "budget-after-attempt-3.json").unlink()
        self.assert_abort(mutate, statuses=(1, 1, 1), calls=3)

    def test_evaluator_rejects_consistently_rewritten_request_hashes(self):
        result, case, ledger, _, _, _ = self.run_case()
        self.assertEqual(result.status, "accepted")
        self.rewrite_request(case)
        with self.assertRaises(ValueError):
            self.evaluator_check(case, result, ledger)

    def test_evaluator_rejects_wrong_source_request_provenance(self):
        result, case, ledger, _, _, _ = self.run_case()
        self.assertEqual(result.status, "accepted")
        receipt = _read(case / "source-provenance.json")
        receipt["approved_request_sha256"] = "0" * 64
        _write(case / "source-provenance.json", receipt)
        with self.assertRaises(ValueError):
            self.evaluator_check(case, result, ledger)


if __name__ == "__main__":
    unittest.main()

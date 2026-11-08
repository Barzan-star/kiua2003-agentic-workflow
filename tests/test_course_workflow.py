"""Normal course CLI tests with a test-local SDK double and offline sources."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_course_records import SOURCE, make_candidate


ROOT = Path(__file__).resolve().parents[1]
FAKE_OPENAI = r'''"""Test-only OpenAI replacement; it has no HTTP implementation."""
import json, os, pathlib

class RawResponse:
    def __init__(self, payload, request_id):
        self.status_code = 200
        self.headers = {"content-type": "application/json", "x-request-id": request_id}
        self.content = json.dumps(payload, separators=(",", ":")).encode()
    def close(self):
        pass

class Raw:
    def __init__(self, payload, request_id):
        self.http_response = RawResponse(payload, request_id)

class Calls:
    def __init__(self):
        self.count = self
        self.with_raw_response = self
    def count(self, **kwargs):
        return Raw({"object":"response.input_tokens", "input_tokens":100}, "req_count")

class Responses:
    def __init__(self, owner):
        self.owner = owner
        self.input_tokens = type("InputTokens", (), {})()
        self.input_tokens.with_raw_response = type("CountRaw", (), {"count":owner.count})()
        self.with_raw_response = type("CreateRaw", (), {"create":owner.create})()

class FakeClient:
    max_retries = 0
    timeout = 90
    def __init__(self):
        self.calls = 0
        self.responses = Responses(self)
    def count(self, **kwargs):
        return Raw({"object":"response.input_tokens", "input_tokens":100}, "req_count")
    def create(self, **kwargs):
        self.calls += 1
        if os.environ.get("TEST_CREATE_ERROR"):
            raise TimeoutError("TEST_SECRET_NATIVE_ERROR")
        sequence = json.loads(os.environ.get("CANDIDATE_SEQUENCE", "[]"))
        candidate_path = sequence[min(self.calls - 1, len(sequence) - 1)] if sequence else os.environ["VALID_CANDIDATE"]
        text = pathlib.Path(candidate_path).read_text(encoding="utf-8")
        log_path = os.environ.get("REQUEST_LOG")
        if log_path:
            with open(log_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(kwargs, ensure_ascii=False) + "\n")
        response = {
          "object":"response", "id":f"resp_{self.calls}", "model":"gpt-6-luna", "status":"completed",
          "usage":{"input_tokens":100,"output_tokens":30,"total_tokens":130},
          "output":[] if os.environ.get("TEST_EMPTY_OUTPUT") else [{"type":"message","role":"assistant","status":"completed",
                      "content":[{"type":"output_text","text":text}]}]
        }
        return Raw(response, f"req_create_{self.calls}")
    def close(self):
        pass

def OpenAI(**kwargs):
    assert kwargs["max_retries"] == 0
    assert kwargs["api_key"] == os.environ["OPENAI_API_KEY"]
    return FakeClient()
'''


class CourseWorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        for name in ("harness", "eval", "fixtures"):
            shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns("__pycache__"))
        runner = self.root / "harness/run_courses.sh"
        runner.chmod(0o755)
        (self.root / "openai.py").write_text(FAKE_OPENAI, encoding="utf-8")
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir()
        self.valid = self.state / "valid.json"
        self.valid.write_text(json.dumps(make_candidate()), encoding="utf-8")
        bad = make_candidate()
        bad["courses"][0]["study_fee_nok"]["amount"] = 777
        self.invalid = self.state / "invalid.json"
        self.invalid.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        self.request_log = self.state / "requests.jsonl"
        self.env = os.environ.copy()
        self.env.pop("OPENAI_API_KEY", None)
        self.env.update({
            "VALID_CANDIDATE": str(self.valid),
            "REQUEST_LOG": str(self.request_log),
        })

    def tearDown(self):
        self.temp.cleanup()

    def run_runner(self, *args, cwd=None):
        return subprocess.run(
            [str(self.root / "harness/run_courses.sh"), *args],
            cwd=cwd or self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def run_actual(self, *args, cwd=None):
        self.env["OPENAI_API_KEY"] = "TEST_SECRET_DO_NOT_LOG"
        return self.run_runner(
            "--offline", "--run-token-limit", "1000", "--max-output-tokens", "100",
            "--max-model-calls", "3", *args, cwd=cwd,
        )

    def seed_publication(self):
        training = self.root / "out/training"
        training.mkdir(parents=True, exist_ok=True)
        (training / "courses.json").write_text("old-json\n", encoding="utf-8")
        (training / "comparison.md").write_text("old-markdown\n", encoding="utf-8")
        return training

    def assert_old_publication(self, training):
        self.assertEqual((training / "courses.json").read_text(), "old-json\n")
        self.assertEqual((training / "comparison.md").read_text(), "old-markdown\n")

    def stub_copied_cli(self, name, exit_code):
        # Stub only the script entry point in this temporary repository. Its
        # importable production functions remain unchanged for preflight.
        path = self.root / "harness" / name
        text = path.read_text(encoding="utf-8")
        marker = 'if __name__ == "__main__":'
        self.assertIn(marker, text)
        path.write_text(text[:text.rindex(marker)] + marker + f"\n    raise SystemExit({exit_code})\n", encoding="utf-8")

    def test_both_dry_runs_need_no_key_sdk_or_output_tree(self):
        for arguments in (("--offline", "--dry-run"), ("--dry-run",)):
            result = self.run_runner(*arguments, cwd=self.state)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Responses API", result.stdout)
            self.assertIn("--run-token-limit", result.stdout)
            self.assertIn("evidence", result.stdout.lower())
            self.assertFalse((self.root / "out").exists())
            self.assertFalse(self.request_log.exists())
            self.assertNotIn("TEST_SECRET_DO_NOT_LOG", result.stdout + result.stderr)

    def test_missing_unknown_and_invalid_arguments_fail_before_output_creation(self):
        for arguments in ((), ("--unknown",), ("--run-token-limit", "0"),
                          ("--run-token-limit", "10", "--max-output-tokens", "2")):
            result = self.run_runner(*arguments)
            self.assertEqual(result.returncode, 2, (arguments, result.stderr))
            self.assertFalse((self.root / "out").exists())
            self.assertFalse(self.request_log.exists())

    def test_missing_runtime_key_fails_before_live_collection_or_output_creation(self):
        result = self.run_runner("--run-token-limit", "100", "--max-output-tokens", "20", "--max-model-calls", "1")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertNotIn("TEST_SECRET", result.stdout + result.stderr)
        self.assertFalse((self.root / "out").exists())
        self.assertFalse(self.request_log.exists())
        self.env["OPENAI_API_KEY"] = "   "
        whitespace = self.run_runner("--run-token-limit", "100", "--max-output-tokens", "20", "--max-model-calls", "1")
        self.assertEqual(whitespace.returncode, 3)
        self.assertFalse((self.root / "out").exists())

    def test_offline_budgeted_cli_publishes_after_check_and_render(self):
        result = self.run_actual()
        self.assertEqual(result.returncode, 0, result.stderr)
        training = self.root / "out/training"
        published = json.loads((training / "courses.json").read_text(encoding="utf-8"))
        self.assertEqual(published, make_candidate())
        markdown = (training / "comparison.md").read_text(encoding="utf-8")
        self.assertIn("Søknadsfrist", markdown)
        self.assertIn("Kildeinnhentet", markdown)
        run_dirs = list(training.glob("run-*"))
        self.assertEqual(len(run_dirs), 1)
        snapshot = json.loads((run_dirs[0] / "course-sources.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot, SOURCE)
        self.assertFalse(os.access(run_dirs[0] / "course-sources.json", os.W_OK))
        self.assertTrue((run_dirs[0] / "ledger.json").is_file())
        self.assertTrue((run_dirs[0] / "case/candidate.json").is_file())
        self.assertTrue((run_dirs[0] / "case/candidate-check.json").is_file())
        self.assertTrue((run_dirs[0] / "case/rendered-courses.json").is_file())
        self.assertEqual(len(self.request_log.read_text(encoding="utf-8").splitlines()), 1)
        request = json.loads(self.request_log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(request["max_output_tokens"], 100)
        self.assertNotIn("TEST_SECRET_DO_NOT_LOG", json.dumps(request))
        self.assertNotIn("S00-base", json.dumps(request))
        self.assertNotIn("course-evaluation-reference", json.dumps(request))
        self.assertNotIn("TEST_SECRET_DO_NOT_LOG", result.stdout + result.stderr)

    def test_three_rejections_keep_prior_publication_unchanged(self):
        training = self.root / "out/training"
        training.mkdir(parents=True)
        (training / "courses.json").write_text("old-json\n", encoding="utf-8")
        (training / "comparison.md").write_text("old-markdown\n", encoding="utf-8")
        self.env["CANDIDATE_SEQUENCE"] = json.dumps([str(self.invalid)] * 3)
        result = self.run_actual()
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual((training / "courses.json").read_text(encoding="utf-8"), "old-json\n")
        self.assertEqual((training / "comparison.md").read_text(encoding="utf-8"), "old-markdown\n")
        self.assertEqual(len(self.request_log.read_text(encoding="utf-8").splitlines()), 3)
        run = next(training.glob("run-*"))
        case_dir = run / "case"
        self.assertTrue((case_dir / "candidate.json").is_file())
        result_evidence = json.loads((case_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result_evidence["status"], "candidate_rejected")
        self.assertEqual(result_evidence["attempts"], 3)

    def test_budgeted_success_from_outside_repository(self):
        result = self.run_actual(cwd=self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "out/training/courses.json").is_file())
        self.assertFalse((self.state / "out").exists())

    def test_native_timeout_preserves_publication_and_hides_exception_message(self):
        training = self.seed_publication()
        self.env["TEST_CREATE_ERROR"] = "1"
        result = self.run_actual()
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assert_old_publication(training)
        self.assertNotIn("TEST_SECRET_NATIVE_ERROR", result.stdout + result.stderr)
        run = next(training.glob("run-*"))
        ledger = json.loads((run / "ledger.json").read_text())
        self.assertTrue(ledger["blocked"])
        self.assertEqual(ledger["model_calls"], 1)
        self.assertEqual(ledger["reservations"][0]["status"], "uncertain")

    def test_empty_completed_output_cannot_publish_stale_candidate(self):
        training = self.seed_publication()
        self.env["TEST_EMPTY_OUTPUT"] = "1"
        result = self.run_actual()
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assert_old_publication(training)
        self.assertEqual(len(self.request_log.read_text().splitlines()), 1)

    def test_collector_failure_stops_before_generation(self):
        training = self.seed_publication()
        self.stub_copied_cli("course_sources.py", 9)
        result = self.run_actual()
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertFalse(self.request_log.exists())
        self.assert_old_publication(training)

    def test_collector_success_without_a_fresh_snapshot_cannot_use_old_source(self):
        training = self.seed_publication()
        (training / "course-sources.json").write_text(json.dumps(SOURCE), encoding="utf-8")
        self.stub_copied_cli("course_sources.py", 0)
        result = self.run_actual()
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertFalse(self.request_log.exists())
        self.assert_old_publication(training)

    def test_insufficient_token_allowance_preserves_existing_publication(self):
        training = self.seed_publication()
        result = self.run_actual("--run-token-limit", "199")
        self.assertEqual(result.returncode, 6, result.stderr)
        self.assertFalse(self.request_log.exists())
        self.assert_old_publication(training)
        run = next(training.glob("run-*"))
        self.assertEqual(json.loads((run / "ledger.json").read_text())["model_calls"], 0)

    def test_renderer_failure_does_not_publish_a_partially_prepared_result(self):
        training = self.seed_publication()
        self.stub_copied_cli("render_courses.py", 9)
        result = self.run_actual()
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assert_old_publication(training)
        self.assertEqual(len(self.request_log.read_text().splitlines()), 1)
        run = next(training.glob("run-*"))
        self.assertTrue(json.loads((run / "ledger.json").read_text())["blocked"])


if __name__ == "__main__":
    unittest.main()

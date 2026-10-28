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


class CourseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        for name in ("harness", "eval", "fixtures"):
            shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / "out").mkdir()
        (self.root / "harness/run_courses.sh").chmod(0o755)
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir()
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        self.fixture = self.state / "source.json"
        self.fixture.write_text(json.dumps(SOURCE), encoding="utf-8")
        self.valid = self.state / "valid.json"
        self.valid.write_text(json.dumps(make_candidate()), encoding="utf-8")
        self.invalid = self.state / "invalid.json"
        invalid_candidate = make_candidate()
        invalid_candidate["courses"][0]["study_fee_nok"]["amount"] = 777
        self.invalid.write_text(json.dumps(invalid_candidate), encoding="utf-8")
        self._write_stub("python3", '''#!/bin/sh
printf '%s\\n' "$*" >> "$COMMAND_LOG"
if [ "$1" = "harness/course_sources.py" ]; then
  mkdir -p out/training
  cp "$SOURCE_FIXTURE" out/training/course-sources.json
  exit 0
fi
if [ "$1" = "eval/check_courses.py" ] && [ "${CHECKER_MODE:-}" = "infrastructure" ]; then
  echo 'simulated checker infrastructure failure' >&2
  exit 2
fi
exec "$REAL_PYTHON" "$@"
''')
        self._write_stub("timeout", '''#!/bin/sh
printf 'timeout %s\\n' "$*" >> "$COMMAND_LOG"
if [ -n "${TIMEOUT_STATUS:-}" ]; then exit "$TIMEOUT_STATUS"; fi
shift 2
exec "$@"
''')
        self._write_stub("codex", '''#!/usr/bin/env python3
import json, os, pathlib, sys
state = pathlib.Path(os.environ["STATE_DIR"])
count_file = state / "codex-count"
count = int(count_file.read_text()) + 1 if count_file.exists() else 1
count_file.write_text(str(count))
(state / f"args-{count}.json").write_text(json.dumps(sys.argv[1:]))
(state / f"prompt-{count}.md").write_text(sys.stdin.read())
if os.environ.get("CODEX_FAIL"):
    raise SystemExit(int(os.environ["CODEX_FAIL"]))
if os.environ.get("CODEX_NO_OUTPUT"):
    raise SystemExit(0)
target = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
sequence = json.loads(os.environ.get("CANDIDATE_SEQUENCE", "[]"))
source = pathlib.Path(sequence[min(count - 1, len(sequence) - 1)] if sequence else os.environ.get("INVALID_CANDIDATE", os.environ["VALID_CANDIDATE"]))
target.write_bytes(source.read_bytes())
''')
        self.command_log = self.state / "commands.log"
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(self.bin) + os.pathsep + self.env.get("PATH", ""),
            "REAL_PYTHON": sys.executable,
            "SOURCE_FIXTURE": str(self.fixture),
            "VALID_CANDIDATE": str(self.valid),
            "COMMAND_LOG": str(self.command_log),
            "STATE_DIR": str(self.state),
        })

    def tearDown(self):
        self.temp.cleanup()

    def _write_stub(self, name, content):
        path = self.bin / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def run_runner(self, *args):
        return subprocess.run([str(self.root / "harness/run_courses.sh"), *args], cwd=self.root, env=self.env, capture_output=True, text=True)

    def codex_count(self):
        path = self.state / "codex-count"
        return int(path.read_text()) if path.exists() else 0

    def test_dry_run_is_side_effect_free(self):
        result = self.run_runner("--offline", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "out/training").exists())
        self.assertFalse(self.command_log.exists())
        self.assertIn("course_records.schema.json", result.stdout)

    def test_valid_candidate_publishes_json_and_source_linked_markdown(self):
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.codex_count(), 1)
        training = self.root / "out/training"
        published = json.loads((training / "courses.json").read_text(encoding="utf-8"))
        self.assertEqual(len(published["courses"]), 3)
        markdown = (training / "comparison.md").read_text(encoding="utf-8")
        self.assertIn("Søknadsfrist", markdown)
        self.assertIn("Kildeinnhentet", markdown)
        self.assertIn("https://www.fagskolen-innlandet.no/utdanninger/automasjon-for-elektrikere-pls", markdown)
        run_dirs = list(training.glob("run-*"))
        self.assertEqual(len(run_dirs), 1)
        self.assertEqual(json.loads((run_dirs[0] / "course-sources.json").read_text()), SOURCE)
        self.assertFalse(os.access(run_dirs[0] / "course-sources.json", os.W_OK))
        args = json.loads((self.state / "args-1.json").read_text())
        for flag in ("--strict-config", "--ephemeral", "--json", "--output-schema"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("-m") + 1], "gpt-6-luna")

    def test_model_failure_stops_without_publication(self):
        self.env["CODEX_FAIL"] = "7"
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.codex_count(), 1)
        self.assertFalse((self.root / "out/training/courses.json").exists())

    def test_missing_candidate_stops_without_using_old_or_publishing(self):
        self.env["CODEX_NO_OUTPUT"] = "1"
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.codex_count(), 1)
        self.assertFalse((self.root / "out/training/courses.json").exists())

    def test_only_validation_rejection_retries_and_exact_feedback_is_passed(self):
        self.env["INVALID_CANDIDATE"] = str(self.invalid)
        result = self.run_runner("--offline")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.codex_count(), 3)
        feedback = "study fee amount does not match a quoted NOK amount"
        self.assertIn(feedback, (self.state / "prompt-2.md").read_text())
        self.assertIn(feedback, (self.state / "prompt-3.md").read_text())
        self.assertFalse((self.root / "out/training/courses.json").exists())

    def test_agent_receives_explicit_indices_without_changing_source_snapshot(self):
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next((self.root / "out/training").glob("run-*"))
        snapshot = json.loads((run / "course-sources.json").read_text())
        self.assertEqual(snapshot, SOURCE)
        view_path = run / "agent-source-view.json"
        view = json.loads(view_path.read_text(encoding="utf-8"))
        self.assertEqual(len(view["courses"]), len(SOURCE["courses"]))
        for original, annotated in zip(SOURCE["courses"], view["courses"]):
            self.assertEqual(original["course_id"], annotated["course_id"])
            self.assertEqual(len(original["source_sections"]), len(annotated["source_sections"]))
            for index, (section, displayed) in enumerate(zip(original["source_sections"], annotated["source_sections"])):
                self.assertEqual(displayed, {**section, "section_index": index})
        prompt = (self.state / "prompt-1.md").read_text(encoding="utf-8")
        self.assertIn(view_path.read_text(encoding="utf-8"), prompt)

    def test_retry_has_rejected_candidate_and_feedback_before_valid_publication(self):
        self.env["CANDIDATE_SEQUENCE"] = json.dumps([str(self.invalid), str(self.valid)])
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.codex_count(), 2)
        prompt = (self.state / "prompt-2.md").read_text(encoding="utf-8")
        self.assertTrue(self.invalid.read_text(encoding="utf-8") in prompt,
                        "The retry prompt must contain the actual rejected JSON candidate")
        self.assertIn("study fee amount does not match a quoted NOK amount", prompt)
        published = self.root / "out/training/courses.json"
        self.assertEqual(json.loads(published.read_text()), make_candidate())

    def test_checker_infrastructure_error_does_not_retry_or_publish(self):
        self.env["CHECKER_MODE"] = "infrastructure"
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.codex_count(), 1)
        self.assertFalse((self.root / "out/training/courses.json").exists())

    def test_timeout_stops_before_codex_and_publication(self):
        self.env["TIMEOUT_STATUS"] = "124"
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 124)
        self.assertEqual(self.codex_count(), 0)
        self.assertFalse((self.root / "out/training/courses.json").exists())

    def test_rejected_candidate_leaves_existing_publication_untouched(self):
        training = self.root / "out/training"
        training.mkdir()
        (training / "courses.json").write_text("old-valid-output\n")
        (training / "comparison.md").write_text("old-valid-report\n")
        self.env["INVALID_CANDIDATE"] = str(self.invalid)
        result = self.run_runner("--offline")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((training / "courses.json").read_text(), "old-valid-output\n")
        self.assertEqual((training / "comparison.md").read_text(), "old-valid-report\n")


if __name__ == "__main__":
    unittest.main()

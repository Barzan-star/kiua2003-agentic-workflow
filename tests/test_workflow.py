import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "harness" / "run.sh"


class WorkflowRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        (self.root / "harness" / "prompts").mkdir(parents=True)
        (self.root / "eval").mkdir()
        (self.root / "fixtures").mkdir()
        shutil.copy2(RUNNER, self.root / "harness" / "run.sh")
        (self.root / "harness" / "prompts" / "summarise.md").write_text(
            "Original summary instructions.\n", encoding="utf-8"
        )
        (self.root / "fixtures" / "met_hamar.json").write_text("fixture\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        self._write_stub("python3", self.python_stub())
        self._write_stub("timeout", self.timeout_stub())
        self._write_stub("codex", self.codex_stub())
        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.bin}{os.pathsep}{self.env['PATH']}"
        self.env["WORKFLOW_STATE"] = str(self.state)

    def _write_stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
        path.chmod(0o755)

    @staticmethod
    def python_stub():
        return '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
state = Path(os.environ["WORKFLOW_STATE"])
with (state / "commands.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\\n")
if args[:2] == ["harness/probe.py", "--offline"] or args == ["harness/probe.py"]:
    raise SystemExit(int(os.environ.get("PROBE_STATUS", "0")))
if args == ["eval/check_probe.py"]:
    raise SystemExit(int(os.environ.get("PROBE_CHECK_STATUS", "0")))
if args and args[0] == "eval/check_summary.py":
    candidate = Path(args[args.index("--summary") + 1])
    if not candidate.is_file():
        print("cannot read summary candidate")
        raise SystemExit(2)
    count_file = state / "checker-count"
    count = int(count_file.read_text() if count_file.exists() else "0") + 1
    count_file.write_text(str(count))
    statuses = json.loads(os.environ.get("CHECK_STATUSES", "[0]"))
    status = statuses[min(count - 1, len(statuses) - 1)]
    print(os.environ.get("CHECK_FEEDBACK", "FAIL: rejected candidate"))
    raise SystemExit(status)
raise SystemExit(90)
'''

    @staticmethod
    def timeout_stub():
        return '''import os, subprocess, sys
from pathlib import Path
state = Path(os.environ["WORKFLOW_STATE"])
(state / "timeout-called").write_text("yes")
if os.environ.get("TIMEOUT_STATUS"):
    raise SystemExit(int(os.environ["TIMEOUT_STATUS"]))
args = sys.argv[1:]
if args[:2] == ["--kill-after=5s", "90s"]:
    args = args[2:]
raise SystemExit(subprocess.run(args).returncode)
'''

    @staticmethod
    def codex_stub():
        return '''import json, os, sys
from pathlib import Path
state = Path(os.environ["WORKFLOW_STATE"])
count_file = state / "codex-count"
count = int(count_file.read_text() if count_file.exists() else "0") + 1
count_file.write_text(str(count))
prompt = sys.stdin.read()
(state / f"prompt-{count}.txt").write_text(prompt, encoding="utf-8")
(state / f"codex-args-{count}.json").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
if os.environ.get("CODEX_STATUS"):
    raise SystemExit(int(os.environ["CODEX_STATUS"]))
if os.environ.get("CODEX_NO_OUTPUT"):
    raise SystemExit(0)
output = sys.argv[sys.argv.index("-o") + 1]
Path(output).write_text(f"fresh candidate {count}\\n", encoding="utf-8")
print("{}")
'''

    def run_runner(self, *args, cwd=None):
        return subprocess.run(
            ["bash", str(self.root / "harness" / "run.sh"), *args],
            cwd=cwd or self.root,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def codex_count(self):
        path = self.state / "codex-count"
        return int(path.read_text()) if path.exists() else 0

    def checker_count(self):
        path = self.state / "checker-count"
        return int(path.read_text()) if path.exists() else 0

    def test_dry_run_from_elsewhere_prints_plan_without_writing(self):
        result = self.run_runner("--offline", "--dry-run", cwd=self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Stage 1: probe", result.stdout)
        self.assertIn("Stage 2: check probe", result.stdout)
        self.assertIn("Stage 3: generate and check summary", result.stdout)
        self.assertIn("fixtures/met_hamar.json", result.stdout)
        self.assertIn("course_summary", result.stdout)
        self.assertFalse((self.root / "out").exists())
        self.assertEqual(self.codex_count(), 0)
        self.assertFalse((self.state / "commands.jsonl").exists())

    def test_stages_run_in_order_before_model_and_candidate_passes(self):
        result = self.run_runner("--offline", cwd=self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [json.loads(line) for line in (self.state / "commands.jsonl").read_text().splitlines()]
        self.assertEqual(commands[:2], [["harness/probe.py", "--offline"], ["eval/check_probe.py"]])
        self.assertEqual(commands[2][0], "eval/check_summary.py")
        self.assertEqual(self.codex_count(), 1)
        run_dirs = list((self.root / "out").glob("workflow-*"))
        self.assertEqual(len(run_dirs), 1)
        candidate = run_dirs[0] / "summary-attempt-1.md"
        self.assertEqual(candidate.read_text(), "fresh candidate 1\n")
        self.assertEqual((self.root / "out" / "summary.md").read_text(), candidate.read_text())
        self.assertTrue((run_dirs[0] / "summary-attempt-1.events.jsonl").exists())
        codex_args = json.loads((self.state / "codex-args-1.json").read_text())
        self.assertIn('default_permissions="course_summary"', codex_args)

    def test_probe_failure_stops_before_checker_and_model(self):
        self.env["PROBE_STATUS"] = "2"
        result = self.run_runner("--offline")
        self.assertNotEqual(result.returncode, 0)
        commands = [json.loads(line) for line in (self.state / "commands.jsonl").read_text().splitlines()]
        self.assertEqual(commands, [["harness/probe.py", "--offline"]])
        self.assertEqual(self.codex_count(), 0)

    def test_probe_checker_failure_stops_before_model(self):
        self.env["PROBE_CHECK_STATUS"] = "1"
        result = self.run_runner("--offline")
        self.assertNotEqual(result.returncode, 0)
        commands = [json.loads(line) for line in (self.state / "commands.jsonl").read_text().splitlines()]
        self.assertEqual(commands, [["harness/probe.py", "--offline"], ["eval/check_probe.py"]])
        self.assertEqual(self.codex_count(), 0)

    def test_checker_feedback_is_in_next_prompt_then_success_stops(self):
        self.env["CHECK_STATUSES"] = "[1, 0]"
        self.env["CHECK_FEEDBACK"] = "FAIL: exact checker detail\nsecond detail"
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.codex_count(), 2)
        self.assertEqual(self.checker_count(), 2)
        second_prompt = (self.state / "prompt-2.txt").read_text()
        self.assertTrue(second_prompt.startswith("Original summary instructions."))
        self.assertIn("FAIL: exact checker detail\nsecond detail", second_prompt)
        self.assertEqual((self.root / "out" / "summary.md").read_text(), "fresh candidate 2\n")

    def test_three_rejections_exit_nonzero_and_leave_old_summary_untouched(self):
        self.env["CHECK_STATUSES"] = "[1, 1, 1]"
        out = self.root / "out"
        out.mkdir()
        old = out / "summary.md"
        old.write_text("old summary evidence\n", encoding="utf-8")
        result = self.run_runner("--offline")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.codex_count(), 3)
        self.assertEqual(self.checker_count(), 3)
        self.assertEqual(old.read_text(), "old summary evidence\n")
        self.assertEqual(len(list(out.glob("workflow-*/summary-attempt-[123].md"))), 3)

    def test_checker_file_or_input_error_aborts_without_retry(self):
        self.env["CHECK_STATUSES"] = "[2, 0]"
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.codex_count(), 1)
        commands = [json.loads(line) for line in (self.state / "commands.jsonl").read_text().splitlines()]
        self.assertEqual(sum(command[0] == "eval/check_summary.py" for command in commands), 1)

    def test_codex_failure_aborts_without_checking_candidate(self):
        self.env["CODEX_STATUS"] = "7"
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.codex_count(), 1)
        self.assertEqual(self.checker_count(), 0)

    def test_timeout_aborts_without_checking_candidate(self):
        self.env["TIMEOUT_STATUS"] = "124"
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 124)
        self.assertEqual(self.codex_count(), 0)
        self.assertEqual(self.checker_count(), 0)

    def test_missing_candidate_cannot_be_satisfied_by_old_summary(self):
        self.env["CODEX_STATUS"] = "0"
        out = self.root / "out"
        out.mkdir()
        old = out / "summary.md"
        old.write_text("old passing summary\n", encoding="utf-8")
        self.env["CODEX_NO_OUTPUT"] = "1"
        # Replace the Codex stub with one that succeeds without writing -o.
        self._write_stub("codex", '''import sys\nraise SystemExit(0)\n''')
        result = self.run_runner("--offline")
        self.assertEqual(result.returncode, 2)
        commands = [json.loads(line) for line in (self.state / "commands.jsonl").read_text().splitlines()]
        self.assertEqual(sum(command[0] == "eval/check_summary.py" for command in commands), 1)
        self.assertEqual(old.read_text(), "old passing summary\n")


if __name__ == "__main__":
    unittest.main()

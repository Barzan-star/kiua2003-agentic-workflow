"""Reproducibility and write-boundary controls for the offline stress runner."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from harness import stress_courses

ROOT = Path(__file__).resolve().parents[1]


class CourseStressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        files = set(stress_courses.COPY_FILES) | {
            "harness/stress_courses.py", "harness/course_stress_driver.py",
        }
        files.update(str(p.relative_to(ROOT)) for p in (ROOT / "fixtures/courses/stress").glob("*") if p.is_file())
        for name in files:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)

    def test_complete_study_runs_without_git_or_historical_run_directories(self):
        publication = self.root / "out/training"
        publication.mkdir(parents=True)
        before = {"courses.json": b'{"sentinel":"previous publication"}\n',
                  "comparison.md": b"Previous comparison remains available.\n"}
        for name, data in before.items():
            (publication / name).write_bytes(data)
        directory, report = stress_courses.run_study(self.root)
        self.assertEqual(report["status"], "complete", report)
        self.assertEqual(report["declared_controls_met"], 10)
        self.assertEqual(report["live_provider_requests"], 0)
        self.assertTrue(report["normal_publication_unchanged"])
        self.assertFalse((self.root / ".git").exists())
        self.assertFalse((self.root / "out/course-evaluations").exists())
        for name, data in before.items():
            self.assertEqual((publication / name).read_bytes(), data)
        manifest = json.loads((directory / "run-manifest.json").read_text())
        for name, expected in manifest["run_output_sha256"].items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), expected)
        result = json.loads((directory / "study-results.json").read_text())
        self.assertEqual(len(result["historical_current_identical_input_comparison"]), 3)

    def test_changed_retained_candidate_is_refused_before_a_study_directory_exists(self):
        candidate = self.root / "fixtures/courses/stress/candidate-base.json"
        candidate.write_bytes(candidate.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "retained stress input hash differs"):
            stress_courses.run_study(self.root)
        self.assertFalse((self.root / "out").exists())

    def test_redirected_output_directory_cannot_escape_the_checkout(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.root / "out").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "stress evidence must stay"):
            stress_courses.run_study(self.root)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

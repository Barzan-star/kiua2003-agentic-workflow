import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eval import check_summary


def sample_probe():
    return {"items": [{"temperature_c": -2}, {"temperature_c": 5.0}, {"temperature_c": 3}]}


VALID_SUMMARY = (
    "Hamar has a cool forecast today, with temperatures ranging from -2 °C to "
    "5.0 °C. Conditions remain variable through the period, so residents should "
    "dress warmly and check the forecast again before heading outside."
)


class SummaryCheckTests(unittest.TestCase):
    def test_valid_summary_accepts_equivalent_numeric_formatting(self):
        summary = VALID_SUMMARY.replace("-2 °C", "-2.0 °C")
        self.assertEqual(check_summary.validate(sample_probe(), summary), [])

    def test_valid_lowercase_celsius_is_accepted(self):
        summary = VALID_SUMMARY.replace("°C", "°c")
        self.assertEqual(check_summary.validate(sample_probe(), summary), [])

    def test_missing_hamar_is_rejected(self):
        summary = VALID_SUMMARY.replace("Hamar", "the town")
        self.assertTrue(any("Hamar" in error for error in check_summary.validate(sample_probe(), summary)))

    def test_short_summary_is_rejected(self):
        errors = check_summary.validate(sample_probe(), "Hamar -2 °C and 5 °C.")
        self.assertTrue(any("20–80 words" in error for error in errors))

    def test_long_summary_is_rejected(self):
        summary = VALID_SUMMARY + " " + "forecast " * 80
        errors = check_summary.validate(sample_probe(), summary)
        self.assertTrue(any("20–80 words" in error for error in errors))

    def test_missing_extreme_is_rejected(self):
        summary = VALID_SUMMARY.replace("5.0 °C", "4 °C")
        errors = check_summary.validate(sample_probe(), summary)
        self.assertTrue(any("maximum temperature" in error for error in errors))

    def test_invented_temperature_is_rejected(self):
        summary = VALID_SUMMARY.replace("variable through", "12 °C before changing through")
        errors = check_summary.validate(sample_probe(), summary)
        self.assertTrue(any("not present" in error for error in errors))

    def test_invented_lowercase_celsius_temperature_is_rejected(self):
        summary = VALID_SUMMARY.replace("variable through", "12 °c before changing through")
        errors = check_summary.validate(sample_probe(), summary)
        self.assertTrue(any("not present" in error for error in errors))

    def test_missing_summary_file_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe_path = root / "probe.json"
            summary_path = root / "missing.md"
            probe_path.write_text(json.dumps(sample_probe()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(check_summary_path()).resolve()),
                    "--probe",
                    str(probe_path),
                    "--summary",
                    str(summary_path),
                ],
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read summary file", result.stderr)


def check_summary_path():
    return Path(__file__).resolve().parents[1] / "eval" / "check_summary.py"


if __name__ == "__main__":
    unittest.main()

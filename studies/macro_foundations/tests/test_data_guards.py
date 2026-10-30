"""Synthetic guard fixtures only; these are never mixed into research observations."""
import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pipeline import decode_csv, normalized, bounded


class DataGuards(unittest.TestCase):
    def test_http_200_maintenance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTML_RESPONSE_NOT_DATA"):
            decode_csv(b"<!doctype html><html><title>Site Maintenance</title></html>")

    def test_duplicate_dates_abort(self):
        fixture = pd.DataFrame({"Date": ["01/02/2020", "01/02/2020"], "10 Yr": [1.8, 1.9]})
        with self.assertRaisesRegex(ValueError, "DUPLICATE_OBSERVATION_DATES"):
            normalized(fixture, {"10 yr": "ust_10y"}, "%m/%d/%Y")

    def test_non_numeric_observation_is_not_silently_dropped(self):
        fixture = pd.DataFrame({"Date": ["01/02/2020"], "10 Yr": ["temporarily unavailable"]})
        with self.assertRaisesRegex(ValueError, "INVALID_NUMERIC_VALUE"):
            normalized(fixture, {"10 yr": "ust_10y"}, "%m/%d/%Y")

    def test_future_rows_excluded_and_missing_preserved(self):
        fixture = pd.DataFrame({"x": [1., None, 3.]}, index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]))
        result = bounded(fixture, "2020-01-01", "2020-01-02")
        self.assertEqual(len(result), 2)
        self.assertTrue(pd.isna(result.loc["2020-01-02", "x"]))


if __name__ == "__main__":
    unittest.main()

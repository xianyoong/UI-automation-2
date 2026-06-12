"""Unit tests for scripts/authoring/author_test.py _apply_capture."""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "authoring"))
sys.path.insert(0, REPO_ROOT)

from author_test import _apply_capture  # noqa: E402


class ApplyCaptureTests(unittest.TestCase):
    def test_cols_and_rows_cols_selectors(self):
        vars_dict = {}
        _apply_capture(
            "a\tb\tc\nd\te\tf\n",
            {"vars.x": "$.cols[1]", "vars.y": "$.rows[1].cols[2]"},
            vars_dict,
        )
        self.assertEqual(vars_dict, {"x": "b", "y": "f"})

    def test_out_of_range_cols_raises(self):
        with self.assertRaises(ValueError):
            _apply_capture("a\tb", {"vars.z": "$.cols[5]"}, {})

    def test_out_of_range_rows_raises(self):
        with self.assertRaises(ValueError):
            _apply_capture("a\tb", {"vars.z": "$.rows[3].cols[0]"}, {})

    def test_bad_dst_prefix_raises(self):
        with self.assertRaises(ValueError):
            _apply_capture("a", {"foo": "$.cols[0]"}, {})

    def test_bad_selector_raises(self):
        with self.assertRaises(ValueError):
            _apply_capture("a", {"vars.x": "not_a_selector"}, {})


if __name__ == "__main__":
    unittest.main()

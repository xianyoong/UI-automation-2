"""Unit tests for scripts/authoring/author_test.py RecurrenceDetector."""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "authoring"))
sys.path.insert(0, REPO_ROOT)

from author_test import RecurrenceDetector  # noqa: E402


class RecurrenceDetectorTests(unittest.TestCase):
    def test_empty_returns_none(self):
        d = RecurrenceDetector()
        self.assertIsNone(d.observe({}, None))
        self.assertIsNone(d.observe({}, ""))

    def test_two_same_returns_none(self):
        d = RecurrenceDetector()
        self.assertIsNone(d.observe({}, "abc"))
        self.assertIsNone(d.observe({}, "abc"))

    def test_three_same_returns_hash(self):
        d = RecurrenceDetector()
        d.observe({}, "abc")
        d.observe({}, "abc")
        self.assertEqual(d.observe({}, "abc"), "abc")

    def test_three_with_a_different_does_not_trigger(self):
        d = RecurrenceDetector()
        d.observe({}, "abc")
        d.observe({}, "xyz")
        self.assertIsNone(d.observe({}, "abc"))

    def test_sliding_window_resets_correctly(self):
        d = RecurrenceDetector()
        # 5 observations; only the last 3 must all match to fire.
        for h in ["a", "b", "a", "a"]:
            self.assertIsNone(d.observe({}, h))
        # window is now ["b", "a", "a"]; one more "a" should fire.
        self.assertEqual(d.observe({}, "a"), "a")

    def test_reset_clears_window(self):
        d = RecurrenceDetector()
        d.observe({}, "x")
        d.observe({}, "x")
        d.reset()
        self.assertIsNone(d.observe({}, "x"))
        self.assertIsNone(d.observe({}, "x"))
        self.assertEqual(d.observe({}, "x"), "x")


if __name__ == "__main__":
    unittest.main()

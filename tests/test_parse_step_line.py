"""Unit tests for scripts/authoring/author_test.py parse_step_line selectors.

Covers selector emission (--auto-id / --name / --name-fallback) and the
maximize shorthand.
"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "authoring"))
sys.path.insert(0, REPO_ROOT)

import author_test  # noqa: E402
from author_test import parse_step_line  # noqa: E402


class ParseStepLineSelectorTests(unittest.TestCase):
    def test_click_with_auto_id_and_name_emits_name_fallback(self):
        steps = parse_step_line(
            'click "Close" type=Button auto_id=CloseButton parent=win_hwnd'
        )
        self.assertIsInstance(steps, list)
        find = steps[0]
        self.assertEqual(find["type"], "find_control")
        args = find["args_expr"]
        self.assertIn("--auto-id", args)
        self.assertIn("CloseButton", args)
        self.assertIn("--name", args)
        self.assertIn("Close", args)
        self.assertIn("--name-fallback", args)

    def test_click_name_only_does_not_emit_name_fallback(self):
        steps = parse_step_line('click "Close" type=Button parent=win_hwnd')
        find = steps[0]
        args = find["args_expr"]
        self.assertIn("--name", args)
        self.assertNotIn("--auto-id", args)
        self.assertNotIn("--name-fallback", args)

    def test_find_control_with_both_selectors_emits_name_fallback(self):
        step = parse_step_line(
            'find_control parent=win_hwnd name="Close" auto_id=CloseButton type=Button'
        )
        self.assertEqual(step["type"], "find_control")
        args = step["args_expr"]
        self.assertIn("--auto-id", args)
        self.assertIn("--name", args)
        self.assertIn("--name-fallback", args)

    def test_maximize_defaults_to_win_hwnd(self):
        step = parse_step_line("maximize")
        self.assertEqual(step["type"], "maximize_window")
        self.assertEqual(step["script"], "scripts/window/maximize_window.py")
        self.assertEqual(step["args_expr"], ["{vars.win_hwnd}"])

    def test_maximize_accepts_explicit_hwnd_var(self):
        step = parse_step_line("maximize myhwnd")
        self.assertEqual(step["type"], "maximize_window")
        self.assertEqual(step["args_expr"], ["{vars.myhwnd}"])

    def test_maximize_rejects_extra_tokens(self):
        with self.assertRaises(author_test.StepParseError):
            parse_step_line("maximize win_hwnd extra")


if __name__ == "__main__":
    unittest.main()

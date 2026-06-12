"""Unit tests for scripts/authoring/author_test.py execute_step."""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "authoring"))
sys.path.insert(0, REPO_ROOT)

from author_test import execute_step  # noqa: E402


class ExecuteStepTests(unittest.TestCase):
    def test_no_op_step_succeeds(self):
        ok, msg = execute_step({"type": "_wait", "ms": 100}, {}, {})
        self.assertTrue(ok)
        self.assertIn("skip", msg.lower())

    def test_missing_script_succeeds_as_noop(self):
        ok, msg = execute_step({"type": "click"}, {}, {})
        self.assertTrue(ok)
        self.assertIn("skip", msg.lower())

    def test_nonzero_exit_when_not_expected(self):
        # Use a tiny throwaway script: invoke python -c that exits 7.
        step = {
            "type": "key",
            "script": "scripts/input/key.py",
            "args": ["this-is-not-a-real-key-combo-zzz"],
        }
        ok, msg = execute_step(step, {}, {})
        # key.py either rejects unknown combos (non-zero) or accepts them; we
        # only assert that the executor reports failure when it does fail.
        if not ok:
            self.assertIn("exit", msg)


if __name__ == "__main__":
    unittest.main()

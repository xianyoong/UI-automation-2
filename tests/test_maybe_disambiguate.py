"""Unit tests for scripts/authoring/author_test.py maybe_disambiguate."""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "authoring"))
sys.path.insert(0, REPO_ROOT)

from author_test import AmbiguousMatch, maybe_disambiguate  # noqa: E402


class MaybeDisambiguateTests(unittest.TestCase):
    def test_non_find_control_is_noop(self):
        step = {"type": "click", "script": "scripts/input/click.py", "args": [10, 20]}
        out = maybe_disambiguate(step, {}, {})
        self.assertIs(out, step)

    def test_step_without_script_is_noop(self):
        step = {"type": "find_control"}
        out = maybe_disambiguate(step, {}, {})
        self.assertIs(out, step)

    def test_ambiguous_match_raises(self):
        # Stub out subprocess.run to simulate two matches under --all.
        import subprocess as _sub
        real_run = _sub.run
        fake_stdout = (
            "name\tauto_id\tcontrol_type\tleft\ttop\tright\tbottom\tcenter_x\tcenter_y\n"
            "Close\tCloseA\tButton\t0\t0\t10\t10\t5\t5\n"
            "Close\tCloseB\tButton\t100\t0\t110\t10\t105\t5\n"
        )

        class FakeProc:
            returncode = 0
            stdout = fake_stdout
            stderr = ""

        def fake_run(cmd, **kwargs):
            # sanity: probe must include --all
            self.assertIn("--all", cmd)
            return FakeProc()

        _sub.run = fake_run
        try:
            step = {
                "type": "find_control",
                "script": "scripts/uia/find_control.py",
                "args": ["12345", "--name", "Close"],
            }
            with self.assertRaises(AmbiguousMatch) as ctx:
                maybe_disambiguate(step, {}, {})
            self.assertEqual(len(ctx.exception.matches), 2)
        finally:
            _sub.run = real_run

    def test_single_match_passes_through(self):
        import subprocess as _sub
        real_run = _sub.run
        single = (
            "name\tauto_id\tcontrol_type\tleft\ttop\tright\tbottom\tcenter_x\tcenter_y\n"
            "Close\tCloseA\tButton\t0\t0\t10\t10\t5\t5\n"
        )

        class FakeProc:
            returncode = 0
            stdout = single
            stderr = ""

        _sub.run = lambda cmd, **kwargs: FakeProc()
        try:
            step = {
                "type": "find_control",
                "script": "scripts/uia/find_control.py",
                "args": ["12345", "--name", "Close"],
            }
            self.assertIs(maybe_disambiguate(step, {}, {}), step)
        finally:
            _sub.run = real_run

    def test_strips_existing_nth_and_all_before_probe(self):
        import subprocess as _sub
        real_run = _sub.run
        captured_cmd = {}

        class FakeProc:
            returncode = 0
            stdout = "header\n"
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return FakeProc()

        _sub.run = fake_run
        try:
            step = {
                "type": "find_control",
                "script": "scripts/uia/find_control.py",
                "args": ["12345", "--name", "Close", "--nth", "3", "--all"],
            }
            maybe_disambiguate(step, {}, {})
            cmd = captured_cmd["cmd"]
            self.assertNotIn("--nth", cmd)
            self.assertNotIn("3", cmd)
            # --all should appear exactly once even though we stripped the
            # original and re-appended.
            self.assertEqual(cmd.count("--all"), 1)
        finally:
            _sub.run = real_run


if __name__ == "__main__":
    unittest.main()

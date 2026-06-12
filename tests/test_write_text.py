"""Unit tests for scripts/write_text.py (no browser, uses a temp dir)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "files"))

import write_text  # noqa: E402


def _run(argv):
    old_argv = sys.argv
    sys.argv = ["write_text.py"] + argv
    out = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out):
            write_text.main()
    except SystemExit as e:
        code = e.code or 0
    finally:
        sys.argv = old_argv
    return code, out.getvalue()


class WriteTextTests(unittest.TestCase):
    def test_writes_empty_file_and_prints_abspath(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "sub", "notes.txt")
            code, out = _run(["--out", target])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(target))
            self.assertEqual(out.splitlines()[0], os.path.abspath(target))
            self.assertEqual(os.path.getsize(target), 0)

    def test_newline_escape_becomes_real_newline(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "n.txt")
            _run(["--out", target, "--text", "a\\nb"])
            with open(target, encoding="utf-8") as f:
                self.assertEqual(f.read(), "a\nb")

    def test_append_mode(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "a.txt")
            _run(["--out", target, "--text", "one"])
            _run(["--out", target, "--text", "two", "--append"])
            with open(target, encoding="utf-8") as f:
                self.assertEqual(f.read(), "onetwo")


if __name__ == "__main__":
    unittest.main()

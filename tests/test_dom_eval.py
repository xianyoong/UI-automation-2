"""Unit tests for scripts/dom_eval.py (no live browser).

``connect_page`` is monkeypatched with a fake session so we can assert how the
evaluated value is rendered to stdout and how exit codes map to null results.
"""
import contextlib
import io
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "web"))

import cdp_client  # noqa: E402
import dom_eval  # noqa: E402


class FakeSession:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def evaluate(self, expr):
        return self._value


def _run(value, expr="x"):
    """Run dom_eval.main() with a fake session; return (exit_code, stdout)."""
    def fake_connect(port, url_contains):
        return FakeSession(value)

    orig = cdp_client.connect_page
    cdp_client.connect_page = fake_connect
    argv = ["dom_eval.py", "--expr", expr, "--port", "9999"]
    old_argv = sys.argv
    sys.argv = argv
    out = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out):
            dom_eval.main()
    except SystemExit as e:
        code = e.code or 0
    finally:
        sys.argv = old_argv
        cdp_client.connect_page = orig
    return code, out.getvalue()


class DomEvalTests(unittest.TestCase):
    def test_string_printed_as_first_line(self):
        code, out = _run("+60199301339")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "+60199301339")
        self.assertIn("type=string", out)

    def test_null_exits_1(self):
        code, out = _run(None)
        self.assertEqual(code, 1)

    def test_number_rendered(self):
        code, out = _run(475000)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "475000")
        self.assertIn("type=number", out)

    def test_boolean_rendered_lowercase(self):
        code, out = _run(True)
        self.assertEqual(out.splitlines()[0], "true")
        self.assertIn("type=boolean", out)

    def test_object_rendered_as_json(self):
        code, out = _run({"a": 1})
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], '{"a":1}')
        self.assertIn("type=object", out)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for scripts/dom_query.py expression building.

Covers the pure ``_build_expression`` JS-string builder (no live browser):
  * default expression queries the selector and reads count/visible/text/box
  * ``--attr`` injects attribute-reading JS and is omitted otherwise
"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "web"))

import dom_query  # noqa: E402


class BuildExpressionTests(unittest.TestCase):
    def test_selector_is_json_encoded(self):
        expr = dom_query._build_expression("a[da-id=x]")
        self.assertIn('document.querySelectorAll("a[da-id=x]")', expr)

    def test_default_has_no_attr_branch(self):
        expr = dom_query._build_expression("div")
        self.assertNotIn("getAttribute", expr)
        self.assertIn("count:els.length", expr)
        self.assertIn("out.text", expr)

    def test_attr_injects_getattribute(self):
        expr = dom_query._build_expression("a", attr="href")
        self.assertIn("getAttribute(\"href\")", expr)
        self.assertIn("out.attr", expr)

    def test_attr_name_is_json_encoded(self):
        # An attribute name with a quote must be safely encoded into the JS.
        expr = dom_query._build_expression("a", attr='data-"x"')
        self.assertIn('data-\\"x\\"', expr)


if __name__ == "__main__":
    unittest.main()

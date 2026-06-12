"""Evaluate a JavaScript expression on the active Chrome page over CDP.

Connects to the page target on ``--port``, evaluates ``--expr`` (a JS expression),
and prints the result as the FIRST output line (so a spec can capture it cleanly
via ``$.cols[0]``). Objects/arrays are printed as compact JSON; ``null`` /
``undefined`` results are treated as "no value". A second tab-separated line
``type=<js-type>`` follows for debugging.

This is the read-only sibling of ``dom_query`` (single-element/attribute reads)
and ``dom_get_html`` (bulk content dumps): use it when the value you need is not
addressable as an element/attribute, e.g. a field buried in ``window.__NEXT_DATA__``.

Exit codes:
  0  evaluated to a non-null value (printed)
  1  evaluated to null/undefined (no value)
  2  could not connect to a page target
  3  bad usage / unexpected error
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_client  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--expr", required=True, help="JavaScript expression to evaluate")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--url-contains", dest="url_contains", default=None)
    a = p.parse_args()

    try:
        session = cdp_client.connect_page(a.port, a.url_contains)
    except cdp_client.CDPError as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

    with session:
        value = session.evaluate(a.expr)

    if value is None:
        print(f"FAIL: expression evaluated to null/undefined: {a.expr}",
              file=sys.stderr)
        sys.exit(1)

    if isinstance(value, str):
        rendered = value
        js_type = "string"
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
        js_type = "boolean"
    elif isinstance(value, (int, float)):
        rendered = repr(value) if isinstance(value, float) else str(value)
        js_type = "number"
    else:
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        js_type = "object"

    print(rendered)
    print(f"type={js_type}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(3)

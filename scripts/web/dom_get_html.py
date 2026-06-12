"""Get HTML (or text) content from the active Chrome page over CDP.

Connects to the page target on ``--port`` and returns the ``outerHTML`` of the
whole document, or of the element matched by ``--selector`` (CSS). With
``--text`` it returns ``innerText`` instead. The content is written to ``--out``
(an artifact path) and a summary line ``bytes=<n>\\tpath=<...>`` is printed
(tab-separated) for capture.

Exit codes:
  0  content retrieved and written
  1  --selector matched nothing
  2  could not connect to a page target
  3  bad usage / unexpected error
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_client  # noqa: E402


def _build_expression(selector, as_text):
    prop = "innerText" if as_text else "outerHTML"
    if not selector:
        # Whole document.
        target = "document.documentElement"
        return f"{target} ? {target}.{prop} : null"
    sel = json.dumps(selector)
    return (f"(function(){{var el=document.querySelector({sel});"
            f"return el ? el.{prop} : null;}})()")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--selector", default=None, help="CSS selector (default whole document)")
    p.add_argument("--text", action="store_true", help="return innerText instead of outerHTML")
    p.add_argument("--out", required=True, help="file path to write the content to")
    p.add_argument("--url-contains", dest="url_contains", default=None)
    a = p.parse_args()

    try:
        session = cdp_client.connect_page(a.port, a.url_contains)
    except cdp_client.CDPError as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

    with session:
        content = session.evaluate(_build_expression(a.selector, a.text))

    if content is None:
        print(f"ERROR: selector {a.selector!r} matched no element", file=sys.stderr)
        sys.exit(1)

    out_dir = os.path.dirname(os.path.abspath(a.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    data = content.encode("utf-8")
    with open(a.out, "wb") as f:
        f.write(data)

    print(f"bytes={len(data)}\tpath={a.out}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(3)

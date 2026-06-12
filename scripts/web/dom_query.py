"""Validate where to interact on the active Chrome page (CDP).

Given a CSS ``--selector``, reports how many elements match and, for the first
match, whether it is visible, its trimmed text, and its bounding box. Prints
``count=<n>\\tvisible=<bool>\\tx=<n>\\ty=<n>\\tw=<n>\\th=<n>\\ttext=<...>``
(tab-separated) for capture.

Assertion flags turn it into a gate (exit 1 if not satisfied):
  --expect-min N   require at least N matches
  --visible        require the first match to be visible
  --contains TEXT  require the first match's text to contain TEXT
With no assertion flags it exits 0 when >=1 element matches, else 1.

``--attr NAME`` reads an attribute of the first match (e.g. ``href``) and prints
its raw value as the FIRST output line (so a spec can capture it cleanly via
``$.cols[0]``); the usual ``count=...`` line follows. Exits 1 if no match.

Exit codes:
  0  matched (and all assertions passed)
  1  no match, or an assertion failed
  2  could not connect to a page target
  3  bad usage / unexpected error
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_client  # noqa: E402


def _build_expression(selector, attr=None):
    sel = json.dumps(selector)
    attr_js = ""
    if attr:
        an = json.dumps(attr)
        attr_js = (
            "out.attr=(el.getAttribute&&el.getAttribute(" + an + "));"
            "if(out.attr==null){out.attr=(el[" + an + "]!=null?String(el[" + an + "]):null);}"
        )
    return (
        "(function(){"
        f"var els=document.querySelectorAll({sel});"
        "var out={count:els.length};"
        "if(els.length){var el=els[0];var r=el.getBoundingClientRect();"
        "var cs=getComputedStyle(el);"
        "out.visible=!!(el.offsetParent!==null||cs.position==='fixed')"
        "&&cs.visibility!=='hidden'&&cs.display!=='none'"
        "&&r.width>0&&r.height>0;"
        "out.x=Math.round(r.left);out.y=Math.round(r.top);"
        "out.w=Math.round(r.width);out.h=Math.round(r.height);"
        "out.text=(el.innerText||el.textContent||'').trim();"
        f"{attr_js}"
        "}"
        "return out;})()"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selector", required=True, help="CSS selector to validate")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--url-contains", dest="url_contains", default=None)
    p.add_argument("--expect-min", dest="expect_min", type=int, default=None,
                   help="require at least N matches")
    p.add_argument("--visible", action="store_true",
                   help="require the first match to be visible")
    p.add_argument("--contains", default=None,
                   help="require the first match's text to contain this substring")
    p.add_argument("--attr", default=None,
                   help="read this attribute of the first match and print its raw "
                        "value as the first output line (capture via $.cols[0])")
    a = p.parse_args()

    try:
        session = cdp_client.connect_page(a.port, a.url_contains)
    except cdp_client.CDPError as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

    with session:
        info = session.evaluate(_build_expression(a.selector, a.attr))

    info = info or {}
    count = int(info.get("count", 0))
    visible = bool(info.get("visible", False))
    text = info.get("text", "") or ""
    x, y = info.get("x", 0), info.get("y", 0)
    w, h = info.get("w", 0), info.get("h", 0)
    if a.attr:
        attr_val = info.get("attr")
        if attr_val is None:
            print(f"FAIL: {a.selector!r} has no attribute {a.attr!r} "
                  f"(matched {count})", file=sys.stderr)
            sys.exit(1)
        print(attr_val)
    print(f"count={count}\tvisible={visible}\tx={x}\ty={y}\tw={w}\th={h}\ttext={text}")

    # Determine pass/fail.
    asserted = a.expect_min is not None or a.visible or a.contains is not None
    min_required = a.expect_min if a.expect_min is not None else 1

    if count < min_required:
        print(f"FAIL: matched {count}, expected at least {min_required} for "
              f"{a.selector!r}", file=sys.stderr)
        sys.exit(1)
    if a.visible and not visible:
        print(f"FAIL: {a.selector!r} first match is not visible", file=sys.stderr)
        sys.exit(1)
    if a.contains is not None and a.contains not in text:
        print(f"FAIL: {a.selector!r} text does not contain {a.contains!r} "
              f"(text={text[:120]!r})", file=sys.stderr)
        sys.exit(1)

    _ = asserted  # informational; exit 0 below covers both gated and ungated use


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(3)

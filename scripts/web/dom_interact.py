"""Interact with an element on the active Chrome page over CDP.

Connects to the page target on ``--port``, locates the element matched by
``--selector`` (CSS), and performs ``action``:

  click   - dispatch trusted mouse press/release at the element's center
  type    - focus the element and insert --value (appends)
  set     - focus, select existing content, then insert --value (replaces)
  press   - dispatch a key event for --value (e.g. Enter, Tab, Escape)
  select  - set a <select>'s value to --value and fire a change event

Interaction uses CDP ``Input.dispatch*`` (trusted events) rather than JS click,
for realism and lower detectability. Prints ``ok action=<a> selector=<s>``.

Exit codes:
  0  action performed
  1  --selector matched nothing / element not interactable
  2  could not connect to a page target
  3  bad usage / unexpected error
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_client  # noqa: E402

# Minimal name -> CDP key descriptor map for the `press` action.
_KEYS = {
    "enter": {"key": "Enter", "code": "Enter", "vk": 13, "text": "\r"},
    "tab": {"key": "Tab", "code": "Tab", "vk": 9},
    "escape": {"key": "Escape", "code": "Escape", "vk": 27},
    "esc": {"key": "Escape", "code": "Escape", "vk": 27},
    "backspace": {"key": "Backspace", "code": "Backspace", "vk": 8},
    "delete": {"key": "Delete", "code": "Delete", "vk": 46},
    "space": {"key": " ", "code": "Space", "vk": 32, "text": " "},
    "arrowdown": {"key": "ArrowDown", "code": "ArrowDown", "vk": 40},
    "arrowup": {"key": "ArrowUp", "code": "ArrowUp", "vk": 38},
    "arrowleft": {"key": "ArrowLeft", "code": "ArrowLeft", "vk": 37},
    "arrowright": {"key": "ArrowRight", "code": "ArrowRight", "vk": 39},
}


def _center_expr(selector):
    """JS returning {found, cx, cy} after scrolling the element into view."""
    sel = json.dumps(selector)
    return (
        "(function(){"
        f"var el=document.querySelector({sel});"
        "if(!el){return {found:false};}"
        "el.scrollIntoView({block:'center',inline:'center'});"
        "var r=el.getBoundingClientRect();"
        "return {found:true,cx:r.left+r.width/2,cy:r.top+r.height/2};})()"
    )


def _focus_expr(selector, select_all):
    sel = json.dumps(selector)
    extra = "if(el.select){el.select();}" if select_all else ""
    return (
        "(function(){"
        f"var el=document.querySelector({sel});"
        "if(!el){return false;}el.focus();"
        f"{extra}return true;}})()"
    )


def _select_expr(selector, value):
    sel = json.dumps(selector)
    val = json.dumps(value)
    return (
        "(function(){"
        f"var el=document.querySelector({sel});"
        "if(!el){return false;}"
        f"el.value={val};"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        "return true;})()"
    )


def _mouse(session, kind, x, y):
    session.send("Input.dispatchMouseEvent", {
        "type": kind, "x": x, "y": y, "button": "left", "clickCount": 1,
    })


def _do_click(session, selector):
    info = session.evaluate(_center_expr(selector)) or {}
    if not info.get("found"):
        return False
    x, y = info["cx"], info["cy"]
    _mouse(session, "mouseMoved", x, y)
    _mouse(session, "mousePressed", x, y)
    _mouse(session, "mouseReleased", x, y)
    return True


def _do_type(session, selector, value, replace):
    if not session.evaluate(_focus_expr(selector, select_all=replace)):
        return False
    session.send("Input.insertText", {"text": value})
    return True


def _do_press(session, value):
    desc = _KEYS.get(value.lower())
    if not desc:
        raise cdp_client.CDPError(
            f"unsupported key {value!r}; known: {', '.join(sorted(_KEYS))}")
    base = {"key": desc["key"], "code": desc["code"],
            "windowsVirtualKeyCode": desc["vk"], "nativeVirtualKeyCode": desc["vk"]}
    down = dict(base, type="keyDown")
    if "text" in desc:
        down["text"] = desc["text"]
    session.send("Input.dispatchKeyEvent", down)
    session.send("Input.dispatchKeyEvent", dict(base, type="keyUp"))
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["click", "type", "set", "press", "select"])
    p.add_argument("--selector", help="CSS selector (not required for press)")
    p.add_argument("--value", default="", help="text/key/option value for the action")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--url-contains", dest="url_contains", default=None)
    p.add_argument("--optional", action="store_true",
                   help="if the selector matches no element, exit 0 (no-op) "
                        "instead of failing; useful for elements that may be "
                        "absent (e.g. a cookie banner already dismissed)")
    a = p.parse_args()

    if a.action != "press" and not a.selector:
        print(f"ERROR: action {a.action!r} requires --selector", file=sys.stderr)
        sys.exit(3)

    try:
        session = cdp_client.connect_page(a.port, a.url_contains)
    except cdp_client.CDPError as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

    try:
        with session:
            if a.action == "click":
                ok = _do_click(session, a.selector)
            elif a.action == "type":
                ok = _do_type(session, a.selector, a.value, replace=False)
            elif a.action == "set":
                ok = _do_type(session, a.selector, a.value, replace=True)
            elif a.action == "select":
                ok = bool(session.evaluate(_select_expr(a.selector, a.value)))
            else:  # press
                ok = _do_press(session, a.value)
    except cdp_client.CDPError as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

    if not ok:
        if a.optional:
            print(f"ok action={a.action} selector={a.selector!r} "
                  f"(optional: no element, skipped)")
            return
        print(f"ERROR: selector {a.selector!r} matched no element", file=sys.stderr)
        sys.exit(1)

    print(f"ok action={a.action} selector={a.selector!r}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(3)

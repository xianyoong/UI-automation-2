"""Dump a depth-bounded UIA subtree as JSON.

Walks a window's UIA tree breadth-first up to --max-depth and prints a JSON
array of nodes. Each node carries name / auto_id / control_type / class /
rect / depth / children. Filters are applied before recursion, so a matching
parent still emits its (filtered) descendants.
"""
import argparse, json, re, sys
from pywinauto import Application

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def serialise(elem, depth, max_depth, name_rx, type_rx):
    name = _safe(elem.window_text, "") or ""
    auto_id = _safe(elem.automation_id, "") or ""
    ctype = _safe(lambda: elem.element_info.control_type, "") or ""
    cls = _safe(elem.class_name, "") or ""
    r = _safe(elem.rectangle)
    rect = [r.left, r.top, r.right, r.bottom] if r else None

    node = {
        "name": name,
        "auto_id": auto_id,
        "control_type": ctype,
        "class": cls,
        "rect": rect,
        "depth": depth,
        "children": [],
    }

    if depth >= max_depth:
        return node

    for child in _safe(elem.children, []) or []:
        sub = serialise(child, depth + 1, max_depth, name_rx, type_rx)
        if name_rx and not name_rx.search(sub["name"]):
            if not sub["children"]:
                continue
        if type_rx and not type_rx.search(sub["control_type"]):
            if not sub["children"]:
                continue
        node["children"].append(sub)
    return node


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("hwnd", type=lambda s: int(s, 0),
                   help="root window handle (decimal or 0x-hex)")
    p.add_argument("--max-depth", dest="max_depth", type=int, default=3,
                   help="hard cap on recursion depth (default 3)")
    p.add_argument("--filter-name", dest="filter_name", default=None,
                   help="regex applied to .name; non-matching leaves are dropped")
    p.add_argument("--filter-type", dest="filter_type", default=None,
                   help="regex applied to .control_type; non-matching leaves are dropped")
    p.add_argument("--backend", choices=["uia", "win32"], default="uia")
    p.add_argument("--compact", action="store_true",
                   help="print JSON without indentation")
    a = p.parse_args()

    if a.max_depth < 0:
        print("ERROR: --max-depth must be >= 0", file=sys.stderr); sys.exit(2)

    name_rx = re.compile(a.filter_name) if a.filter_name else None
    type_rx = re.compile(a.filter_type) if a.filter_type else None

    app = Application(backend=a.backend).connect(handle=a.hwnd)
    win = app.window(handle=a.hwnd)
    root = serialise(win, 0, a.max_depth, name_rx, type_rx)

    if a.compact:
        print(json.dumps(root, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(root, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

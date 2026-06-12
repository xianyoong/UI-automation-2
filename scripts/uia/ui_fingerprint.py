"""Print a short hash representing the current foreground UI state.

The fingerprint is built from deterministic fields joined with ``\x1f``: the
foreground window title, class name, process name, optional rectangle, and up to
50 direct UIA children sorted by screen position, each represented by control
type, name, automation id, and class name.
"""
import argparse, ctypes, ctypes.wintypes, hashlib, os, sys
from pywinauto import Application

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Make this process DPI-aware so pywinauto rects match the rest of the toolkit.
# Per-monitor v2 (value 2) is the modern setting.
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

SEP = "\x1f"
MAX_CHILDREN = 50


def _clean(value):
    return "" if value is None else str(value).replace(SEP, " ")


def _process_name(pid):
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        raise OSError(f"unable to open process {pid} for querying")
    try:
        size = ctypes.wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            raise OSError(f"unable to query process image name for pid {pid}")
        return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)


def _rect_fields(rect):
    return [rect.left, rect.top, rect.right, rect.bottom]


def _element_fields(wrapper):
    info = wrapper.element_info
    return [info.control_type or "", info.name or "", info.automation_id or "", info.class_name or ""]


def build_fields(include_rect=True):
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        raise RuntimeError("no foreground window")

    app = Application(backend="uia").connect(handle=hwnd)
    win = app.window(handle=hwnd)
    info = win.element_info
    rect = win.rectangle()
    pid = win.process_id()

    fields = [
        "window",
        info.name or win.window_text() or "",
        info.class_name or win.class_name() or "",
        _process_name(pid),
    ]
    if include_rect:
        fields.extend(_rect_fields(rect))

    children = []
    for child in win.children():
        child_rect = child.rectangle()
        children.append((child_rect.top, child_rect.left, _element_fields(child)))

    for _, _, child_fields in sorted(children, key=lambda item: (item[0], item[1]))[:MAX_CHILDREN]:
        fields.append("child")
        fields.extend(child_fields)

    return [_clean(field) for field in fields]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verbose", action="store_true", help="Print hash input fields to stderr.")
    p.add_argument("--include-rect", dest="include_rect", action=argparse.BooleanOptionalAction, default=True,
                   help="Include foreground window rectangle in the fingerprint (default: enabled).")
    a = p.parse_args()

    fields = build_fields(include_rect=a.include_rect)
    raw = SEP.join(fields)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    if a.verbose:
        for i, field in enumerate(fields):
            print(f"field[{i}]={field}", file=sys.stderr)
    print(digest)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

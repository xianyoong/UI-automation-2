"""Maximize a window by hwnd; skip (no-op) if it is already maximized.

Restores the window first if it is minimised, then maximises it. If the window
is already maximised, nothing is changed and `already maximized hwnd=<n> ...` is
printed. Prints `maximized hwnd=<n> title=<...>` on a successful maximise.
Exits 1 if the hwnd does not exist.
"""
import argparse, sys, time
from pywinauto import Application
from pywinauto.findwindows import ElementNotFoundError


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("hwnd", type=lambda s: int(s, 0),
                   help="window handle (decimal or 0x-hex)")
    p.add_argument("--backend", choices=["uia", "win32"], default="uia")
    p.add_argument("--settle-ms", dest="settle_ms", type=int, default=100,
                   help="sleep after maximizing so the window can finish animating (default 100)")
    a = p.parse_args()

    try:
        app = Application(backend=a.backend).connect(handle=a.hwnd)
        win = app.window(handle=a.hwnd)
        if not win.exists(timeout=0.5):
            print(f"ERROR: hwnd {a.hwnd} not found", file=sys.stderr); sys.exit(1)
        if win.is_minimized():
            win.restore()
        if win.is_maximized():
            title = _title(win)
            print(f"already maximized hwnd={a.hwnd} title={title!r}")
            return
        win.maximize()
    except ElementNotFoundError:
        print(f"ERROR: hwnd {a.hwnd} not found", file=sys.stderr); sys.exit(1)
    except Exception as e:
        print(f"ERROR: could not maximize hwnd {a.hwnd}: {e}", file=sys.stderr); sys.exit(1)

    if a.settle_ms > 0:
        time.sleep(a.settle_ms / 1000.0)

    print(f"maximized hwnd={a.hwnd} title={_title(win)!r}")


def _title(win):
    try:
        return win.window_text() or ""
    except Exception:
        return ""


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

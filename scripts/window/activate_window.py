"""Bring a window to the foreground (raise + focus).

Restores the window if it is minimised, then calls SetForegroundWindow via
pywinauto's set_focus(). Prints `activated hwnd=<n> title=<...>` on success.
Exits 1 if the hwnd does not exist or Windows refuses to foreground it.
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
                   help="sleep after raising so the window can finish animating (default 100)")
    a = p.parse_args()

    try:
        app = Application(backend=a.backend).connect(handle=a.hwnd)
        win = app.window(handle=a.hwnd)
        if not win.exists(timeout=0.5):
            print(f"ERROR: hwnd {a.hwnd} not found", file=sys.stderr); sys.exit(1)
        if win.is_minimized():
            win.restore()
        win.set_focus()
    except ElementNotFoundError:
        print(f"ERROR: hwnd {a.hwnd} not found", file=sys.stderr); sys.exit(1)
    except Exception as e:
        print(f"ERROR: could not activate hwnd {a.hwnd}: {e}", file=sys.stderr); sys.exit(1)

    if a.settle_ms > 0:
        time.sleep(a.settle_ms / 1000.0)

    title = ""
    try:
        title = win.window_text() or ""
    except Exception:
        pass
    print(f"activated hwnd={a.hwnd} title={title!r}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

"""Type a literal text string into the focused window."""
import argparse, sys
import pyautogui

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("text")
    p.add_argument("--interval", type=float, default=0.02)
    a = p.parse_args()
    pyautogui.typewrite(a.text, interval=a.interval)
    print(f"typed {len(a.text)} chars")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

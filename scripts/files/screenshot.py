"""Capture a screenshot (full screen or region) to a PNG file."""
import argparse, os, sys
import pyautogui

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("out_path")
    p.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    a = p.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out_path)), exist_ok=True)
    img = pyautogui.screenshot(region=tuple(a.region) if a.region else None)
    img.save(a.out_path)
    print(a.out_path)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

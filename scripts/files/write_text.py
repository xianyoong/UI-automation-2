"""Create / write a UTF-8 text file and print its absolute path.

Writes ``--text`` (default empty string) to ``--out``, creating any missing
parent directories first. ``\\n`` escapes in ``--text`` are turned into real
newlines. With ``--append`` the text is appended instead of overwriting.

Prints the file's **absolute path** as the FIRST output line (so a spec can
capture it via ``$.cols[0]``), then a tab-separated ``bytes=<n>`` line.

A common use is to pre-create an empty target file so a GUI editor (e.g. Notepad)
can open it *path-bound* and save with Ctrl+S, with no Save-As dialog to drive.

Exit codes:
  0  written
  3  bad usage / unexpected error
"""
import argparse
import os
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="file path to write")
    p.add_argument("--text", default="", help="text content (\\n becomes newline)")
    p.add_argument("--append", action="store_true",
                   help="append to the file instead of overwriting")
    a = p.parse_args()

    out = os.path.abspath(a.out)
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    content = a.text.replace("\\n", "\n")
    data = content.encode("utf-8")
    mode = "ab" if a.append else "wb"
    with open(out, mode) as f:
        f.write(data)

    size = os.path.getsize(out)
    print(out)
    print(f"bytes={size}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(3)

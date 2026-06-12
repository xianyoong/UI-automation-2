"""Assert a file exists (exit 0) or not (with --negate); supports env-var paths.

Optional --delete removes the file first (used for pre-test cleanup) and
always exits 0 regardless of whether the file existed.
"""
import argparse, os, sys

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path")
    p.add_argument("--delete", action="store_true",
                   help="Remove the file if present, then exit 0.")
    p.add_argument("--negate", action="store_true",
                   help="Exit 0 only if the file does NOT exist.")
    p.add_argument("--contains", default=None,
                   help="If set, also assert the file contents include this substring.")
    a = p.parse_args()
    resolved = os.path.expandvars(os.path.expanduser(a.path))

    if a.delete:
        try:
            os.remove(resolved)
            print(f"deleted {resolved}")
        except FileNotFoundError:
            print(f"absent (nothing to delete) {resolved}")
        return

    exists = os.path.isfile(resolved)
    size = os.path.getsize(resolved) if exists else 0
    print(f"path\texists\tsize_bytes\n{resolved}\t{exists}\t{size}")
    want_exists = not a.negate
    if exists != want_exists:
        sys.exit(1)
    if a.contains is not None and exists:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        if a.contains not in data:
            print(f"ERROR: file does not contain {a.contains!r}; got {data!r}", file=sys.stderr)
            sys.exit(1)
        print(f"contains\t{a.contains!r}\tOK")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

"""Poll find_window.py or find_control.py until it succeeds or the timeout expires.

On success, stdout is whatever the wrapped helper printed (so `capture:` rules
in YAML work identically to a direct call). On timeout, exits 1 with a message
on stderr and the last failure output.
"""
import argparse, os, subprocess, sys, time

PY = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["window", "control"], required=True,
                   help="which helper to poll: find_window.py or find_control.py")
    p.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=5000)
    p.add_argument("--poll-ms", dest="poll_ms", type=int, default=250)
    p.add_argument("forward", nargs=argparse.REMAINDER,
                   help="args forwarded to the wrapped helper; place after `--`")
    a = p.parse_args()

    args = a.forward
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("ERROR: no forwarded args; usage: wait_for.py --mode <m> -- <helper args>",
              file=sys.stderr); sys.exit(2)

    script = ("window", "find_window.py") if a.mode == "window" else ("uia", "find_control.py")
    cmd = [PY, os.path.join(_REPO_ROOT, "scripts", *script)] + args

    deadline = time.time() + a.timeout_ms / 1000.0
    interval = max(a.poll_ms, 0) / 1000.0
    attempts = 0
    last_stderr = ""
    last_stdout = ""

    while True:
        attempts += 1
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        last_stderr = r.stderr
        last_stdout = r.stdout
        if r.returncode == 0 and r.stdout.strip():
            sys.stdout.write(r.stdout)
            sys.stdout.flush()
            return
        if time.time() >= deadline:
            print(f"timeout: {a.mode} not found after {a.timeout_ms}ms "
                  f"({attempts} attempt{'s' if attempts != 1 else ''}); "
                  f"last stderr: {last_stderr.strip()[:200]!r}",
                  file=sys.stderr)
            if last_stdout.strip():
                print(f"last stdout: {last_stdout.strip()[:200]!r}", file=sys.stderr)
            sys.exit(1)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

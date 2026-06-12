"""Execute a declarative UI-automation test spec (YAML).

Usage:
    python run_test.py <spec.yaml>

Exit codes:
    0  all steps passed
    1  one or more assertions failed
    2  runner error (bad spec, script missing, etc.)
"""
import argparse, datetime, json, os, re, subprocess, sys, time
import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Make this process (and the child scripts it spawns) DPI-aware so
# pyautogui virtual-pixel clicks align with pywinauto physical-pixel rects
# on HiDPI displays. Per-monitor v2 (value 2) is the modern setting.
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
QUIET = False


class Ctx:
    def __init__(self, spec):
        self.spec = spec
        self.vars = {}
        self.iter_failed = {}   # n -> bool, used by snapshot step
        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")
        self.subs = {
            "timestamp": ts,
            "inputs": spec.get("inputs", {}),
            "artifacts": spec.get("artifacts", {}),
            "vars": self.vars,
        }
        # pre-resolve artifacts paths
        art = spec.get("artifacts", {})
        self.subs["artifacts"] = {
            k: render(v, self.subs) for k, v in art.items()
        }
        self.shot_dir = os.path.join(ROOT, self.subs["artifacts"].get("screenshot_dir", "screenshots/run"))
        os.makedirs(self.shot_dir, exist_ok=True)
        self.timestamp = ts
        self.step_results = []
        self.started_at = datetime.datetime.utcnow()


_expr_re = re.compile(r"\{([^{}]+)\}")


def lookup(path, subs):
    cur = subs
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
        if cur is None:
            return ""
    return cur


def render(value, subs):
    """Render {placeholders} and {a + b} arithmetic on ints."""
    if isinstance(value, list):
        return [render(v, subs) for v in value]
    if isinstance(value, dict):
        return {k: render(v, subs) for k, v in value.items()}
    if not isinstance(value, str):
        return value

    def repl(m):
        expr = m.group(1).strip()
        # simple integer arithmetic: "vars.win_left + 100"
        if any(op in expr for op in "+-*/"):
            tokens = re.split(r"(\s*[+\-*/]\s*)", expr)
            try:
                parts = []
                for tok in tokens:
                    tok_s = tok.strip()
                    if tok_s in {"+", "-", "*", "/"}:
                        parts.append(tok_s)
                    elif re.fullmatch(r"-?\d+", tok_s):
                        parts.append(tok_s)
                    else:
                        v = lookup(tok_s, subs)
                        parts.append(str(int(v)))
                return str(eval(" ".join(parts), {"__builtins__": {}}, {}))
            except Exception:
                pass
        return str(lookup(expr, subs))

    return _expr_re.sub(repl, value)


def run_cmd(script, args, expect_exit=0):
    cmd = [PY, os.path.join(ROOT, script)] + [str(a) for a in args]
    if not QUIET:
        print(f"  $ {' '.join(cmd)}")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    failed = p.returncode != expect_exit
    if p.stdout and (failed or not QUIET):
        for line in p.stdout.rstrip().splitlines():
            print(f"    | {line}")
    if p.stderr:
        for line in p.stderr.rstrip().splitlines():
            print(f"    ! {line}")
    if failed:
        raise AssertionError(f"exit {p.returncode}, expected {expect_exit}")
    return p


def capture(out_text, mapping, ctx):
    """Apply $.cols[i] / $.rows[j].cols[i] selectors to tab-separated output."""
    lines = [l for l in out_text.splitlines() if l.strip()]
    rows = [l.split("\t") for l in lines]
    first_cols = rows[0] if rows else []
    for dst, sel in mapping.items():
        m = re.fullmatch(r"\$\.cols\[(\d+)\]", sel)
        if m:
            val = first_cols[int(m.group(1))]
        else:
            m = re.fullmatch(r"\$\.rows\[(\d+)\]\.cols\[(\d+)\]", sel)
            if m:
                val = rows[int(m.group(1))][int(m.group(2))]
            else:
                raise ValueError(f"bad selector: {sel}")
        if dst.startswith("vars."):
            ctx.vars[dst[5:]] = val
        else:
            raise ValueError(f"capture dst must start with vars.: {dst}")


def get_wait(ctx, name):
    if not name:
        return 0
    val = ctx.spec.get("timing", {}).get(name, 0)
    return int(val) / 1000.0


def exec_step(step, ctx, local_subs):
    subs = dict(ctx.subs); subs.update(local_subs)
    t = step["type"]
    desc = step.get("description", "")
    if not QUIET:
        print(f"\n[{step.get('id','?')}] ({t}) {desc.strip().splitlines()[0] if desc else ''}")

    if t == "foreach":
        items = lookup(step["items"], subs)
        var = step["var"]; idx_var = step.get("index_var", "i")
        body = step["body"]
        for i, item in enumerate(items, start=1):
            if not QUIET:
                print(f"\n--- iter {i}: {var}={item!r} ---")
            local = {var: item, idx_var: i}
            ctx.iter_failed[i] = False
            for sub in body:
                try:
                    exec_step(sub, ctx, {**local_subs, **local})
                except AssertionError as e:
                    print(f"    FAIL: {e}")
                    ctx.iter_failed[i] = True
                    if sub["type"] != "screenshot":
                        # try to take the FAIL snapshot before bubbling
                        pass
                    raise
        return

    script = step.get("script")
    raw_args = step.get("args") or step.get("args_expr") or []
    args = [render(a, subs) for a in raw_args]
    expect_exit = step.get("expect_exit", 0)

    if t == "assert_console_contains":
        target = render(step["expected_contains_expr"], subs)
        total = get_wait(ctx, step.get("poll_total_ms")) or 3.0
        interval = get_wait(ctx, step.get("poll_interval_ms")) or 0.2
        deadline = time.time() + total
        last = ""
        while time.time() < deadline:
            p = subprocess.run([PY, os.path.join(ROOT, script)] + args,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            last = p.stdout
            if target in last:
                if not QUIET:
                    print(f"    matched: {target!r}")
                return
            time.sleep(interval)
        raise AssertionError(f"console did not contain {target!r}; last={last[:200]!r}")

    if t == "screenshot":
        n = local_subs.get("n", 0)
        failed = ctx.iter_failed.get(n, False)
        key = "args_expr_on_fail" if failed else "args_expr_on_pass"
        raw = step.get(key) or step.get("args_expr") or step.get("args")
        args = [render(a, subs) for a in raw]
        run_cmd(script, args, expect_exit=0)
        return

    p = run_cmd(script, args, expect_exit=expect_exit)
    if "capture" in step:
        capture(p.stdout, step["capture"], ctx)
    wait = get_wait(ctx, step.get("wait_after"))
    if wait:
        time.sleep(wait)


def main():
    global QUIET
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="suppress per-step headers and successful stdout echo")
    a = ap.parse_args()
    QUIET = a.quiet
    with open(a.spec, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    ctx = Ctx(spec)
    print(f"=== {spec.get('name')} ===")
    print(f"screenshot_dir: {ctx.shot_dir}")
    failed = False
    failed_id = None
    failed_msg = None
    for step in spec["steps"]:
        sid = step.get("id", "?")
        stype = step.get("type", "")
        sdesc = (step.get("description") or "").strip().splitlines()[0] if step.get("description") else ""
        t0 = time.time()
        try:
            exec_step(step, ctx, {})
            ctx.step_results.append({
                "id": sid, "type": stype, "description": sdesc,
                "status": "pass", "duration_s": round(time.time() - t0, 3),
                "error": None,
            })
        except AssertionError as e:
            ctx.step_results.append({
                "id": sid, "type": stype, "description": sdesc,
                "status": "fail", "duration_s": round(time.time() - t0, 3),
                "error": str(e),
            })
            print(f"\n*** STEP FAILED: {sid}: {e}")
            failed = True
            failed_id = sid
            failed_msg = str(e)
            break
    write_result(a.spec, spec, ctx, "FAIL" if failed else "PASS", failed_id, failed_msg)
    print("\n=== RESULT:", "FAIL" if failed else "PASS", "===")
    sys.exit(1 if failed else 0)


def write_result(spec_path, spec, ctx, result, failed_id, failed_msg):
    finished_at = datetime.datetime.utcnow()
    rec = {
        "spec": os.path.relpath(os.path.abspath(spec_path), ROOT).replace("\\", "/"),
        "name": spec.get("name", os.path.basename(spec_path)),
        "description": spec.get("description", ""),
        "started_at": ctx.started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at": finished_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_s": round((finished_at - ctx.started_at).total_seconds(), 3),
        "result": result,
        "failed_step_id": failed_id,
        "failed_step_error": failed_msg,
        "screenshot_dir": os.path.relpath(ctx.shot_dir, ROOT).replace("\\", "/"),
        "steps": ctx.step_results,
        "total_steps": len(spec.get("steps", [])),
    }
    out_dir = os.path.join(ROOT, "results")
    os.makedirs(out_dir, exist_ok=True)
    spec_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_",
                       os.path.splitext(os.path.basename(spec_path))[0])
    out_path = os.path.join(out_dir, f"{ctx.timestamp}__{spec_slug}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2)
        if not QUIET:
            print(f"result: {os.path.relpath(out_path, ROOT)}")
    except Exception as e:
        print(f"WARN: could not write result file: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"RUNNER ERROR: {e}", file=sys.stderr)
        sys.exit(2)

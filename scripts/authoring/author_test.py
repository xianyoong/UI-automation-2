"""Interactive REPL for authoring UI automation test-case YAML.

This tool builds a runnable YAML spec one compact step line at a time. Each
parsed step is executed live via the same engine ``run_test.py`` uses, so
captured variables (window hwnds, control coordinates, ...) accumulate in
``vars`` as you author and become available to later steps.
"""
import argparse
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from typing import Optional

import yaml

try:
    from prompt_toolkit import prompt as pt_prompt
except Exception:  # pragma: no cover - optional dependency
    pt_prompt = None

# Make run_test importable so the live executor can reuse its expression
# rendering and capture helpers.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
import run_test  # noqa: E402  (sys.path adjusted above)

EXECUTOR_TIMEOUT_S = 30

HELP = """
Interactive test authoring
--------------------------
Commands:
  multi   enter block mode; one step per line, end with blank line or ---
  save    write the YAML spec to the output path
  quit    exit, confirming if there are unsaved changes

Step grammar examples:
  click "Close" type=Button auto_id=CloseButton parent=win_hwnd
  click 100 200
  type "hello from copilot"
  type_expr "echo {text}"
  key ctrl+s
  find_window "^Untitled - Notepad$" class=Notepad backend=any nth=1 as=win
  find_control parent=win_hwnd name="Close" auto_id=CloseButton type=Button as=close
  assert_file %TEMP%\\out.txt contains "hello" negate delete
  wait 500
  screenshot "after_launch.png"

Selector tips:
  Provide both auto_id=... and a name when possible. The emitted YAML will
  include --name-fallback, so the runtime tries AutomationId first and falls
  back to Name if the AutomationId changes between app builds.
""".strip()

SPEC_KEY_ORDER = [
    "name",
    "description",
    "inputs",
    "artifacts",
    "timing",
    "steps",
    "expected_results",
]

SCRIPT_BY_TYPE = {
    "key": "scripts/input/key.py",
    "type_text": "scripts/input/type_text.py",
    "click": "scripts/input/click.py",
    "find_window": "scripts/window/find_window.py",
    "find_control": "scripts/uia/find_control.py",
    "assert_file": "scripts/files/assert_file_exists.py",
    "screenshot": "scripts/files/screenshot.py",
    "maximize_window": "scripts/window/maximize_window.py",
}


class StepParseError(ValueError):
    """Raised when a compact step line cannot be parsed."""


_FINGERPRINT_STEP_TYPES = frozenset({"click", "key", "type_text"})
_FINGERPRINT_TIMEOUT_S = 5


class RecurrenceDetector:
    """Detect a stuck UI by tracking the last N fingerprints."""

    WINDOW_SIZE = 3

    def __init__(self) -> None:
        self.recent: list[str] = []

    def observe(self, step: dict, ui_hash: Optional[str]) -> Optional[str]:
        """Record ``ui_hash``; return it when the last WINDOW_SIZE all match."""
        if not ui_hash:
            return None
        self.recent.append(ui_hash)
        if len(self.recent) > self.WINDOW_SIZE:
            self.recent.pop(0)
        if (len(self.recent) == self.WINDOW_SIZE
                and len(set(self.recent)) == 1):
            return ui_hash
        return None

    def reset(self) -> None:
        self.recent.clear()


class RecurrenceHalt(Exception):
    """Raised when the same UI fingerprint is observed WINDOW_SIZE times."""

    def __init__(self, ui_hash: str):
        super().__init__(f"UI fingerprint {ui_hash} seen "
                         f"{RecurrenceDetector.WINDOW_SIZE} times in a row")
        self.ui_hash = ui_hash


def _capture_ui_fingerprint() -> Optional[str]:
    """Run ``scripts/ui_fingerprint.py`` and return the digest, or ``None``."""
    script = os.path.join(_REPO_ROOT, "scripts", "uia", "ui_fingerprint.py")
    if not os.path.exists(script):
        return None
    try:
        proc = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_FINGERPRINT_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


class AmbiguousMatch(Exception):
    """Raised when a find_control selector matches more than one control."""

    def __init__(self, matches: list[list[str]]):
        super().__init__(f"{len(matches)} matches")
        self.matches = matches


def execute_step(step: dict, vars_dict: dict, spec: dict) -> tuple[bool, str]:
    """Run ``step`` live via subprocess, applying captures into ``vars_dict``.

    Returns (ok, message). Steps without a ``script`` field (e.g. internal
    ``_wait``) succeed as a no-op.
    """
    step_type = step.get("type")
    if not step_type or step_type.startswith("_"):
        return True, "skipped (no-op step)"
    script = step.get("script")
    if not script:
        return True, f"skipped (no script for type {step_type!r})"

    subs = {
        "vars": vars_dict,
        "inputs": spec.get("inputs", {}) or {},
        "artifacts": spec.get("artifacts", {}) or {},
        "timestamp": "author",
    }

    if step_type == "screenshot":
        raw_args = (step.get("args_expr_on_pass")
                    or step.get("args_expr")
                    or step.get("args")
                    or [])
    else:
        raw_args = step.get("args") or step.get("args_expr") or []

    try:
        args = [run_test.render(a, subs) for a in raw_args]
    except Exception as exc:
        return False, f"failed to render args: {exc}"

    expect_exit = int(step.get("expect_exit", 0))
    cmd = [sys.executable, os.path.join(_REPO_ROOT, script)] + [str(a) for a in args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=EXECUTOR_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout after {EXECUTOR_TIMEOUT_S}s running {script}"
    except OSError as exc:
        return False, f"failed to spawn {script}: {exc}"

    if proc.returncode != expect_exit:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = stderr[-1] if stderr else ""
        return False, (f"exit {proc.returncode}, expected {expect_exit}"
                       + (f"; stderr: {tail}" if tail else ""))

    if "capture" in step:
        try:
            _apply_capture(proc.stdout, step["capture"], vars_dict)
        except Exception as exc:
            return False, f"capture failed: {exc}"

    return True, f"ok ({len(proc.stdout)} bytes stdout)"


def _apply_capture(out_text: str, mapping: dict, vars_dict: dict) -> None:
    """Apply ``$.cols[i]`` / ``$.rows[j].cols[i]`` selectors to TSV output."""
    lines = [l for l in out_text.splitlines() if l.strip()]
    rows = [l.split("\t") for l in lines]
    first_cols = rows[0] if rows else []
    for dst, sel in mapping.items():
        m = re.fullmatch(r"\$\.cols\[(\d+)\]", sel)
        if m:
            idx = int(m.group(1))
            if idx >= len(first_cols):
                raise ValueError(f"selector {sel!r} out of range (have {len(first_cols)} cols)")
            val = first_cols[idx]
        else:
            m = re.fullmatch(r"\$\.rows\[(\d+)\]\.cols\[(\d+)\]", sel)
            if not m:
                raise ValueError(f"bad selector: {sel}")
            r_idx, c_idx = int(m.group(1)), int(m.group(2))
            if r_idx >= len(rows) or c_idx >= len(rows[r_idx]):
                raise ValueError(f"selector {sel!r} out of range "
                                 f"(have {len(rows)} rows)")
            val = rows[r_idx][c_idx]
        if not dst.startswith("vars."):
            raise ValueError(f"capture dst must start with vars.: {dst}")
        vars_dict[dst[5:]] = val


def maybe_disambiguate(step: dict, vars_dict: dict, spec: dict) -> dict:
    """Probe ``find_control`` steps for ambiguity; raise ``AmbiguousMatch`` if >1.

    For non-find_control steps this is a no-op and returns ``step`` unchanged.
    The probe runs the same script with ``--all`` forced (and ``--nth``/``--all``
    stripped from the original args) so we get the full match set under the
    user's filters. If any args fail to render, we silently skip probing.
    """
    if step.get("type") != "find_control":
        return step
    script = step.get("script")
    if not script:
        return step

    raw_args = step.get("args") or step.get("args_expr") or []
    subs = {
        "vars": vars_dict,
        "inputs": spec.get("inputs", {}) or {},
        "artifacts": spec.get("artifacts", {}) or {},
        "timestamp": "author",
    }
    try:
        rendered = [run_test.render(a, subs) for a in raw_args]
    except Exception:
        return step

    cleaned: list[str] = []
    skip_next = False
    for tok in rendered:
        if skip_next:
            skip_next = False
            continue
        s = str(tok)
        if s == "--all":
            continue
        if s == "--nth":
            skip_next = True
            continue
        cleaned.append(s)
    cleaned.append("--all")

    cmd = [sys.executable, os.path.join(_REPO_ROOT, script)] + [str(a) for a in cleaned]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=EXECUTOR_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return step

    if proc.returncode != 0:
        return step

    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    rows = [l.split("\t") for l in lines[1:]]
    if len(rows) > 1:
        raise AmbiguousMatch(rows)
    return step


def _print_ambiguous_matches(matches: list[list[str]]) -> None:
    """Pretty-print a list of find_control match rows for the REPL."""
    print(f"AMBIGUOUS: selector matched {len(matches)} controls:")
    for i, row in enumerate(matches, start=1):
        if len(row) >= 9:
            name, auto_id, ctype, left, top, right, bottom = row[:7]
            print(f"  [{i}] name={name!r} auto_id={auto_id!r} type={ctype!r} "
                  f"rect=({left},{top},{right},{bottom})")
        else:
            print(f"  [{i}] {row}")
    print("Re-enter the step with a more specific selector "
          "(add auto_id=, type=, class=, or nth=).")


def _prompt_recurrence_action(ui_hash: str) -> str:
    """Ask the author what to do after a recurrence halt. Returns one of:
    ``keep``, ``discard``, ``abort``. Defaults to ``keep`` on EOF / blank input.
    """
    print(f"\nRECURRENCE: the UI has not changed for "
          f"{RecurrenceDetector.WINDOW_SIZE} consecutive acting steps "
          f"(fingerprint {ui_hash}).")
    print("  [k]eep    — accept this step and continue authoring")
    print("  [d]iscard — drop this step and try a different one")
    print("  [a]bort   — discard the current batch of steps")
    while True:
        try:
            ans = _prompt("recurrence> ").strip().lower()
        except EOFError:
            return "keep"
        if not ans or ans in {"k", "keep"}:
            return "keep"
        if ans in {"d", "discard", "skip", "s"}:
            return "discard"
        if ans in {"a", "abort"}:
            return "abort"
        print("Please answer k, d, or a.")


def _prompt(text: str) -> str:
    if pt_prompt is not None and sys.stdin.isatty() and sys.stdout.isatty():
        return pt_prompt(text)
    return input(text)


def _parse_kv_tokens(tokens: list[str]) -> dict[str, str]:
    opts: dict[str, str] = {}
    for tok in tokens:
        if "=" not in tok:
            raise StepParseError(f"expected key=value option, got {tok!r}")
        key, value = tok.split("=", 1)
        if not key or value == "":
            raise StepParseError(f"bad key=value option: {tok!r}")
        opts[key.lower()] = value
    return opts


def _positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise StepParseError(f"{label} must be an integer: {value!r}") from exc
    if parsed < 1:
        raise StepParseError(f"{label} must be >= 1")
    return parsed


def _var_expr(varname: str) -> str:
    if varname.startswith("vars."):
        return "{" + varname + "}"
    return "{vars." + varname + "}"


def _selector_default_var(opts: dict[str, str]) -> str:
    for key in ("auto_id", "name", "type", "class"):
        value = opts.get(key)
        if value:
            safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
            if safe:
                return safe
    return "control"


def _warn_name_only(opts: dict[str, str]) -> None:
    if opts.get("name") and not opts.get("auto_id"):
        print("TIP: selector relies on Name only; add auto_id=... for resilience "
              "(AutomationId rarely changes between builds).")


def _append_control_selector_args(args: list[str], opts: dict[str, str]) -> None:
    if opts.get("auto_id"):
        args.extend(["--auto-id", opts["auto_id"]])
    if opts.get("name"):
        args.extend(["--name", opts["name"]])
    if opts.get("type"):
        args.extend(["--control-type", opts["type"]])
    if opts.get("class"):
        args.extend(["--class", opts["class"]])
    if opts.get("auto_id") and opts.get("name"):
        args.append("--name-fallback")


def _build_find_control_step(opts: dict[str, str], varname: str, parent: str) -> dict:
    nth = _positive_int(opts.get("nth", "1"), "nth")
    args = [_var_expr(parent)]
    _append_control_selector_args(args, opts)
    if nth > 1:
        args.append("--all")
    _warn_name_only(opts)
    return {
        "type": "find_control",
        "description": f"Locate control {varname!r} and capture its center point.",
        "script": SCRIPT_BY_TYPE["find_control"],
        "args_expr": args,
        "capture": {
            f"vars.{varname}_x": f"$.rows[{nth}].cols[7]",
            f"vars.{varname}_y": f"$.rows[{nth}].cols[8]",
        },
    }


def _build_click_selector(tokens: list[str]) -> list[dict]:
    if len(tokens) < 2:
        raise StepParseError('click selector requires a name, e.g. click "Close"')
    name = tokens[1]
    opts = _parse_kv_tokens(tokens[2:])
    opts["name"] = name
    parent = opts.pop("parent", "win_hwnd")
    varname = opts.pop("as", "click_target")
    find_step = _build_find_control_step(opts, varname, parent)
    click_step = {
        "type": "click",
        "description": f"Click the center of control {name!r}.",
        "script": SCRIPT_BY_TYPE["click"],
        "args_expr": [_var_expr(f"{varname}_x"), _var_expr(f"{varname}_y")],
    }
    return [find_step, click_step]


def parse_step_line(line: str) -> dict | list[dict]:
    """Parse one compact authoring line into one or more YAML runtime steps."""
    stripped = line.strip()
    if not stripped:
        raise StepParseError("empty step")
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError as exc:
        raise StepParseError(str(exc)) from exc
    if not tokens:
        raise StepParseError("empty step")

    verb = tokens[0].lower()

    if verb == "click":
        if len(tokens) == 3:
            try:
                x = int(tokens[1], 10)
                y = int(tokens[2], 10)
            except ValueError:
                return _build_click_selector(tokens)
            return {
                "type": "click",
                "description": f"Click at {x},{y}.",
                "script": SCRIPT_BY_TYPE["click"],
                "args": [x, y],
            }
        return _build_click_selector(tokens)

    if verb == "type":
        if len(tokens) != 2:
            raise StepParseError('type requires exactly one quoted text argument')
        return {
            "type": "type_text",
            "description": "Type literal text.",
            "script": SCRIPT_BY_TYPE["type_text"],
            "args": [tokens[1]],
        }

    if verb == "type_expr":
        if len(tokens) != 2:
            raise StepParseError('type_expr requires exactly one quoted text argument')
        return {
            "type": "type_text",
            "description": "Type rendered text expression.",
            "script": SCRIPT_BY_TYPE["type_text"],
            "args_expr": [tokens[1]],
        }

    if verb == "key":
        if len(tokens) != 2:
            raise StepParseError("key requires exactly one combo argument")
        return {
            "type": "key",
            "description": f"Press {tokens[1]}.",
            "script": SCRIPT_BY_TYPE["key"],
            "args": [tokens[1]],
        }

    if verb == "find_window":
        if len(tokens) < 2:
            raise StepParseError('find_window requires a title regex, e.g. find_window "^Title$"')
        title_regex = tokens[1]
        opts = _parse_kv_tokens(tokens[2:])
        varname = opts.pop("as", "win")
        nth = _positive_int(opts.pop("nth", "1"), "nth")
        args = [title_regex]
        if opts.get("class"):
            args.extend(["--class", opts.pop("class")])
        if opts.get("backend"):
            backend = opts.pop("backend")
            if backend not in {"uia", "win32", "any"}:
                raise StepParseError("backend must be one of: uia, win32, any")
            args.extend(["--backend", backend])
        if opts:
            raise StepParseError(f"unknown find_window option(s): {', '.join(sorted(opts))}")
        if nth > 1:
            args.append("--all")
            row_prefix = f"$.rows[{nth - 1}].cols"
        else:
            row_prefix = "$.cols"
        return {
            "type": "find_window",
            "description": f"Locate window matching {title_regex!r}; capture hwnd and rect in vars.{varname}_*.",
            "script": SCRIPT_BY_TYPE["find_window"],
            "args": args,
            "capture": {
                f"vars.{varname}_hwnd": f"{row_prefix}[1]",
                f"vars.{varname}_left": f"{row_prefix}[2]",
                f"vars.{varname}_top": f"{row_prefix}[3]",
                f"vars.{varname}_right": f"{row_prefix}[4]",
                f"vars.{varname}_bottom": f"{row_prefix}[5]",
            },
        }

    if verb == "find_control":
        opts = _parse_kv_tokens(tokens[1:])
        parent = opts.pop("parent", None)
        if not parent:
            raise StepParseError("find_control requires parent=<varname>")
        varname = opts.pop("as", _selector_default_var(opts))
        unknown = set(opts) - {"name", "auto_id", "type", "class", "nth"}
        if unknown:
            raise StepParseError(f"unknown find_control option(s): {', '.join(sorted(unknown))}")
        if not any(opts.get(k) for k in ("name", "auto_id", "type", "class")):
            raise StepParseError("find_control requires at least one selector: name, auto_id, type, or class")
        return _build_find_control_step(opts, varname, parent)

    if verb == "assert_file":
        if len(tokens) < 2:
            raise StepParseError("assert_file requires a path")
        args = [tokens[1]]
        idx = 2
        while idx < len(tokens):
            tok = tokens[idx].lower()
            if tok == "contains":
                if idx + 1 >= len(tokens):
                    raise StepParseError("contains requires a substring")
                args.extend(["--contains", tokens[idx + 1]])
                idx += 2
            elif tok == "negate":
                args.append("--negate")
                idx += 1
            elif tok == "delete":
                args.append("--delete")
                idx += 1
            else:
                raise StepParseError(f"unknown assert_file option: {tokens[idx]!r}")
        return {
            "type": "assert_file",
            "description": f"Assert file state for {tokens[1]!r}.",
            "script": SCRIPT_BY_TYPE["assert_file"],
            "args": args,
        }

    if verb == "wait":
        if len(tokens) != 2:
            raise StepParseError("wait requires milliseconds, e.g. wait 500")
        return {"type": "_wait", "ms": _positive_int(tokens[1], "wait")}

    if verb == "screenshot":
        if len(tokens) != 2:
            raise StepParseError('screenshot requires a filename, e.g. screenshot "after.png"')
        return {
            "type": "screenshot",
            "description": f"Capture screenshot {tokens[1]!r}.",
            "script": SCRIPT_BY_TYPE["screenshot"],
            "args_expr": ["{artifacts.screenshot_dir}/" + tokens[1]],
        }

    if verb == "maximize":
        if len(tokens) > 2:
            raise StepParseError("maximize takes at most one window hwnd var, e.g. maximize win_hwnd")
        hwnd_var = tokens[1] if len(tokens) == 2 else "win_hwnd"
        return {
            "type": "maximize_window",
            "description": f"Maximize window {hwnd_var!r} (skip if already maximized).",
            "script": SCRIPT_BY_TYPE["maximize_window"],
            "args_expr": [_var_expr(hwnd_var)],
        }

    raise StepParseError(f"unknown step command {tokens[0]!r}")


class AuthorSession:
    def __init__(self, out_path: str, spec: dict):
        self.out_path = out_path
        self.spec = spec
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.detector = RecurrenceDetector()
        self.dirty = True
        self.saved_once = False
        self._wait_applied = False
        self.vars: dict = {}

    def next_id(self, step_type: str) -> str:
        self.counters[step_type] += 1
        return f"{step_type}_{self.counters[step_type]:02d}"

    def assign_id(self, step: dict) -> None:
        if step.get("type") and not step.get("id") and not step["type"].startswith("_"):
            step["id"] = self.next_id(step["type"])
            self._order_step_keys(step)

    @staticmethod
    def _order_step_keys(step: dict) -> None:
        ordered = {}
        for key in ("id", "type", "description", "script"):
            if key in step:
                ordered[key] = step[key]
        for key, value in step.items():
            if key not in ordered:
                ordered[key] = value
        step.clear()
        step.update(ordered)

    def wait_key(self, ms: int) -> str:
        key = f"wait_{ms}_ms"
        self.spec["timing"].setdefault(key, ms)
        return key

    def apply_wait(self, ms: int, pending: list[dict]) -> None:
        target = pending[-1] if pending else (self.spec["steps"][-1] if self.spec["steps"] else None)
        if target is None:
            raise StepParseError("wait requires a previous step")
        existing = target.get("wait_after")
        if existing and existing in self.spec["timing"]:
            total = int(self.spec["timing"][existing]) + ms
            target["wait_after"] = self.wait_key(total)
        else:
            target["wait_after"] = self.wait_key(ms)
        self._wait_applied = True

    def parse_lines(self, lines: list[str]) -> list[dict]:
        pending: list[dict] = []
        for line in lines:
            parsed = parse_step_line(line)
            parsed_steps = parsed if isinstance(parsed, list) else [parsed]
            for step in parsed_steps:
                if step.get("type") == "_wait":
                    self.apply_wait(step["ms"], pending)
                    continue
                self.assign_id(step)
                try:
                    step = maybe_disambiguate(step, self.vars, self.spec)
                except AmbiguousMatch as exc:
                    _print_ambiguous_matches(exc.matches)
                    raise StepParseError(
                        f"ambiguous find_control: {len(exc.matches)} matches"
                    )
                ok, message = execute_step(step, self.vars, self.spec)
                print(message)
                if not ok:
                    raise StepParseError(f"execution failed for {step.get('id', step.get('type'))}: {message}")
                pending.append(step)
                if step.get("type") in _FINGERPRINT_STEP_TYPES:
                    ui_hash = _capture_ui_fingerprint()
                    recurred = self.detector.observe(step, ui_hash)
                    if recurred:
                        action = _prompt_recurrence_action(recurred)
                        self.detector.reset()
                        if action == "discard":
                            pending.pop()
                            print(f"discarded step {step.get('id', '?')}")
                        elif action == "abort":
                            raise StepParseError(
                                "authoring aborted due to recurring UI state"
                            )
                        # 'keep' falls through; step stays in pending
        return pending

    def add_lines(self, lines: list[str]) -> bool:
        self._wait_applied = False
        try:
            pending = self.parse_lines(lines)
        except StepParseError as exc:
            print(f"ERROR: {exc}")
            return False
        if pending:
            self.spec["steps"].extend(pending)
        if pending or self._wait_applied:
            self.dirty = True
            detail = f"{len(pending)} step(s)" if pending else "wait"
            print(f"accepted {detail}")
        return True

    def list_steps(self) -> None:
        if not self.spec["steps"]:
            print("(no steps yet)")
            return
        for idx, step in enumerate(self.spec["steps"], start=1):
            print(f"{idx}. {step.get('id')} ({step.get('type')}) {step.get('description', '')}")

    def edit_step(self) -> None:
        self.list_steps()
        if not self.spec["steps"]:
            return
        raw = _prompt("Edit which step number? ").strip()
        try:
            idx = int(raw, 10)
        except ValueError:
            print("ERROR: expected a step number")
            return
        if idx < 1 or idx > len(self.spec["steps"]):
            print("ERROR: step number out of range")
            return
        replacement = _prompt("replacement step> ").strip()
        if not replacement:
            print("edit cancelled")
            return
        try:
            new_steps = self.parse_lines([replacement])
        except StepParseError as exc:
            print(f"ERROR: {exc}")
            return
        if not new_steps:
            print("ERROR: replacement produced no step")
            return
        self.spec["steps"][idx - 1:idx] = new_steps
        self.dirty = True
        print(f"replaced step {idx} with {len(new_steps)} step(s)")

    def save(self) -> None:
        ordered_spec = {key: self.spec[key] for key in SPEC_KEY_ORDER}
        mode = "w" if self.saved_once else "x"
        with open(self.out_path, mode, encoding="utf-8") as f:
            yaml.dump(
                ordered_spec,
                f,
                Dumper=yaml.SafeDumper,
                sort_keys=False,
                default_flow_style=False,
                indent=2,
                allow_unicode=True,
            )
        self.saved_once = True
        self.dirty = False
        print(f"saved {self.out_path}")

    def confirm_quit(self) -> bool:
        if not self.dirty:
            return True
        ans = _prompt("Unsaved changes. Quit anyway? [y/N] ").strip().lower()
        return ans in {"y", "yes"}

    def done_confirm(self) -> bool:
        ans = _prompt("Done authoring? [y/N] ").strip().lower()
        if ans not in {"y", "yes"}:
            return False
        if self.dirty:
            save_ans = _prompt("Save before exit? [Y/n] ").strip().lower()
            if save_ans not in {"n", "no"}:
                self.save()
        return True


def collect_block() -> list[str]:
    lines: list[str] = []
    while True:
        line = _prompt("steps (end with blank line)> ")
        if not line.strip() or line.strip() == "---":
            return lines
        lines.append(line)


def initial_spec(name: str, description: str) -> dict:
    return {
        "name": name,
        "description": description,
        "inputs": {},
        "artifacts": {"screenshot_dir": "screenshots/{timestamp}"},
        "timing": {},
        "steps": [],
        "expected_results": [],
    }


def run_repl(session: AuthorSession) -> None:
    while True:
        try:
            line = _prompt("step> ")
        except EOFError:
            print()
            if session.confirm_quit():
                return
            continue
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower == "quit":
            if session.confirm_quit():
                return
            continue
        if lower == "save":
            session.save()
            continue
        if lower == "edit":
            session.edit_step()
            continue
        if lower == "multi":
            lines = collect_block()
            if not lines:
                print("no steps entered")
                continue
            accepted = session.add_lines(lines)
        else:
            accepted = session.add_lines([line])
        if not accepted:
            continue

        while True:
            ans = _prompt("Add another step? [y/N/edit/save/quit] ").strip().lower()
            if ans in {"", "y", "yes"}:
                break
            if ans in {"n", "no"}:
                if session.done_confirm():
                    return
                break
            if ans == "edit":
                session.edit_step()
                continue
            if ans == "save":
                session.save()
                continue
            if ans == "quit":
                if session.confirm_quit():
                    return
                continue
            print("Please answer y, N, edit, save, or quit.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_yaml", help="path to the YAML scenario to create")
    args = parser.parse_args()

    out_path = os.path.abspath(args.out_yaml)
    if os.path.exists(out_path):
        print(f"ERROR: refusing to overwrite existing scenario: {out_path}", file=sys.stderr)
        sys.exit(2)

    print(HELP)
    print()
    name = _prompt("name: ").strip()
    if not name:
        name = os.path.splitext(os.path.basename(out_path))[0]
    description = _prompt("description: ").strip()
    spec = initial_spec(name, description)
    session = AuthorSession(out_path, spec)
    run_repl(session)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

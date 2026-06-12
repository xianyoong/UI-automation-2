# AGENTS.md

Instructions for AI coding agents (GitHub Copilot CLI, Codex CLI, Cursor, Aider, Claude Code, etc.) working in this repository.

This file follows the [agents.md](https://agents.md/) convention and is loaded automatically by supporting agents.

## What this repo is

`ui-auto` is a declarative UI-automation toolkit for Windows desktop apps. Test cases are YAML files in `test_cases/`, executed by `run_test.py` (entry point: `.\run.ps1 <spec>`). Each step in a spec maps to a script under `scripts/`.

## Authoritative references (read on demand, not eagerly)

- `README.md` — install, run, top-level usage.
- `docs/test-spec-format.md` — YAML keys, step types, placeholders, capture syntax.
- `docs/authoring-scenarios.md` — interactive REPL workflow + selector conventions.
- `docs/copilot-cli-test-authoring.md` — user guide for authoring test cases via an AI agent.
- `docs/file-structure.md` — what every file/folder is for.
- `docs/reproducibility.md` — why runs must be bit-identical.
- `docs/troubleshooting.md` — DPI, multi-monitor, UI language gotchas.
- `test_cases/powershell_echo_loop.yaml` — canonical example (also shows `foreach` + UIA validation).
- `scripts/*.py` — one script per step `type`.

## Hard rules when authoring or editing a test case

1. Top-level YAML keys MUST be: `name`, `description`, `inputs`, `artifacts`, `timing`, `steps`, `expected_results`. Do not invent new top-level keys.
2. **Do NOT randomize `inputs`.** Reproducibility requires identical values every run.
3. Every step has `id`, `type`, `description`. Reference timing via `wait_after: <key_from_timing_block>` — never inline ms literals.
4. **Selectors:** prefer `auto_id` + `name` together. `scripts/uia/find_control.py` tries AutomationId first, falls back to name. Always pass `parent=` a captured window hwnd.
5. **Capture** window/control handles with `capture: { vars.<name>: "$.cols[1]" }` on `find_window` / `find_control` steps; reference them as `{vars.<name>}` in later steps.
6. Artifact paths use `{timestamp}` (substituted at run start, UTC). Default screenshot dir: `screenshots/{timestamp}`.
7. For console assertions use `assert_console_contains` with `poll_total_ms` and `poll_interval_ms` from the `timing` block.
8. For file assertions use `assert_file` (supports `--negate`, `--contains`, `--delete`).
9. Do **not** invent new step types. If something doesn't fit, ask before extending the schema.
10. When emitting a new test case, output ONE complete YAML in a single fenced block; no surrounding prose unless the user asks for an explanation.

## Iterating on failures

When the user pastes back a failing step id + stderr, respond with the **smallest diff** that fixes that step only. Do not re-emit the whole file unless the structure itself is wrong.

## Running tests and the runner

See the [README](README.md) for install, run, and exit-code semantics. Quick reference:

- Run a scenario: `.\run.ps1 test_cases\<name>.yaml -q`
- Unit tests: `uv run python -m unittest discover -s tests -v`

## Environment

Windows 10/11, PowerShell, Python via `uv` with pins in `requirements.lock.txt` / `uv.lock`. Use Windows-style backslash paths. Don't bump pins as part of unrelated changes.

## Style and scope

- Make surgical changes. Don't touch unrelated code or randomize anything that affects reproducibility.
- Don't commit secrets or generated `screenshots/{timestamp}/` artifacts.
- Don't add new linters, formatters, or test frameworks without being asked.

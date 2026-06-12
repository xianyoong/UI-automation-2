# File structure

A guided tour of every file and folder in this repo, so you can find your way around quickly.

## Top level

| Path | Purpose |
|---|---|
| `README.md` | Project overview, install command, example invocation, doc index. |
| `AGENTS.md` | Auto-loaded instructions for AI coding agents (Copilot CLI, Codex CLI, Cursor, Aider, Claude Code, …) working in this repo. Follows the [agents.md](https://agents.md/) convention. |
| `LICENSE` | MIT license. |
| `install.ps1` | One-line bootstrap installer for a fresh Windows machine (see [Entry points](#entry-points)). |
| `setup.ps1` | Local convenience wrapper that runs `uv sync` when `uv` is already installed. |
| `run.ps1` | Thin shortcut wrapper: `.\run.ps1 <spec> [-q]` → `uv run python run_test.py <spec> [-q]`. Lets you invoke a scenario without going through an LLM. |
| `run_test.py` | YAML test-spec runner (see [Entry points](#entry-points)). |
| `pyproject.toml` | Project metadata + direct dependencies (`pyautogui`, `pywinauto`, `Pillow`, `PyYAML`). Pins Python to `>=3.10,<3.13`. |
| `requirements.txt` | Human-edited top-level requirements list (mirrors `pyproject.toml` deps). |
| `requirements.lock.txt` | Fully resolved, pinned dependency list for `pip` users. |
| `uv.lock` | `uv`-generated lockfile pinning every transitive dependency with content hashes. |
| `.python-version` | Interpreter version pin used by `uv` to fetch the exact Python build. |
| `.gitignore` | Excludes `.venv/`, `screenshots/`, and other local artifacts from git. |
| `.venv/` | Local virtual environment created by `uv sync` (not committed). |
| `screenshots/` | Per-run screenshot artifacts written under `screenshots/{timestamp}/` (not committed). |
| `docs/` | Markdown documentation — see [docs/](#docs). |
| `scripts/` | Primitive Python helpers invoked by `run_test.py`, grouped into category subfolders — see [scripts/](#scripts) and [scripts-reference.md](scripts-reference.md). |
| `test_cases/` | Declarative YAML scenarios — see [test_cases/](#test_cases). |
| `tests/` | Stdlib `unittest` coverage for the helper scripts and the authoring REPL. Run with `uv run python -m unittest discover -s tests -v`. |

## Entry points

### `install.ps1`
Zero-state bootstrap for a clean Windows 10/11 machine. In order it:

1. Installs `uv` from `astral.sh` if missing.
2. Installs `git` via `winget` if missing.
3. Clones (or `git pull`s) the repo into `%USERPROFILE%\UI-automation`.
4. Runs `uv sync` to fetch the pinned Python interpreter and all dependencies.
5. Prints the example command to run the bundled scenario.

Designed to be invoked via `irm https://raw.githubusercontent.com/william051200/UI-automation/main/install.ps1 | iex`.

### `setup.ps1`
Lightweight alternative for developers who already have `uv` installed. `cd`s to the repo, verifies `uv` is on `PATH`, runs `uv sync`, and prints the example command. Use `install.ps1` instead on a fresh machine.

### `run.ps1`
Thin PowerShell wrapper around `uv run python run_test.py`. Takes the spec path as its first argument and forwards any remaining flags (e.g. `-q`). `Set-Location $PSScriptRoot` lets you call it from any working directory, and it propagates the runner's exit code unchanged.

```powershell
.\run.ps1 test_cases\powershell_echo_loop.yaml
.\run.ps1 test_cases\powershell_echo_loop.yaml -q
```

### `run_test.py`
The test runner. Given a YAML spec, it:

- Parses `inputs`, `artifacts`, `timing`, and `steps` blocks (format documented in [`test-spec-format.md`](test-spec-format.md)).
- Enables per-monitor v2 DPI awareness so virtual-pixel clicks line up with physical-pixel UIA rectangles on HiDPI displays.
- Walks `steps` in order, dispatching each one by invoking the matching `scripts/*.py` as a subprocess (with `args` / `args_expr` substituted from captured variables and inputs).
- Captures stdout from helper scripts and stores fields in `vars.*` for later steps (see `capture:` clauses).
- Evaluates assertions (`assert_console_contains`, `expect_exit`, etc.) and polls where requested.
- Saves screenshots into `artifacts.screenshot_dir`.
- Exits **0** on full pass, **1** on a failed assertion, **2** on runner error (bad spec, missing script, etc.).

Pass `-q` / `--quiet` to suppress per-step headers and successful subcommand stdout — useful when running under an LLM to keep token usage down. Failure output, stderr, and the final `RESULT` line are always shown.

Usage: `uv run python run_test.py test_cases\<scenario>.yaml [-q]`.

## `scripts/`

Single-purpose Python CLIs used as primitives by `run_test.py` (and runnable directly for debugging). They are organized into category subfolders:

| Subfolder | Contents |
|---|---|
| `scripts/web/` | Browser automation over the Chrome DevTools Protocol (`cdp_client`, `browser_launch`, `browser_goto`, `dom_get_html`, `dom_interact`, `dom_query`, `dom_eval`). |
| `scripts/input/` | Synthetic mouse/keyboard input at screen coordinates (`click`, `type_text`, `key`, `drag`, `scroll`). |
| `scripts/window/` | Window management — find, focus, maximize, launch, close, and poll-wait (`find_window`, `activate_window`, `maximize_window`, `close_window`, `launch`, `wait_for`). |
| `scripts/uia/` | UI Automation inspection / text reads (`find_control`, `read_console`, `read_text`, `uia_tree`, `ui_fingerprint`). |
| `scripts/files/` | Screenshots, file writes/asserts, clipboard (`screenshot`, `write_text`, `assert_file_exists`, `clipboard`). |
| `scripts/authoring/` | Interactive YAML authoring REPL (`author_test`). |

See [`scripts-reference.md`](scripts-reference.md) for what every script does, its step `type`, arguments, and exit codes.

| File | Purpose |
|---|---|
| [`file-structure.md`](file-structure.md) | This document — layout of the repo. |
| [`scripts-reference.md`](scripts-reference.md) | What every `scripts/` helper does — step `type`, arguments, exit codes, grouped by category. |
| [`test-spec-format.md`](test-spec-format.md) | Reference for YAML spec keys, step types, placeholder syntax, and `capture` rules. |
| [`authoring-scenarios.md`](authoring-scenarios.md) | Workflow for writing a new scenario, including using Inspect.exe to discover UIA selectors. |
| [`copilot-cli-test-authoring.md`](copilot-cli-test-authoring.md) | Human-facing workflow for authoring test cases via Copilot CLI / other AI agents. |
| [`reproducibility.md`](reproducibility.md) | Why runs stay bit-identical (pinned inputs, UIA targeting, locked deps). |
| [`troubleshooting.md`](troubleshooting.md) | DPI scaling, multi-monitor, UI-language, and legacy pip path issues. |

## `test_cases/`

Holds the declarative YAML scenarios consumed by `run_test.py`. One file per scenario; new scenarios drop in here alongside the existing example.

| File | Purpose |
|---|---|
| `powershell_echo_loop.yaml` | Reference scenario: opens PowerShell from the Start menu, echoes four fixed strings, validates each via UIA, screenshots each iteration, then closes the window by clicking the UIA-located Close button. |
| `propertyguru_search_edge.yaml` | Web-automation sample: launches a fresh Microsoft Edge over CDP, loads PropertyGuru (MY), screenshots the home page, searches "Batu Kawan", screenshots the results, opens the first listing, and screenshots its detail page. Targets a live external site, so it is intentionally **not** bit-reproducible. |

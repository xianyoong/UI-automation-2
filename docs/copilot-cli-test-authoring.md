# Creating test cases with Copilot CLI

A user-facing workflow for authoring new YAML test cases via [GitHub Copilot CLI](https://github.com/github/gh-copilot) (or any other agent that reads [`AGENTS.md`](../AGENTS.md)).

The **rules** the agent must follow live in [`AGENTS.md`](../AGENTS.md) at the repo root and are auto-loaded — this doc only covers *how you, the human, drive the session*. For the YAML spec itself see [`test-spec-format.md`](test-spec-format.md); for the live-capture REPL alternative see [`authoring-scenarios.md`](authoring-scenarios.md).

## Prerequisites

- Repo installed per the [README](../README.md) (`uv`, Python, deps).
- `gh` CLI with the Copilot extension installed and authenticated.
- The target Windows app reachable from the Start menu (or with a known launch path).

## How the agent sees this repo

Copilot CLI and most other agents (Codex CLI, Cursor, Aider, Claude Code, …) auto-load [`AGENTS.md`](../AGENTS.md) on session start. Everything under `docs/`, `scripts/`, and `test_cases/` is read on demand via the agent's own tool calls — `AGENTS.md` points at those files so the agent knows where to look but doesn't preload them.

For Copilot-only tweaks, add `.github/copilot-instructions.md` (Copilot ignores other agents' files and vice versa).

## Pick a workflow

| Situation | Recommended workflow |
|---|---|
| Brand-new scenario, unknown UIA tree | **REPL-first** — use `scripts/authoring/author_test.py` to capture real selectors live, then ask the agent to refactor / extend. |
| Variant of an existing scenario | **Agent-first** — point the agent at the nearest existing YAML in `test_cases/` and have it produce a new file. |
| Bulk parameter sweep | **Agent-first** — describe the inputs table; the agent fills `inputs` + a `foreach` block. |

The REPL guarantees selectors actually resolve; the agent is faster but you must run the result and iterate on failures.

## Recommended loop

1. **Describe the scenario** in one prompt — app to open, actions, assertions, artifacts. No need to restate the rules; `AGENTS.md` covers them.
2. **Save** the generated YAML to `test_cases/<name>.yaml`.
3. **Run it** directly (no LLM in the loop):
   ```powershell
   .\run.ps1 test_cases\<name>.yaml -q
   ```
4. **On failure**, paste the failing step id + stderr back to the agent and ask for a targeted fix. Don't let it re-emit the whole file unless the structure is wrong.

## Example prompts

**Run an existing scenario** (no authoring):
> Run `.\run.ps1 test_cases\powershell_echo_loop.yaml -q` and report only the exit code and any FAIL lines.

**Simple new scenario:**
> Create `test_cases/notepad_save.yaml` that opens Notepad from the Start menu, types `hello from copilot`, saves the file as `%TEMP%\copilot_test.txt` via Ctrl+S, asserts the file exists, and closes Notepad with a mouse click on the Close button. Reuse the `timing` block style from `test_cases/powershell_echo_loop.yaml`.

**Parametrised scenario:**
> Create `test_cases/notepad_echo.yaml` that opens Notepad from the Start menu and, for each string in `inputs.lines` (e.g. `["alpha", "beta", "gamma"]`), types the line followed by Enter, screenshots the window, and asserts the document text contains that line. Use a `foreach` step.

**Targeted fix:**
> Step `validate_echo_3` fails with `expected_contains_expr not found within 3000 ms`. The text appears but with a leading `PS>` prompt. Update only that step's `expected_contains_expr` — don't touch other steps.

## Optional follow-up prompts

- *"Explain what step `<id>` does and why `wait_after` is set to `<timing_key>`."*
- *"Convert the three repeated `click` steps into a `foreach` over `inputs.buttons`."*
- *"Add a fail-only screenshot variant for step `<id>`."* (see [`test-spec-format.md`](test-spec-format.md#pass--fail-screenshot-variants))

## Token-efficient usage

See the [*Token-efficient Copilot usage*](../README.md#token-efficient-copilot-usage) section in the README.

## See also

- [`AGENTS.md`](../AGENTS.md) — rules the agent follows (auto-loaded).
- [Test-spec format](test-spec-format.md)
- [Authoring scenarios (REPL)](authoring-scenarios.md)
- [Troubleshooting](troubleshooting.md)
- [Reproducibility](reproducibility.md)

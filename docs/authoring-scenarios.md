# Authoring a new scenario

There are two ways to author a scenario:

## Option A — Interactive REPL (recommended)

Run the interactive authoring tool and type one compact step per line. Each step is executed live, so captured variables (window hwnds, control coordinates, ...) accumulate as you go.

```powershell
uv run python scripts/authoring/author_test.py test_cases\my_scenario.yaml
```

Commands inside the REPL: `multi` for block input, `edit` to replace a step, `save` to write the YAML, `quit` to exit.

### Selector convention

Prefer the **AutomationId + Name** pattern so the YAML survives small UI changes:

```text
click "Close" type=Button auto_id=CloseButton parent=win_hwnd
find_control parent=win_hwnd name="Close" auto_id=CloseButton type=Button
```

When both `auto_id=` and a name are present, the authoring tool emits both `--auto-id` and `--name` plus `--name-fallback` into the saved YAML. `scripts/uia/find_control.py` then tries AutomationId first and, if it yields zero matches, retries with the auto_id filter dropped (name / type / class still apply). This makes scenarios resilient to AutomationId churn between app builds.

If you only supply a name the tool prints a TIP suggesting you add an `auto_id=` — it never blocks.

### Live safety checks

The REPL runs each step against the real UI as you type it, and applies two safeguards on top of that:

- **Ambiguous selector halt.** If a `find_control` selector matches more than one control, the step is **not executed**; instead the REPL prints every candidate (name / auto_id / type / rect) and asks you to re-enter the step with a more specific selector (`auto_id=`, `type=`, `class=`, or `nth=`). This is what would have hit the "two Close buttons" problem during authoring instead of at run time.

- **Recurring-state halt.** After each acting step (`click` / `key` / `type_text`), the REPL captures a UI fingerprint via `scripts/uia/ui_fingerprint.py`. If the **last three** consecutive fingerprints are identical — i.e. the UI hasn't changed despite your inputs — authoring halts with a prompt:
  - `[k]eep` — accept the step and keep going
  - `[d]iscard` — drop the step and try a different one
  - `[a]bort` — discard the current batch entirely

## Option B — Hand-edit YAML

1. Use **Inspect.exe** (ships with the Windows SDK, typically at `C:\Program Files (x86)\Windows Kits\10\bin\<version>\x64\Inspect.exe`) to discover UIA selectors for the controls you'll target:
   - window title
   - button `Name` / `AutomationId` / `ControlType`
   - any other property you'll match against
2. Copy [`test_cases/powershell_echo_loop.yaml`](../test_cases/powershell_echo_loop.yaml) as a starting point.
3. Replace `inputs`, `steps`, and `expected_results`. Keep `inputs` literal — no randomness — so reruns are bit-for-bit reproducible.
4. Run the spec:
   ```powershell
   uv run python run_test.py test_cases\my_scenario.yaml
   ```
5. Iterate on the `timing:` constants if you see flaky waits.

See [test-spec-format.md](test-spec-format.md) for the full YAML reference.

## Running tests

Unit tests for the authoring tool live in `tests/`:

```powershell
uv run python -m unittest discover -s tests -v
```


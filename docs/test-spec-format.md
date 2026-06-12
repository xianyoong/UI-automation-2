# Test-case spec format

A test case is a YAML file with these top-level keys:

| Key | Purpose |
|---|---|
| `name`, `description` | Human-readable identity. |
| `inputs` | Fixed values used by the scenario. **Do not randomize** — reproducibility requires identical inputs every run. |
| `artifacts` | Output paths; `{timestamp}` is substituted at run start (UTC). |
| `timing` | Named delay/poll constants (ms). Steps reference these by name (e.g. `wait_after: after_enter_ms`). |
| `steps` | Ordered list of actions. Each step has an `id`, `type`, and `description`. |
| `expected_results` | Human-readable pass criteria. |

## Step types

| `type` | Calls | Notes |
|---|---|---|
| `key`, `type_text`, `click`, `screenshot`, `find_window`, `find_control` | matching `scripts/*.py` | `expect_exit` defaults to 0. Set to a non-zero value to assert failure (e.g. `find_window` after closing a window). |
| `assert_file` | `assert_file_exists.py` | Asserts a file exists (or, with `--negate`, does not). Optional `--contains` checks a substring; `--delete` removes the file after the check. |
| `assert_console_contains` | `read_console.py` with polling | Asserts `expected_contains_expr` appears within `poll_total_ms`. |
| `foreach` | n/a | Iterates `items` (e.g. `inputs.echo_texts`), exposing `var` and `index_var` to nested `body` steps. |

### Web-page steps (raw Chrome DevTools Protocol)

These drive a Chrome launched normally with only `--remote-debugging-port` (no automation switches, so `navigator.webdriver` stays `false`). State lives in the long-running Chrome; each step reconnects over CDP. All accept `--port` (default `9222`) and an optional `--url-contains` to pick a specific page target. See [reproducibility](reproducibility.md) for the fixed `--user-data-dir`.

| `type` | Calls | Notes |
|---|---|---|
| `browser_launch` | `browser_launch.py` | Launches Chrome or Edge (`--browser chrome|edge`) with `--remote-debugging-port` + fixed `--user-data-dir`, waits for the CDP endpoint. `--fresh` wipes the profile dir first. Prints `port`/`pid`; capture the port for later steps. |
| `browser_goto` | `browser_goto.py` | `Page.navigate` to a URL, waits for `document.readyState === 'complete'`. Prints final `url`/`title`. |
| `dom_get_html` | `dom_get_html.py` | Writes `outerHTML` (or `--text` `innerText`) of the document or `--selector` to `--out`; prints `bytes`/`path`. Exit 1 if the selector matches nothing. |
| `dom_interact` | `dom_interact.py` | `action` ∈ click/type/set/press/select on a CSS `--selector` (+`--value`). Uses trusted `Input.dispatch*` events. Exit 1 if not found/interactable. |
| `dom_query` | `dom_query.py` | Validate where to interact: reports `count`/`visible`/`text`/box for a `--selector`. Assertion flags `--expect-min`/`--visible`/`--contains` exit 1 on failure. `--attr NAME` prints the first match's attribute value as the first output line (capture via `$.cols[0]`); `--attr innerText` captures text. |
| `dom_eval` | `dom_eval.py` | Evaluates a JS `--expr` on the page and prints the result as the first output line (capture via `$.cols[0]`); objects become compact JSON. Null/undefined exits 1. Use for values not addressable as elements/attributes (e.g. inside `window.__NEXT_DATA__`). |
| `write_text` | `write_text.py` | Writes `--text` (default empty; `\n` → newline) to `--out`, makes parent dirs, prints the **absolute** path as the first line (capture via `$.cols[0]`). `--append` to append. Useful to pre-create a path-bound file for a GUI editor to save. |

## Placeholders

`{path.to.value}` resolves against `inputs`, `artifacts`, `vars` (captured from earlier steps), and loop locals. Simple integer arithmetic works:

```yaml
args_expr: ["{vars.win_left + 100}", "{vars.win_top + 60}"]
```

## Capturing values from script output

```yaml
capture:
  vars.hwnd: "$.cols[1]"               # column 1 of the first output line
  vars.close_x: "$.rows[1].cols[7]"    # row 1, column 7 (skip header)
```

## Pass / fail screenshot variants

`screenshot` accepts `args_expr_on_pass` and `args_expr_on_fail`, so failed iterations are saved under a different filename:

```yaml
- id: snapshot
  type: screenshot
  script: scripts/files/screenshot.py
  args_expr_on_pass: ["{artifacts.screenshot_dir}/iter_{n}.png"]
  args_expr_on_fail: ["{artifacts.screenshot_dir}/iter_{n}_FAIL.png"]
```

See [`test_cases/powershell_echo_loop.yaml`](../test_cases/powershell_echo_loop.yaml) for a complete worked example.

# Scripts reference

Every primitive helper invoked by `run_test.py` lives under `scripts/`, organized into category subfolders. Each script is a single-purpose CLI mapped to a step `type` in a YAML spec, and can also be run directly from a shell for ad-hoc debugging. This is the single source of truth for what each script does; the [file-structure](file-structure.md) doc only describes the repo layout.

Categories:

- [`scripts/web/`](#web--browser--cdp) — browser automation over the Chrome DevTools Protocol
- [`scripts/input/`](#input--mousekeyboard) — synthetic mouse / keyboard input (screen coordinates)
- [`scripts/window/`](#window--window-management) — find, focus, maximize, launch, close windows
- [`scripts/uia/`](#uia--ui-automation-inspection) — read / inspect UI Automation trees and text
- [`scripts/files/`](#files--files--clipboard) — screenshots, file writes/asserts, clipboard
- [`scripts/authoring/`](#authoring) — the interactive YAML authoring REPL

---

## `web/` — browser / CDP

These drive a Chrome/Edge launched normally with only `--remote-debugging-port` (no automation switches, so `navigator.webdriver` stays `false`), attaching over raw CDP. Each helper reconnects to the long-running browser, since runner steps are separate subprocesses. All take `--port` (default `9222`) and optional `--url-contains` to select a page target.

### `cdp_client.py` — shared CDP module (not a step)
Connection plumbing imported by the helpers below: `list_targets()`, `select_page_target()`, `wait_ready()`, and a `CDPSession` websocket wrapper with `send()`/`evaluate()`. Pure helpers are unit-tested in `tests/test_cdp_client.py`. Lives alongside the other `web/` scripts so they can `import cdp_client` directly.

### `browser_launch.py` — start Chrome/Edge with a debug port
Locates the browser (`--browser chrome|edge`), launches it with `--remote-debugging-port` and a fixed `--user-data-dir` (default `.browser-profile/` or `.browser-profile-edge/`, gitignored), and polls until the CDP endpoint answers. `--fresh` wipes the profile dir first. `--clone` instead seeds the profile dir from your real browser profile (`%LocalAppData%\Microsoft\Edge\User Data` etc.) so your existing logins/cookies carry over without touching the live profile — it defaults to a `.browser-profile[-edge]-clone/` dir and clones only when that dir is empty (use `--fresh` to force a re-clone, or `--clone-from PATH` to pick a different source). Prints the launched **pid on its own first line** (capture via `$.cols[0]`).

```
browser_launch.py [url] [--browser chrome|edge] [--fresh] [--clone] [--clone-from DIR]
                  [--port 9222] [--user-data-dir DIR] [--chrome PATH]
```

### `browser_goto.py` — navigate to a URL
`Page.navigate` to a URL, then waits for `document.readyState === 'complete'`. Prints the final `url` and `title`.

```
browser_goto.py <url> [--port 9222] [--load-timeout-ms 15000]
```

### `dom_get_html.py` — read page/element HTML
Writes the `outerHTML` (or `--text` `innerText`) of the document or `--selector` to `--out`, printing `bytes`/`path`. Exit 1 if the selector matches nothing.

```
dom_get_html.py --out PATH [--selector CSS] [--text] [--port 9222]
```

### `dom_interact.py` — click / type / press on an element
Performs `action` (click/type/set/press/select) on a CSS `--selector` using trusted CDP `Input.dispatch*` events. Exit 1 if not found/interactable.

```
dom_interact.py <click|type|set|press|select> [--selector CSS] [--value V] [--port 9222]
```

### `dom_query.py` — validate where to interact
Reports `count`/`visible`/`text`/bounding-box for a `--selector`. Assertion flags `--expect-min`, `--visible`, `--contains` make it exit 1 on failure. `--attr NAME` reads an attribute (e.g. `href`) of the first match and prints its raw value as the **first** output line (`$.cols[0]`). `--attr innerText` works too (non-attribute property names fall back to `el[NAME]`), giving a clean text capture.

```
dom_query.py --selector CSS [--expect-min N] [--visible] [--contains TEXT] [--attr NAME] [--port 9222]
```

### `dom_eval.py` — evaluate a JS expression on the page
Evaluates `--expr` (a JavaScript expression) on the active CDP page and prints the result as the **first** output line (capture via `$.cols[0]`); a `type=<js-type>` line follows. Objects are printed as compact JSON; a `null`/`undefined` result exits 1. Use it when the value isn't addressable as an element/attribute — e.g. a field inside `window.__NEXT_DATA__`.

```
dom_eval.py --expr JS [--url-contains S] [--port 9222]
```

---

## `input/` — mouse/keyboard

Synthetic input delivered at **screen coordinates** to the focused window. (For in-page web interactions use the `web/dom_interact.py` helper instead — that drives DOM elements over CDP and is not redundant with these.)

### `click.py` — mouse click
Moves the mouse to `(x, y)` and clicks. Defaults to a single left click; flags allow right-click and double-click.

```
click.py <x> <y> [--right] [--double]
```

### `type_text.py` — type a literal string
Types a text string into the currently focused window (UTF-8). `--interval` controls per-character delay (default 0.02 s; use `0.06` if capitals/Shift get dropped on slower machines).

```
type_text.py <text> [--interval 0.02]
```

### `key.py` — press a key or hotkey
Presses a single named key (`enter`, `win`, `tab`, …) or a `+`-separated hotkey combo (`ctrl+s`, `alt+f4`, `win+r`).

```
key.py <combo>
```

### `drag.py` — press, drag, release
Presses a mouse button at `(x1,y1)`, drags to `(x2,y2)`, and releases, using an explicit mouseDown → moveTo → mouseUp sequence (pyautogui's `dragTo()` is unreliable on Windows 11).

```
drag.py <x1> <y1> <x2> <y2> [--button left|right]
```

### `scroll.py` — scroll the mouse wheel
Scrolls the wheel at `(x, y)`. Positive delta = up/right, negative = down/left.

```
scroll.py <x> <y> <delta>
```

---

## `window/` — window management

### `find_window.py` — locate a top-level window
Iterates all desktop windows (via `uia`, `win32`, or `any`, de-duplicating by handle) and returns those whose title matches a regex (optionally filtered by class name or owning process id via `--pid`). Results are sorted by `(pid, hwnd)` so numbered candidate lists are reproducible. Prints tab-separated `pid hwnd left top right bottom title`. Exits **1** if nothing matches — used by specs to assert a window is *gone* (`expect_exit: 1`).

```
find_window.py <title_regex> [--class CLASS] [--pid PID] [--backend uia|win32|any]
                              [--all | --nth N]
```

### `activate_window.py` — raise + focus a window
Restores the window if minimised, then calls `SetForegroundWindow` via pywinauto's `set_focus()`. Prints `activated hwnd=<n> title=<...>`. Exits 1 if the hwnd does not exist or Windows refuses to foreground it.

```
activate_window.py <hwnd> [--backend uia|win32] [--settle-ms 100]
```

### `maximize_window.py` — maximize a window (skip if already maximized)
Maximizes a window by `hwnd` (restores first if minimised). If **already maximized** it is left unchanged and `already maximized hwnd=<n> ...` is printed (still exit 0). Exits 1 if the hwnd does not exist.

```
maximize_window.py <hwnd> [--backend uia|win32] [--settle-ms 100]
```

### `close_window.py` — close a window (graceful, optional force)
Sends WM_CLOSE to the window (same as clicking the X / Alt+F4). If the window or its owning process is still alive after `--grace-ms`, exits 2 unless `--force` is set, in which case the owning process is terminated. Exit: 0 closed, 1 no such hwnd, 2 still alive without `--force`, 3 bad usage.

```
close_window.py <hwnd> [--grace-ms 2000] [--force]
```

### `launch.py` — launch an executable, optionally wait for its window
Prints `pid` on success. With `--wait-window`, prints `pid<TAB>hwnd<TAB>left<TAB>top<TAB>right<TAB>bottom<TAB>title` once a matching window appears (same column order as `find_window.py`). Exit: 0 OK, 1 launch failed, 2 window-wait timed out, 3 bad usage.

```
launch.py <exe> [--args ...] [--wait-window REGEX] [--timeout-ms N]
```

### `wait_for.py` — poll find_window / find_control until success
Wraps `window/find_window.py` or `uia/find_control.py` and retries until it succeeds or `--timeout-ms` elapses. On success, stdout is whatever the wrapped helper printed (so `capture:` rules work identically). On timeout, exits 1.

```
wait_for.py --mode window|control [--timeout-ms 5000] [--poll-ms 250] -- <helper args>
```

---

## `uia/` — UI Automation inspection

### `find_control.py` — locate a UIA control inside a window
Walks the UIA descendant tree of a window (by `hwnd`) and matches controls by `name`, `auto_id`, `control_type`, and/or `class`, using `exact` / `contains` / `regex` comparison. Prints a header row plus rectangle and computed center coordinates, ready to feed into `input/click.py`. With `--name-fallback`, if the `--auto-id` filter yields zero matches the scan retries without it — keeps selectors resilient when AutomationIds churn between app builds.

```
find_control.py <hwnd> [--name N] [--auto-id A] [--control-type T] [--class C]
                       [--match exact|contains|regex] [--backend uia|win32]
                       [--parent-hwnd HWND] [--all | --nth N] [--name-fallback]
```

### `read_console.py` — dump a window's UIA text (console-oriented)
Connects to a window by `hwnd` and prints its textual content. Prefers the `Document` UIA control (where a PowerShell/terminal console exposes its buffer), falling back to legacy properties, then to every visible text node. Used to validate console output without OCR.

```
read_console.py <hwnd>
```

### `read_text.py` — read a specific UIA element's text (selector-based)
Inverse of `type_text.py`. Locates a descendant via `<parent_hwnd>` plus any of `--name` / `--auto-id` / `--control-type` (or reads the parent's own text with no selectors), then prints the value verbatim (no quotes, no trailing newline). Works for modern apps (UWP/WinUI/Win11 Notepad) whose children have no Win32 hwnd.

```
read_text.py <hwnd> [--name N] [--auto-id A] [--control-type T]
```

> **Note — `read_console.py` vs `read_text.py`:** both read UIA text but serve different jobs. `read_console.py` targets the whole-window console buffer (the `Document` control) for terminal output; `read_text.py` reads a *specific* selector-addressed descendant. Keep both; pick by whether you want the console buffer or a single labelled control.

### `uia_tree.py` — dump a depth-bounded UIA subtree as JSON
Walks a window's UIA tree breadth-first up to `--max-depth` and prints a JSON array of nodes (name / auto_id / control_type / class / rect / depth / children). Filters apply before recursion. Use for discovering selectors during authoring.

```
uia_tree.py <hwnd> [--max-depth N] [--name N] [--auto-id A] [--control-type T]
```

### `ui_fingerprint.py` — short hash of the current foreground UI
Prints a 16-char SHA-256 prefix derived from the foreground window's title, class, process, optional rectangle, and up to 50 direct UIA children sorted by screen position. The authoring REPL's recurrence detector calls this after each acting step to spot a stuck UI. (Distinct from `uia_tree.py`: a stable change-hash vs a full human-readable dump.)

```
ui_fingerprint.py [--verbose] [--no-include-rect]
```

---

## `files/` — files & clipboard

### `screenshot.py` — capture PNG
Saves a PNG of the full screen, or of a specified region. Creates the output directory if needed.

```
screenshot.py <out_path> [--region X Y W H]
```

### `write_text.py` — create / write a text file
Writes `--text` (default empty; `\n` becomes a newline) to `--out`, creating parent dirs, and prints the file's **absolute path** as the first line (`$.cols[0]`), then `bytes=<n>`. `--append` appends instead of overwriting. Handy for pre-creating an empty file so a GUI editor (e.g. Notepad) can open it *path-bound* and save with Ctrl+S (no Save-As dialog to automate).

```
write_text.py --out PATH [--text STR] [--append]
```

### `assert_file_exists.py` — file existence / content assertions
Asserts a file exists (or, with `--negate`, does not), optionally checking that it contains a given substring, and optionally deleting it afterwards (`--delete`). Used by the YAML `assert_file` step type.

```
assert_file_exists.py <path> [--contains TEXT] [--negate] [--delete]
```

### `clipboard.py` — read or write the Windows clipboard (text only)
`read` prints current clipboard text; `write <text>` replaces it; `write-stdin` reads stdin verbatim (multi-line safe). Uses the Win32 clipboard API via ctypes.

```
clipboard.py <read|write|write-stdin> [text]
```

---

## `authoring/`

### `author_test.py` — interactive YAML authoring REPL
Builds a runnable YAML spec one compact step line at a time. Each step is executed live against the real UI, so captured variables (window hwnds, control coordinates) accumulate as you go. Includes two safety halts: ambiguous `find_control` selectors and 3-in-a-row identical UI fingerprints. See [`authoring-scenarios.md`](authoring-scenarios.md) for the workflow.

```
author_test.py <out_yaml>
```

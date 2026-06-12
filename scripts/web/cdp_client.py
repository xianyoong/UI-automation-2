"""Minimal Chrome DevTools Protocol (CDP) client over a websocket.

Attaches to a Chrome that was launched normally with only
``--remote-debugging-port=<port>`` (no automation switches), so
``navigator.webdriver`` stays ``false`` and the real profile/UA are used. Every
helper script reconnects through this module, since each runner step is a fresh
subprocess and browser state lives in the long-running Chrome, not the helper.

Public surface used by the helper scripts:
  * ``list_targets(port)``            -> list of target dicts from ``/json``
  * ``select_page_target(targets, url_contains=None)`` (pure, unit-tested)
  * ``wait_ready(port, timeout_s)``   -> poll ``/json/version`` until reachable
  * ``CDPSession``                    -> websocket session with ``send`` / ``evaluate``
  * ``connect_page(port, url_contains=None, timeout_s=...)`` -> open a CDPSession
"""
import json
import time
import urllib.request

import websocket  # websocket-client


class CDPError(RuntimeError):
    """Raised when a CDP command returns an error or a target can't be found."""


def _http_get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_targets(port, timeout=5):
    """Return the list of debuggable targets reported by ``/json``."""
    return _http_get_json(f"http://127.0.0.1:{port}/json", timeout=timeout)


def select_page_target(targets, url_contains=None):
    """Pick the most appropriate ``type == 'page'`` target, optionally by URL.

    When ``url_contains`` is given, only targets whose URL contains it are
    considered. Otherwise, real web pages (http/https/file) are preferred over
    browser-internal pages (e.g. ``edge://sync-confirmation-dialog``,
    ``chrome://``, ``devtools://``, ``about:blank``) so DOM helpers attach to the
    content page rather than a transient browser dialog.

    Pure function (no I/O) so it is unit-testable without a live browser.
    Raises :class:`CDPError` if no matching page target exists.
    """
    pages = [t for t in targets if t.get("type") == "page"]
    if url_contains:
        pages = [t for t in pages if url_contains in (t.get("url") or "")]
    elif pages:
        web = [t for t in pages
               if (t.get("url") or "").startswith(("http://", "https://", "file://"))]
        if web:
            pages = web
    if not pages:
        hint = f" matching url_contains={url_contains!r}" if url_contains else ""
        raise CDPError(f"no page target found{hint}")
    return pages[0]


def wait_ready(port, timeout_s=15.0, interval_s=0.25):
    """Poll ``/json/version`` until Chrome's CDP endpoint answers (or timeout)."""
    deadline = time.time() + timeout_s
    last_err = None
    while time.time() < deadline:
        try:
            _http_get_json(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return True
        except Exception as e:  # connection refused until Chrome is up
            last_err = e
            time.sleep(interval_s)
    raise CDPError(f"CDP endpoint on port {port} not ready after {timeout_s}s "
                   f"(last error: {last_err})")


class CDPSession:
    """A websocket session bound to a single CDP target."""

    def __init__(self, ws_url, timeout_s=30.0):
        self._next_id = 0
        self._ws = websocket.create_connection(ws_url, timeout=timeout_s)

    def close(self):
        try:
            self._ws.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def send(self, method, params=None):
        """Send a CDP command and block for the response with the matching id."""
        self._next_id += 1
        msg_id = self._next_id
        self._ws.send(json.dumps({"id": msg_id, "method": method,
                                  "params": params or {}}))
        while True:
            data = json.loads(self._ws.recv())
            if data.get("id") != msg_id:
                # Skip unrelated CDP events that may arrive on the same socket.
                continue
            if "error" in data:
                err = data["error"]
                raise CDPError(f"{method} failed: {err.get('message')} "
                               f"(code {err.get('code')})")
            return data.get("result", {})

    def evaluate(self, expression, return_by_value=True, await_promise=False):
        """Runtime.evaluate; returns the JS value (when return_by_value)."""
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": return_by_value,
            "awaitPromise": await_promise,
        })
        if "exceptionDetails" in result:
            exc = result["exceptionDetails"]
            text = exc.get("exception", {}).get("description") or exc.get("text")
            raise CDPError(f"JS evaluation error: {text}")
        return result.get("result", {}).get("value")


def connect_page(port, url_contains=None, timeout_s=30.0):
    """Resolve the page target on ``port`` and return an open :class:`CDPSession`."""
    targets = list_targets(port)
    target = select_page_target(targets, url_contains)
    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        raise CDPError(f"target {target.get('id')!r} has no webSocketDebuggerUrl")
    return CDPSession(ws_url, timeout_s=timeout_s)

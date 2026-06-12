"""Unit tests for scripts/cdp_client.py.

Covers the pieces that don't require a live browser:
  * select_page_target picks the first page target, honors url_contains,
    and raises CDPError on no match / empty list
  * CDPSession.send frames commands with an incrementing id, skips unrelated
    events, returns the result, and raises CDPError on a CDP error reply
"""
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "web"))

import cdp_client  # noqa: E402
from cdp_client import CDPError, select_page_target  # noqa: E402


class SelectPageTargetTests(unittest.TestCase):
    def test_picks_first_page_target(self):
        targets = [
            {"type": "background_page", "url": "chrome://x"},
            {"type": "page", "url": "https://a.example", "id": "1"},
            {"type": "page", "url": "https://b.example", "id": "2"},
        ]
        self.assertEqual(select_page_target(targets)["id"], "1")

    def test_url_contains_filters(self):
        targets = [
            {"type": "page", "url": "https://a.example", "id": "1"},
            {"type": "page", "url": "https://b.example", "id": "2"},
        ]
        self.assertEqual(select_page_target(targets, url_contains="b.exa")["id"], "2")

    def test_no_page_target_raises(self):
        with self.assertRaises(CDPError):
            select_page_target([{"type": "service_worker", "url": "x"}])

    def test_empty_list_raises(self):
        with self.assertRaises(CDPError):
            select_page_target([])

    def test_url_filter_no_match_raises(self):
        with self.assertRaises(CDPError):
            select_page_target([{"type": "page", "url": "https://a"}],
                               url_contains="zzz")

    def test_prefers_web_page_over_internal(self):
        targets = [
            {"type": "page", "url": "edge://sync-confirmation-dialog/", "id": "d"},
            {"type": "page", "url": "https://real.example", "id": "p"},
        ]
        self.assertEqual(select_page_target(targets)["id"], "p")

    def test_falls_back_to_internal_when_no_web(self):
        targets = [{"type": "page", "url": "edge://newtab/", "id": "n"}]
        self.assertEqual(select_page_target(targets)["id"], "n")


class FakeWebSocket:
    """Stand-in for a websocket-client connection used by CDPSession."""

    def __init__(self, scripted_replies):
        # scripted_replies: list of dict messages to hand back from recv()
        self._replies = list(scripted_replies)
        self.sent = []

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        return json.dumps(self._replies.pop(0))

    def close(self):
        pass


def _make_session(ws):
    session = cdp_client.CDPSession.__new__(cdp_client.CDPSession)
    session._next_id = 0
    session._ws = ws
    return session


class CDPSessionSendTests(unittest.TestCase):
    def test_send_increments_id_and_returns_result(self):
        ws = FakeWebSocket([{"id": 1, "result": {"ok": True}}])
        session = _make_session(ws)
        result = session.send("Runtime.evaluate", {"expression": "1+1"})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(ws.sent[0]["id"], 1)
        self.assertEqual(ws.sent[0]["method"], "Runtime.evaluate")
        self.assertEqual(ws.sent[0]["params"], {"expression": "1+1"})

    def test_send_skips_unrelated_events(self):
        ws = FakeWebSocket([
            {"method": "Page.frameNavigated", "params": {}},  # event, no id
            {"id": 1, "result": {"value": 42}},
        ])
        session = _make_session(ws)
        self.assertEqual(session.send("Runtime.evaluate"), {"value": 42})

    def test_send_raises_on_cdp_error(self):
        ws = FakeWebSocket([{"id": 1, "error": {"message": "boom", "code": -32000}}])
        session = _make_session(ws)
        with self.assertRaises(CDPError):
            session.send("Bad.method")

    def test_consecutive_sends_increment_id(self):
        ws = FakeWebSocket([
            {"id": 1, "result": {}},
            {"id": 2, "result": {}},
        ])
        session = _make_session(ws)
        session.send("A")
        session.send("B")
        self.assertEqual([m["id"] for m in ws.sent], [1, 2])


if __name__ == "__main__":
    unittest.main()

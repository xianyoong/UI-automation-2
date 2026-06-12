"""Navigate the active Chrome page to a URL and wait for it to finish loading.

Connects over CDP to the page target on ``--port``, issues ``Page.navigate``,
then polls ``document.readyState === 'complete'`` (bounded by --load-timeout-ms).
Prints ``url=<final>\\ttitle=<...>`` (tab-separated) on success.

Exit codes:
  0  navigated and the page reached readyState 'complete'
  1  page did not finish loading within the timeout
  2  could not connect to a page target
  3  bad usage / unexpected error
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_client  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", help="URL to navigate to")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--url-contains", dest="url_contains", default=None,
                   help="pick the page target whose current URL contains this substring")
    p.add_argument("--load-timeout-ms", dest="load_timeout_ms", type=int, default=15000)
    p.add_argument("--poll-ms", dest="poll_ms", type=int, default=150)
    a = p.parse_args()

    try:
        session = cdp_client.connect_page(a.port, a.url_contains)
    except cdp_client.CDPError as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

    with session:
        session.send("Page.enable")
        session.send("Page.navigate", {"url": a.url})

        deadline = time.time() + a.load_timeout_ms / 1000.0
        interval = max(a.poll_ms, 0) / 1000.0
        ready = False
        while time.time() < deadline:
            try:
                state = session.evaluate("document.readyState")
            except cdp_client.CDPError:
                state = None
            if state == "complete":
                ready = True
                break
            time.sleep(interval)

        final_url = session.evaluate("location.href") or a.url
        title = session.evaluate("document.title") or ""

    if not ready:
        print(f"ERROR: {a.url!r} did not reach readyState 'complete' within "
              f"{a.load_timeout_ms}ms (url={final_url!r})", file=sys.stderr)
        sys.exit(1)

    print(f"url={final_url}\ttitle={title}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(3)

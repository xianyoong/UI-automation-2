"""Launch a Chromium browser (Chrome or Edge) with a remote-debugging port.

Starts a normally-configured browser (no automation switches, so
``navigator.webdriver`` stays ``false``) with ``--remote-debugging-port`` and a
fixed ``--user-data-dir``, then polls the CDP endpoint until it answers. Prints
the launched process id on its own first line (for clean capture via
``$.cols[0]``) followed by ``port=<n>\\tpid=<n>\\tendpoint=<url>`` (tab-separated)
so a spec can capture the port for later DOM steps. ``--fresh`` wipes the profile
dir first for a clean browser (no cookies/login). ``--clone`` instead seeds the
profile dir from your real browser profile so your existing logins/cookies carry
over (without touching the live profile). Edge is Chromium, so the same CDP
helpers apply.

Exit codes:
  0  browser launched and the CDP endpoint is ready
  1  browser executable not found, or the endpoint never became ready
  3  bad usage / unexpected error
"""
import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_client  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_BROWSER_CANDIDATES = {
    "chrome": [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ],
    "edge": [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
    ],
}

# Default profile dir per browser (gitignored), so Chrome and Edge don't clash.
_DEFAULT_PROFILE = {
    "chrome": os.path.join(_REPO_ROOT, ".browser-profile"),
    "edge": os.path.join(_REPO_ROOT, ".browser-profile-edge"),
}

# Default clone target per browser (gitignored), seeded from the real profile.
_DEFAULT_CLONE_PROFILE = {
    "chrome": os.path.join(_REPO_ROOT, ".browser-profile-clone"),
    "edge": os.path.join(_REPO_ROOT, ".browser-profile-edge-clone"),
}

# The real (default) user-data dir each browser keeps your logins/cookies in.
_REAL_USER_DATA = {
    "chrome": os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data"),
    "edge": os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\User Data"),
}

# Heavy/regenerable or exclusively-locked entries skipped when cloning a profile,
# so the copy stays fast and a running browser doesn't block it.
_CLONE_SKIP_DIRS = {
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
    "DawnWebGPUCache", "ShaderCache", "GrShaderCache", "Service Worker",
    "Crashpad", "component_crx_cache", "extensions_crx_cache",
}
_CLONE_SKIP_FILE_HINTS = ("lockfile", "LOCK", "Singleton", ".lock")


def _clone_ignore(dirpath, names):
    skip = set()
    for n in names:
        full = os.path.join(dirpath, n)
        if os.path.isdir(full) and n in _CLONE_SKIP_DIRS:
            skip.add(n)
        elif any(h in n for h in _CLONE_SKIP_FILE_HINTS):
            skip.add(n)
    return skip


def clone_profile(source, target):
    """Best-effort copy of a browser user-data dir into ``target``.

    Skips cache/lock entries and ignores per-file errors so the clone works even
    while the source browser is running. Cookie/login DBs and ``Local State``
    (the DPAPI key, decryptable under the same Windows user) are copied so logins
    carry over. NOTE: while the source browser is *running*, its ``Cookies`` DB is
    exclusively locked and cannot be copied — close the browser before cloning
    (or re-clone with ``--fresh``) if you need cookie-based logins to carry over.
    """
    if not os.path.isdir(source):
        print(f"ERROR: cannot clone; source profile not found: {source}",
              file=sys.stderr)
        sys.exit(1)
    shutil.copytree(source, target, ignore=_clone_ignore,
                    dirs_exist_ok=True, copy_function=_safe_copy)
    _warn_if_cookies_locked(source, target)


def _warn_if_cookies_locked(source, target):
    """Warn if the source has cookie DBs that didn't make it into the clone."""
    missing = []
    for root, _dirs, files in os.walk(source):
        if os.path.basename(root) == "Network" and "Cookies" in files:
            rel = os.path.relpath(os.path.join(root, "Cookies"), source)
            if not os.path.exists(os.path.join(target, rel)):
                missing.append(rel)
    if missing:
        print(
            "WARNING: could not copy cookie DB(s) — the source browser is likely "
            "running and holds an exclusive lock: " + ", ".join(missing) + ". "
            "Close the browser and re-clone (e.g. with --fresh) if you need "
            "cookie-based logins to carry over.",
            file=sys.stderr,
        )


def _safe_copy(src, dst):
    try:
        shutil.copy2(src, dst)
    except OSError:
        # File locked by a running browser (e.g. open SQLite WAL); skip it.
        pass


def find_browser(browser, explicit=None):
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for path in _BROWSER_CANDIDATES.get(browser, []):
        if path and os.path.isfile(path):
            return path
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", nargs="?", default="about:blank",
                   help="initial URL to open (default about:blank)")
    p.add_argument("--browser", choices=["chrome", "edge"], default="chrome",
                   help="which Chromium browser to launch (default chrome)")
    p.add_argument("--port", type=int, default=9222,
                   help="remote-debugging port (default 9222)")
    p.add_argument("--user-data-dir", dest="user_data_dir", default=None,
                   help="profile dir (default .browser-profile[-edge], or "
                        ".browser-profile[-edge]-clone when --clone is used)")
    p.add_argument("--fresh", action="store_true",
                   help="delete the profile dir before launch for a clean browser "
                        "(with --clone, forces a re-clone)")
    p.add_argument("--clone", action="store_true",
                   help="seed the profile dir from your real browser profile so "
                        "existing logins/cookies carry over (clones only if the "
                        "target is empty unless --fresh is given)")
    p.add_argument("--clone-from", dest="clone_from", default=None,
                   help="source user-data dir to clone (default: your real "
                        "Chrome/Edge profile)")
    p.add_argument("--chrome", default=None, dest="exe",
                   help="explicit path to the browser executable")
    p.add_argument("--ready-timeout-ms", dest="ready_timeout_ms", type=int, default=15000)
    a = p.parse_args()

    exe = find_browser(a.browser, a.exe)
    if not exe:
        print(f"ERROR: {a.browser} executable not found; pass --chrome <path>",
              file=sys.stderr)
        sys.exit(1)

    if a.user_data_dir:
        profile = a.user_data_dir
    elif a.clone:
        profile = _DEFAULT_CLONE_PROFILE[a.browser]
    else:
        profile = _DEFAULT_PROFILE[a.browser]

    if a.fresh and os.path.isdir(profile):
        shutil.rmtree(profile, ignore_errors=True)

    if a.clone and not os.path.isdir(profile):
        source = a.clone_from or _REAL_USER_DATA[a.browser]
        clone_profile(source, profile)

    os.makedirs(profile, exist_ok=True)

    cmd = [
        exe,
        f"--remote-debugging-port={a.port}",
        f"--user-data-dir={profile}",
        # Chromium M111+ rejects DevTools websocket connections with HTTP 403
        # unless the connecting origin is explicitly allowed.
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        # Suppress the fresh-profile sign-in/sync confirmation dialog
        # (edge://sync-confirmation-dialog) that otherwise overlays the page.
        "--disable-sync",
        "--disable-features=msImplicitSignin",
        a.url,
    ]
    try:
        proc = subprocess.Popen(cmd)
    except OSError as e:
        print(f"ERROR: failed to launch {a.browser}: {e}", file=sys.stderr); sys.exit(1)

    try:
        cdp_client.wait_ready(a.port, timeout_s=a.ready_timeout_ms / 1000.0)
    except cdp_client.CDPError as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

    # Bare pid on its own first line for clean capture via $.cols[0],
    # followed by the human-readable port/pid/endpoint summary.
    print(proc.pid)
    print(f"port={a.port}\tpid={proc.pid}\tendpoint=http://127.0.0.1:{a.port}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(3)

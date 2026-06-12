"""Generate a self-contained HTML dashboard of test-case status.

Scans:
  test_cases/*.yaml   -> known specs (so cases that never ran still appear)
  results/*.json      -> per-run records written by run_test.py
  dashboard_meta.json -> sidecar metadata: id, category, priority, note, hold

Output:
  dashboard.html (at repo root by default)

Usage:
  uv run python scripts/dashboard.py                     # generate
  uv run python scripts/dashboard.py --open              # generate + open
  uv run python scripts/dashboard.py --hold   <spec>     # mark on-hold
  uv run python scripts/dashboard.py --resume <spec>     # clear on-hold
  uv run python scripts/dashboard.py --set <spec> <key>=<value> ...
"""
import argparse, glob, hashlib, html, json, mimetypes, os, re, subprocess, sys, threading, urllib.parse, webbrowser
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import yaml
except Exception:
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_PATH = os.path.join(ROOT, "dashboard_meta.json")

DEFAULT_PRIORITY = "P2"
DEFAULT_CATEGORY = "Smoke"

CATEGORY_HINTS = [
    ("powershell", "Smoke"),
    ("calc", "Functional"),
    ("install", "Install"),
    ("editor", "Editor"),
    ("debug", "Debug"),
    ("project", "Project"),
    ("find", "Find"),
    ("menu", "Editor"),
]

CATEGORY_COLOR = {
    "Smoke":      "#0ea5e9",
    "Functional": "#10b981",
    "Install":    "#a855f7",
    "Editor":     "#f97316",
    "Debug":      "#06b6d4",
    "Project":    "#3b82f6",
    "Find":       "#14b8a6",
    "Regression": "#ef4444",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


GALLERY_CSS = """
.gpage { background: #f4f6f8; min-height: 100vh; }
.gnav  { background: #1f2937; color: #f9fafb; padding: 14px 28px; display: flex; align-items: center; gap: 28px; }
.gnav .brand { font-weight: 700; font-size: 16px; }
.gnav a { color: #d1d5db; text-decoration: none; font-size: 14px; }
.gnav a.active, .gnav a:hover { color: #fff; }
.gnav .right { margin-left: auto; color: #9ca3af; font-size: 13px; }
.gmain { max-width: 1400px; margin: 0 auto; padding: 22px 28px 60px; font: 14px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; color: #111827; }
.gtitle { display: flex; align-items: center; gap: 10px; margin: 0 0 6px; font-size: 22px; font-weight: 700; }
.gcrumb { color: #6b7280; font-size: 13px; margin-bottom: 16px; }
.gcrumb a { color: #2563eb; text-decoration: none; }
.gcrumb a:hover { text-decoration: underline; }
.gactions { margin-bottom: 14px; display: flex; gap: 8px; flex-wrap: wrap; }
.gbtn { border: 1px solid #d1d5db; background: #fff; color: #111827; padding: 6px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500; }
.gbtn:hover { background: #f3f4f6; }
.gbtn.del { background: #fee2e2; color: #991b1b; border-color: #fecaca; }
.gbtn.del:hover { background: #fecaca; }
.gbtn.back { background: #e0e7ff; color: #1e40af; border-color: #c7d2fe; }
.gfolders { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.gfolder { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; transition: border-color .15s, transform .15s; }
.gfolder:hover { border-color: #93c5fd; transform: translateY(-1px); }
.gfolder a.flink { display: block; color: inherit; text-decoration: none; }
.gthumb { background: #f3f4f6; height: 160px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.gthumb img { max-width: 100%; max-height: 100%; object-fit: cover; width: 100%; height: 100%; }
.gthumb.empty { color: #9ca3af; font-size: 12px; }
.gfmeta { padding: 10px 12px; }
.gfmeta .name { font-weight: 600; font-size: 13px; word-break: break-all; }
.gfmeta .sub  { color: #6b7280; font-size: 12px; margin-top: 2px; }
.gfrow { display: flex; gap: 6px; padding: 0 12px 12px; }
.gimgs { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
.gimg  { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
.gimg .pic { height: 160px; background: #0f172a; display: flex; align-items: center; justify-content: center; }
.gimg .pic img { max-width: 100%; max-height: 100%; }
.gimg .meta { padding: 8px 10px; font-size: 12px; color: #374151; word-break: break-all; }
.gimg .meta .sub { color: #6b7280; margin-top: 2px; }
.gimg .gfrow { padding: 0 8px 10px; }
.gempty { padding: 48px; text-align: center; color: #6b7280; background: #fff; border: 1px dashed #d1d5db; border-radius: 8px; }
.gtoast { position: fixed; right: 24px; bottom: 24px; background: #111827; color: #fff; padding: 10px 16px; border-radius: 6px; font-size: 13px; opacity: 0; transition: opacity .25s; pointer-events: none; max-width: 480px; }
.gtoast.show { opacity: 1; }
"""

GALLERY_JS = """
function gtoast(msg, kind) {
  let t = document.getElementById('gtoast');
  if (!t) {
    t = document.createElement('div'); t.id = 'gtoast'; t.className = 'gtoast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(window._gToast);
  window._gToast = setTimeout(() => t.classList.remove('show'), 2400);
}
async function gApi(path, params) {
  const body = new URLSearchParams(params || {});
  const res = await fetch(path, { method: 'POST', body });
  if (!res.ok) throw new Error(await res.text());
  try { return await res.json(); } catch { return {}; }
}
async function delImage(path) {
  if (!confirm('Delete this image?\\n' + path)) return;
  try {
    await gApi('/api/delete_image', { path });
    gtoast('Deleted ' + path);
    setTimeout(() => location.reload(), 350);
  } catch (e) { gtoast('Failed: ' + e.message); }
}
async function delFolder(path) {
  if (!confirm('Delete the entire folder and all images inside?\\n' + path)) return;
  try {
    await gApi('/api/delete_folder', { path });
    gtoast('Deleted ' + path);
    // Navigate up one level
    const parts = path.split('/'); parts.pop();
    setTimeout(() => location.href = '/' + parts.join('/') + (parts.length ? '/' : ''), 350);
  } catch (e) { gtoast('Failed: ' + e.message); }
}
"""


def _list_dir(full):
    """Return (dirs, files) sorted, with name + size for files."""
    dirs, files = [], []
    try:
        for name in sorted(os.listdir(full)):
            p = os.path.join(full, name)
            if name.startswith("."):
                continue
            if os.path.isdir(p):
                dirs.append(name)
            else:
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    sz = 0
                files.append((name, sz))
    except OSError:
        pass
    return dirs, files


def _is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def _crumbs(rel):
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    out = ['<a href="/">Dashboard</a>']
    cur = ""
    for i, p in enumerate(parts):
        cur = cur + "/" + p
        if i == len(parts) - 1:
            out.append(f'<span>{html.escape(p)}</span>')
        else:
            out.append(f'<a href="{cur}/">{html.escape(p)}</a>')
    return ' <span style="color:#9ca3af">/</span> '.join(out)


def render_gallery(rel, full):
    """Render a screenshots gallery (folder list or image grid)."""
    dirs, files = _list_dir(full)
    rel_norm = rel.rstrip("/").replace("\\", "/")
    is_root = rel_norm in ("screenshots", "")
    parent = "/".join(rel_norm.split("/")[:-1])
    parent_url = "/" + parent + "/" if parent else "/"

    # ---- folder cards (each subfolder gets a preview thumbnail) -----
    folder_cards = []
    for d in dirs:
        sub_full = os.path.join(full, d)
        sub_dirs, sub_files = _list_dir(sub_full)
        imgs = [n for n, _ in sub_files if _is_image(n)]
        first = imgs[0] if imgs else None
        thumb_html = (
            f'<div class="gthumb"><img loading="lazy" src="/{rel_norm}/{html.escape(d)}/{html.escape(first)}"></div>'
            if first else
            f'<div class="gthumb empty">📁 (no preview)</div>'
        )
        folder_path = f"{rel_norm}/{d}"
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(sub_full)).strftime("%Y-%m-%d %H:%M")
        except OSError:
            mtime = ""
        folder_cards.append(
            f'<div class="gfolder">'
            f'  <a class="flink" href="/{folder_path}/">'
            f'    {thumb_html}'
            f'    <div class="gfmeta">'
            f'      <div class="name">📁 {html.escape(d)}</div>'
            f'      <div class="sub">{len(imgs)} image(s) · {mtime}</div>'
            f'    </div>'
            f'  </a>'
            f'  <div class="gfrow">'
            f'    <a class="gbtn" href="/{folder_path}/">Open</a>'
            f'    <button class="gbtn del" onclick="delFolder(\'{folder_path}\')">🗑 Delete folder</button>'
            f'  </div>'
            f'</div>'
        )

    # ---- image cards ------------------------------------------------
    image_cards = []
    image_files = [(n, sz) for (n, sz) in files if _is_image(n)]
    other_files = [(n, sz) for (n, sz) in files if not _is_image(n)]
    for n, sz in image_files:
        img_path = f"{rel_norm}/{n}"
        image_cards.append(
            f'<div class="gimg">'
            f'  <a class="pic" href="/{img_path}" target="_blank"><img loading="lazy" src="/{img_path}"></a>'
            f'  <div class="meta">{html.escape(n)}<div class="sub">{_human_size(sz)}</div></div>'
            f'  <div class="gfrow">'
            f'    <a class="gbtn" href="/{img_path}" target="_blank">View</a>'
            f'    <a class="gbtn" href="/{img_path}" download>Download</a>'
            f'    <button class="gbtn del" onclick="delImage(\'{img_path}\')">🗑 Delete</button>'
            f'  </div>'
            f'</div>'
        )

    # ---- assemble ---------------------------------------------------
    body_parts = []
    if not dirs and not files:
        body_parts.append('<div class="gempty">📷 No screenshots yet. Run a test to capture some.</div>')
    if folder_cards:
        body_parts.append('<h3 style="margin:14px 0 10px">Folders</h3>')
        body_parts.append(f'<div class="gfolders">{"".join(folder_cards)}</div>')
    if image_cards:
        if folder_cards:
            body_parts.append('<h3 style="margin:22px 0 10px">Images</h3>')
        body_parts.append(f'<div class="gimgs">{"".join(image_cards)}</div>')
    if other_files:
        rows = "".join(
            f'<li><a href="/{rel_norm}/{html.escape(n)}">{html.escape(n)}</a> '
            f'<span style="color:#6b7280">({_human_size(sz)})</span></li>'
            for n, sz in other_files
        )
        body_parts.append(f'<h3 style="margin:22px 0 10px">Other files</h3><ul>{rows}</ul>')

    actions = ['<a class="gbtn back" href="/">← Dashboard</a>']
    if not is_root:
        actions.append(f'<a class="gbtn back" href="{parent_url}">↑ Up</a>')
        actions.append(f'<button class="gbtn del" onclick="delFolder(\'{rel_norm}\')">🗑 Delete this folder</button>')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Screenshots — {html.escape(rel_norm)}</title>
<style>{GALLERY_CSS}</style>
</head>
<body class="gpage">
<nav class="gnav">
  <span class="brand">🐛 VS UI Test Dashboard</span>
  <a href="/">Dashboard</a>
  <a href="#">Daily Install</a>
  <a class="active" href="/screenshots/">Screenshots</a>
  <a href="#">🖥️ Remote VMs</a>
  <span class="right">Powered by Copilot CLI</span>
</nav>
<main class="gmain">
  <h1 class="gtitle">📷 Screenshots</h1>
  <div class="gcrumb">{_crumbs(rel_norm)}</div>
  <div class="gactions">{''.join(actions)}</div>
  {''.join(body_parts)}
</main>
<script>{GALLERY_JS}</script>
</body></html>
"""


# ---------------------------------------------------------------- meta sidecar
def load_meta():
    if not os.path.exists(META_PATH):
        return {}
    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_meta(meta):
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


def auto_meta(spec_rel, name):
    """Derive defaults for a spec when no sidecar entry exists."""
    base = os.path.splitext(os.path.basename(spec_rel))[0]
    cat = DEFAULT_CATEGORY
    for hint, c in CATEGORY_HINTS:
        if hint in base.lower():
            cat = c
            break
    # Stable 3-digit ID from sha1 of the spec path
    h = hashlib.sha1(spec_rel.encode("utf-8")).hexdigest()
    num = int(h[:6], 16) % 1000
    prefix_map = {"Smoke": "SMK", "Functional": "FUN", "Install": "INS",
                  "Editor": "EDT", "Debug": "DBG", "Project": "PRJ",
                  "Find": "FND", "Regression": "REG"}
    prefix = prefix_map.get(cat, "TC")
    tcid = f"TC-{prefix}-{num:03d}"
    return {
        "id": tcid,
        "category": cat,
        "priority": DEFAULT_PRIORITY,
        "note": "",
        "hold": False,
    }


# ------------------------------------------------------------------ data load
def load_results():
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "results", "*.json"))):
        try:
            with open(p, "r", encoding="utf-8") as f:
                rec = json.load(f)
            rec["_path"] = os.path.relpath(p, ROOT).replace("\\", "/")
            out.append(rec)
        except Exception as e:
            print(f"WARN: skipping {p}: {e}", file=sys.stderr)
    return out


def load_specs():
    specs = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "test_cases", "*.yaml"))):
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        info = {"spec": rel, "name": os.path.basename(p),
                "description": "", "total_steps": 0}
        if yaml is not None:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                info["name"] = data.get("name", info["name"])
                info["description"] = data.get("description", "")
                info["total_steps"] = len(data.get("steps", []))
            except Exception:
                pass
        specs[rel] = info
    return specs


def aggregate(specs, runs, meta):
    by_spec = defaultdict(list)
    for r in runs:
        by_spec[r.get("spec", "")].append(r)
    rows = []
    for spec_key, info in specs.items():
        history = sorted(by_spec.get(spec_key, []),
                         key=lambda r: r.get("started_at", ""), reverse=True)
        latest = history[0] if history else None
        m = dict(auto_meta(spec_key, info["name"]))
        m.update(meta.get(spec_key, {}))
        passes = sum(1 for r in history if r.get("result") == "PASS")
        fails  = sum(1 for r in history if r.get("result") == "FAIL")
        if m.get("hold"):
            status = "HOLD"
        elif not history:
            status = "NOT RUN"
        elif latest.get("result") == "PASS":
            status = "PASS"
        elif latest.get("result") == "FAIL":
            status = "FAIL"
        else:
            status = "STOPPED"
        rows.append({
            "spec": spec_key, "name": info["name"],
            "description": info["description"],
            "total_steps": info["total_steps"],
            "latest": latest, "history": history,
            "runs": len(history), "passes": passes, "fails": fails,
            "meta": m, "status": status,
        })
    rows.sort(key=lambda r: (r["meta"]["priority"], r["meta"]["id"]))
    return rows


def _utcnow():
    try:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


def last_n_days(runs, n=7):
    today = _utcnow().date()
    days = [(today - timedelta(days=i)) for i in range(n - 1, -1, -1)]
    p = {d: 0 for d in days}
    f = {d: 0 for d in days}
    for r in runs:
        try:
            d = datetime.strptime(r.get("started_at", ""), "%Y-%m-%dT%H:%M:%SZ").date()
        except Exception:
            continue
        if d not in p:
            continue
        if r.get("result") == "PASS":
            p[d] += 1
        elif r.get("result") == "FAIL":
            f[d] += 1
    return [(d, p[d], f[d]) for d in days]


# ------------------------------------------------------------------- helpers
def esc(s):
    return html.escape(str(s) if s is not None else "")


def fmt_dur(s):
    if s is None:
        return "—"
    try:
        s = float(s)
    except Exception:
        return "—"
    if s < 1:
        return f"{int(s*1000)} ms"
    if s < 60:
        return f"{s:.1f} s"
    m, sec = divmod(s, 60)
    return f"{int(m)}m {sec:.0f}s"


def fmt_time(t):
    if not t:
        return "—"
    try:
        return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return t


# ----------------------------------------------------------------- SVG chart
def _nice_ticks(peak, target=5):
    """Integer ticks from 0 up to >= peak, ~target steps, using 1/2/5 * 10^k."""
    import math
    if peak <= 0:
        return [0, 1]
    raw = peak / target
    pow10 = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = pow10
    for m in (1, 2, 5, 10):
        step = m * pow10
        if peak / step <= target:
            break
    step = max(1, int(round(step)))
    top = step * math.ceil(peak / step)
    return list(range(0, int(top) + step, step))


def build_chart(buckets, height=240):
    W = 1100
    H = max(140, int(height))
    pad_l, pad_r, pad_t, pad_b = 64, 40, 24, 40
    inner_w = W - pad_l - pad_r
    inner_h = H - pad_t - pad_b
    n = len(buckets)
    if n == 0:
        return f'<svg id="runs-chart" viewBox="0 0 {W} {H}"></svg>'
    peak = max((max(p, f) for _, p, f in buckets), default=0)
    ticks = _nice_ticks(peak)
    top = ticks[-1] if ticks else 1
    xs = [pad_l + (inner_w * i / (n - 1) if n > 1 else inner_w / 2) for i in range(n)]
    def y_of(v):
        return pad_t + inner_h * (1 - v / top)
    gridlines = "".join(
        f'<line x1="{pad_l}" y1="{y_of(t):.1f}" x2="{W - pad_r}" y2="{y_of(t):.1f}" '
        f'stroke="#e5e7eb" stroke-dasharray="3,3"/>'
        for t in ticks
    )
    y_labels = "".join(
        f'<text x="{pad_l - 8}" y="{y_of(t) + 4:.1f}" text-anchor="end" '
        f'fill="#374151" font-size="12">{t}</text>'
        for t in ticks
    )
    y_title = (
        f'<text x="18" y="{pad_t + inner_h/2:.1f}" fill="#374151" font-size="12" '
        f'text-anchor="middle" font-weight="600" '
        f'transform="rotate(-90 18 {pad_t + inner_h/2:.1f})"># of runs</text>'
    )
    pass_pts = " ".join(f"{xs[i]:.1f},{y_of(p):.1f}" for i, (_, p, _) in enumerate(buckets))
    fail_pts = " ".join(f"{xs[i]:.1f},{y_of(f):.1f}" for i, (_, _, f) in enumerate(buckets))
    x_labels = "".join(
        f'<text x="{xs[i]:.1f}" y="{H - 12}" text-anchor="middle" '
        f'fill="#374151" font-size="12">{d.strftime("%m/%d")}</text>'
        for i, (d, _, _) in enumerate(buckets)
    )
    pass_dots = "".join(
        f'<circle cx="{xs[i]:.1f}" cy="{y_of(p):.1f}" r="4" fill="#10b981">'
        f'<title>{d.strftime("%Y-%m-%d")}: {p} passed</title></circle>'
        for i, (d, p, _) in enumerate(buckets)
    )
    fail_dots = "".join(
        f'<circle cx="{xs[i]:.1f}" cy="{y_of(f):.1f}" r="4" fill="#ef4444">'
        f'<title>{d.strftime("%Y-%m-%d")}: {f} failed</title></circle>'
        for i, (d, _, f) in enumerate(buckets)
    )
    return f'''<svg id="runs-chart" viewBox="0 0 {W} {H}" preserveAspectRatio="none" style="width:100%;height:{H}px">
  {gridlines}
  <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{H - pad_b}" stroke="#9ca3af"/>
  <line x1="{pad_l}" y1="{H - pad_b}" x2="{W - pad_r}" y2="{H - pad_b}" stroke="#9ca3af"/>
  {y_labels}
  {y_title}
  <polyline fill="none" stroke="#10b981" stroke-width="2" points="{pass_pts}"/>
  <polyline fill="none" stroke="#ef4444" stroke-width="2" points="{fail_pts}"/>
  {pass_dots}{fail_dots}{x_labels}
</svg>'''


# --------------------------------------------------------------------- styles
CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font: 14px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; color: #111827; }
.nav { background: #1f2937; color: #f9fafb; padding: 14px 28px; display: flex; align-items: center; gap: 28px; }
.nav .brand { font-weight: 700; font-size: 16px; display: flex; align-items: center; gap: 8px; }
.nav a { color: #d1d5db; text-decoration: none; font-size: 14px; }
.nav a.active, .nav a:hover { color: #fff; }
.nav .right { margin-left: auto; color: #9ca3af; font-size: 13px; }
main { max-width: 1400px; margin: 0 auto; padding: 22px 28px 60px; }
.title-row { display: flex; align-items: center; margin-bottom: 16px; gap: 12px; flex-wrap: wrap; }
.title-row h1 { margin: 0; font-size: 22px; font-weight: 700; }
.title-row h1 .ico { margin-right: 6px; }
.actions { margin-left: auto; display: flex; gap: 8px; }
.btn { border: 1px solid #d1d5db; background: #fff; color: #111827; padding: 8px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-weight: 500; }
.btn:hover { background: #f3f4f6; }
.btn.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
.btn.primary:hover { background: #1d4ed8; }
.btn.green { background: #16a34a; color: #fff; border-color: #16a34a; }
.btn.green:hover { background: #15803d; }
.btn.sm { padding: 4px 10px; font-size: 12px; }
.btn.icon { padding: 4px 8px; }
.cards { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin-bottom: 14px; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 18px 20px; text-align: center; }
.card .lbl { font-size: 12px; letter-spacing: .8px; font-weight: 600; color: #6b7280; }
.card .num { font-size: 32px; font-weight: 700; margin-top: 6px; color: #111827; }
.card.passed { background: #16a34a; border-color: #16a34a; }
.card.failed { background: #dc2626; border-color: #dc2626; }
.card.hold   { background: #eab308; border-color: #eab308; }
.card.notrun { background: #6b7280; border-color: #6b7280; }
.card.passed .lbl, .card.passed .num,
.card.failed .lbl, .card.failed .num,
.card.hold .lbl,   .card.hold .num,
.card.notrun .lbl, .card.notrun .num { color: #fff; }
.last-run { color: #6b7280; font-size: 13px; margin-bottom: 14px; }
.panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px 20px; margin-bottom: 18px; }
.panel-h { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.panel-h .t { font-weight: 600; font-size: 14px; }
.legend span { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-right: 6px; }
.legend .p { background: #d1fae5; color: #065f46; }
.legend .f { background: #fee2e2; color: #991b1b; }
.legend .peak { color: #6b7280; font-size: 12px; margin-left: 8px; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
th, td { padding: 12px 14px; text-align: left; border-bottom: 1px solid #f1f5f9; vertical-align: middle; font-size: 13px; }
th { background: #f9fafb; font-weight: 600; font-size: 12px; color: #374151; text-transform: none; letter-spacing: 0; }
tbody tr:last-child td { border-bottom: none; }
.badge { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; letter-spacing: .3px; text-transform: uppercase; }
.badge.PASS    { background: #16a34a; color: #fff; }
.badge.FAIL    { background: #dc2626; color: #fff; }
.badge.HOLD    { background: #eab308; color: #422006; }
.badge.STOPPED { background: #111827; color: #fff; }
.badge.NOTRUN  { background: #6b7280; color: #fff; }
.cat { display: inline-block; padding: 3px 10px; border-radius: 14px; font-size: 11px; font-weight: 600; color: #fff; }
.pri { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; color: #374151; background: #e5e7eb; }
.tcid { color: #2563eb; font-weight: 600; font-family: ui-monospace, Consolas, monospace; }
.note { color: #4b5563; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-actions { display: flex; gap: 4px; flex-wrap: nowrap; justify-content: flex-end; }
.row-actions .btn { padding: 4px 10px; font-size: 12px; }
.btn.run     { background: #16a34a; color: #fff; border-color: #16a34a; }
.btn.run:hover { background: #15803d; }
.btn.hold    { background: #fef3c7; color: #92400e; border-color: #fde68a; }
.btn.resume  { background: #fef3c7; color: #92400e; border-color: #fde68a; }
.btn.del     { background: #fee2e2; color: #991b1b; border-color: #fecaca; }
.btn.del:hover { background: #fecaca; }
.toast { position: fixed; right: 24px; bottom: 24px; background: #111827; color: #fff; padding: 10px 16px; border-radius: 6px; font-size: 13px; opacity: 0; transition: opacity .25s; pointer-events: none; max-width: 480px; }
.toast.show { opacity: 1; }
.detail-row td { background: #fafafa; padding: 0; border-bottom: 1px solid #e5e7eb; }
.detail-row .inner { padding: 12px 18px; }
.steps { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
.step { padding: 2px 0; }
.step.pass { color: #047857; }
.step.fail { color: #b91c1c; }
.muted { color: #6b7280; }
.hidden { display: none; }
.history-table { width: 100%; margin-top: 8px; font-size: 12px; }
.history-table th, .history-table td { padding: 6px 8px; }
"""

JS = """
const SERVER_MODE = (location.protocol === 'http:' || location.protocol === 'https:');
function toast(msg, kind) {
  let t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (kind ? ' ' + kind : '');
  clearTimeout(window._toastT);
  window._toastT = setTimeout(() => t.className = 'toast', 2800);
}
async function copyCmd(cmd) {
  try {
    await navigator.clipboard.writeText(cmd);
    toast('Copied: ' + cmd);
  } catch (e) {
    toast('Run in PowerShell: ' + cmd);
  }
}
async function api(path, params) {
  const body = new URLSearchParams(params || {});
  const res = await fetch(path, {method: 'POST', body});
  if (!res.ok) throw new Error(await res.text());
  try { return await res.json(); } catch { return {}; }
}
async function runSpec(spec) {
  if (!SERVER_MODE) {
    return copyCmd('.\\\\run.ps1 ' + spec + ' -q');
  }
  try {
    toast('▶ Launching PowerShell for ' + spec + ' ...', 'info');
    await api('/api/run', {spec});
    toast('PowerShell window opened. Reloading in 6 s …', 'info');
    setTimeout(() => location.reload(), 6000);
  } catch (e) { toast('Run failed: ' + e.message, 'err'); }
}
async function runAll() {
  if (!SERVER_MODE) {
    return copyCmd('Get-ChildItem test_cases\\\\*.yaml | ForEach-Object { .\\\\run.ps1 $_.FullName -q }');
  }
  try {
    toast('▶ Running all test cases …', 'info');
    await api('/api/run_all', {});
    toast('Launched. Refresh in a moment to see results.', 'info');
    setTimeout(() => location.reload(), 8000);
  } catch (e) { toast('Run all failed: ' + e.message, 'err'); }
}
async function holdSpec(spec, hold) {
  if (!SERVER_MODE) {
    return copyCmd('uv run python scripts/dashboard.py --' + (hold ? 'hold' : 'resume') + ' ' + spec);
  }
  try {
    await api(hold ? '/api/hold' : '/api/resume', {spec});
    toast(hold ? 'Marked on hold' : 'Resumed', 'info');
    setTimeout(() => location.reload(), 400);
  } catch (e) { toast('Failed: ' + e.message, 'err'); }
}
async function deleteSpec(spec) {
  if (!confirm('Delete ' + spec + ' ?')) return;
  if (!SERVER_MODE) {
    return copyCmd('Remove-Item ' + spec);
  }
  try {
    await api('/api/delete', {spec});
    toast('Deleted ' + spec, 'info');
    setTimeout(() => location.reload(), 400);
  } catch (e) { toast('Delete failed: ' + e.message, 'err'); }
}
function editSpec(spec) {
  if (!SERVER_MODE) {
    return copyCmd('code ' + spec);
  }
  api('/api/edit', {spec})
    .then(() => toast('Opened in editor'))
    .catch(e => copyCmd('code ' + spec));
}
function newCase() {
  copyCmd('uv run python scripts/author_test.py test_cases/new_scenario.yaml');
}
function toggleDetails(idx) {
  const r = document.getElementById('det-' + idx);
  if (r) r.classList.toggle('hidden');
}
function refresh() { location.reload(); }
function resizeChart(h) {
  const el = document.getElementById('runs-chart');
  if (el) el.style.height = h + 'px';
  const lbl = document.getElementById('chart-h-val');
  if (lbl) lbl.textContent = h + ' px';
  try { localStorage.setItem('chartHeight', h); } catch(_) {}
}
window.addEventListener('DOMContentLoaded', () => {
  try {
    const saved = localStorage.getItem('chartHeight');
    if (saved) {
      const s = document.getElementById('chart-h');
      if (s) { s.value = saved; resizeChart(saved); }
    }
  } catch(_) {}
});
"""


# ------------------------------------------------------------------ rendering
def render_history(row, idx):
    if not row["history"]:
        body = '<div class="muted">No runs recorded yet.</div>'
    else:
        rows_html = []
        for r in row["history"][:10]:
            result = r.get("result", "?")
            badge_cls = "NOTRUN" if result not in ("PASS", "FAIL") else result
            shot = r.get("screenshot_dir", "")
            shot_link = f'<a href="{esc(shot)}/" target="_blank">view</a>' if shot else "—"
            rec_link = f'<a href="{esc(r.get("_path",""))}" target="_blank">json</a>'
            rows_html.append(
                f'<tr><td>{esc(fmt_time(r.get("started_at")))}</td>'
                f'<td><span class="badge {badge_cls}">{esc(result)}</span></td>'
                f'<td>{esc(fmt_dur(r.get("duration_s")))}</td>'
                f'<td>{esc(r.get("failed_step_id") or "—")}</td>'
                f'<td>{shot_link}</td><td>{rec_link}</td></tr>'
            )
        steps_html = ""
        if row["latest"] and row["latest"].get("steps"):
            parts = ['<div class="steps" style="margin-top:10px"><div class="muted" style="margin-bottom:4px">Latest run steps:</div>']
            for st in row["latest"]["steps"]:
                cls = "pass" if st.get("status") == "pass" else "fail"
                mark = "✓" if cls == "pass" else "✗"
                err = f' — {esc(st.get("error"))}' if st.get("error") else ""
                parts.append(
                    f'<div class="step {cls}">{mark} [{esc(st.get("id"))}] '
                    f'({esc(st.get("type"))}) {esc(st.get("description"))} '
                    f'<span class="muted">{esc(fmt_dur(st.get("duration_s")))}</span>{err}</div>'
                )
            parts.append('</div>')
            steps_html = "".join(parts)
        body = (
            '<table class="history-table"><thead><tr>'
            '<th>Started</th><th>Result</th><th>Duration</th>'
            '<th>Failed Step</th><th>Screenshots</th><th>Record</th>'
            '</tr></thead><tbody>'
            + "".join(rows_html) + '</tbody></table>' + steps_html
        )
    return (
        f'<tr id="det-{idx}" class="detail-row hidden">'
        f'<td colspan="8"><div class="inner">'
        f'<div style="margin-bottom:6px"><strong>{esc(row["name"])}</strong> '
        f'<span class="muted">— {esc(row["spec"])}</span></div>'
        f'<div class="muted" style="margin-bottom:8px">{esc(row["description"]) or ""}</div>'
        f'{body}</div></td></tr>'
    )


def render_row(row, idx):
    m = row["meta"]
    status = row["status"]
    badge_cls = status.replace(" ", "")
    cat = m["category"]
    cat_color = CATEGORY_COLOR.get(cat, "#6b7280")
    spec = row["spec"]
    last_run = fmt_time((row["latest"] or {}).get("started_at")) if row["latest"] else "—"
    note = m.get("note") or ((row["latest"] or {}).get("failed_step_error") or "")
    note_short = (note[:60] + "…") if len(note) > 60 else note
    is_hold = m.get("hold", False)
    hold_btn = (f'<button class="btn resume" onclick="holdSpec(&quot;{esc(spec)}&quot;, false)">Resume</button>'
                if is_hold else
                f'<button class="btn hold" onclick="holdSpec(&quot;{esc(spec)}&quot;, true)">Hold</button>')
    return (
        f'<tr><td><span class="badge {badge_cls}">{esc(status)}</span></td>'
        f'<td><span class="tcid">{esc(m["id"])}</span></td>'
        f'<td>{esc(row["name"])}</td>'
        f'<td><span class="cat" style="background:{cat_color}">{esc(cat)}</span></td>'
        f'<td><span class="pri">{esc(m["priority"])}</span></td>'
        f'<td>{esc(last_run)}</td>'
        f'<td class="note" title="{esc(note)}">{esc(note_short)}</td>'
        f'<td><div class="row-actions">'
        f'<button class="btn" onclick="toggleDetails({idx})">Details</button>'
        f'<button class="btn run" onclick="runSpec(&quot;{esc(spec)}&quot;)">▶ Run</button>'
        f'<button class="btn icon" onclick="editSpec(&quot;{esc(spec)}&quot;)" title="Edit YAML">✎</button>'
        f'{hold_btn}'
        f'<button class="btn del icon" onclick="deleteSpec(&quot;{esc(spec)}&quot;)" title="Delete">🗑</button>'
        f'</div></td></tr>'
    )


def build_html(rows, runs):
    total = len(rows)
    passed = sum(1 for r in rows if r["status"] == "PASS")
    failed = sum(1 for r in rows if r["status"] == "FAIL")
    hold   = sum(1 for r in rows if r["status"] == "HOLD")
    notrun = sum(1 for r in rows if r["status"] == "NOT RUN")
    last_run = max((r["latest"]["started_at"] for r in rows if r["latest"]), default="")
    buckets = last_n_days(runs, 7)
    chart_svg = build_chart(buckets)
    peak = max((max(p, f) for _, p, f in buckets), default=0)
    total_runs = sum(p + f for _, p, f in buckets)
    total_pass_runs = sum(p for _, p, _ in buckets)
    total_fail_runs = sum(f for _, _, f in buckets)
    today_pass = buckets[-1][1] if buckets else 0
    today_fail = buckets[-1][2] if buckets else 0

    table_rows = []
    for i, r in enumerate(rows):
        table_rows.append(render_row(r, i))
        table_rows.append(render_history(r, i))
    rows_html = "".join(table_rows) if rows else (
        '<tr><td colspan="8" class="muted" style="padding:24px;text-align:center">'
        'No test cases found in test_cases/</td></tr>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>VS UI Test Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<nav class="nav">
  <span class="brand">🐛 VS UI Test Dashboard</span>
  <a href="#" class="active">Dashboard</a>
  <a href="#">Daily Install</a>
  <a href="/screenshots/" target="_blank">Screenshots</a>
  <a href="#">🖥️ Remote VMs</a>
  <span class="right">Powered by Copilot CLI</span>
</nav>
<main>
  <div class="title-row">
    <h1><span class="ico">📊</span>Test Suite Status</h1>
    <div class="actions">
      <button class="btn primary" onclick="newCase()">+ New Test Case</button>
      <button class="btn green" onclick="runAll()">▶ Run All</button>
      <button class="btn" onclick="refresh()">↻ Refresh</button>
    </div>
  </div>

  <div class="cards">
    <div class="card"><div class="lbl">TOTAL</div><div class="num">{total}</div></div>
    <div class="card passed"><div class="lbl">PASSED</div><div class="num">{passed}</div></div>
    <div class="card failed"><div class="lbl">FAILED</div><div class="num">{failed}</div></div>
    <div class="card hold"><div class="lbl">ON HOLD</div><div class="num">{hold}</div></div>
    <div class="card notrun"><div class="lbl">NOT RUN</div><div class="num">{notrun}</div></div>
  </div>

  <div class="last-run">Last run: {esc(fmt_time(last_run))}</div>

  <div class="panel">
    <div class="panel-h">
      <div class="t">📈 Last 7 days — runs per day</div>
      <div class="legend">
        <span class="p">passed</span><span class="f">failed</span><span class="peak">peak: {peak}/day</span>
        <span style="margin-left:14px;color:#6b7280;font-size:12px">Height
          <input type="range" id="chart-h" min="160" max="700" value="240" step="20"
                 oninput="resizeChart(this.value)" style="vertical-align:middle;width:140px">
          <span id="chart-h-val">240 px</span>
        </span>
      </div>
    </div>
    {chart_svg}
    <div style="margin-top:8px;padding:8px 12px;background:#f9fafb;border-radius:6px;font-size:12px;color:#4b5563;line-height:1.6">
      <strong>Today (UTC):</strong>
      <span style="color:#047857;font-weight:600">{today_pass} passed</span> ·
      <span style="color:#b91c1c;font-weight:600">{today_fail} failed</span> ·
      <span class="muted">{today_pass + today_fail} run(s)</span>
      &nbsp;|&nbsp; <strong>Last 7 days:</strong> {total_pass_runs} pass / {total_fail_runs} fail ({total_runs} runs)
      <div style="margin-top:4px;color:#6b7280">
        ℹ️ This chart counts <em>every execution</em>. The cards above count <em>unique test cases</em>
        by the result of their <em>latest</em> run — so a case that failed 13 times then passed once is
        13 reds + 1 green here, but <strong>PASSED</strong> in the cards.
      </div>
    </div>
  </div>

  <table>
    <thead><tr>
      <th>Status</th><th>ID</th><th>Title</th><th>Category</th>
      <th>Priority</th><th>Last Run</th><th>Note</th>
      <th style="text-align:right">Actions</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</main>
<div id="toast" class="toast"></div>
<script>{JS}</script>
</body></html>
"""


# --------------------------------------------------------------------- entry
def cmd_set(args):
    meta = load_meta()
    rel = args.spec.replace("\\", "/")
    entry = meta.get(rel, {})
    for kv in args.kv:
        if "=" not in kv:
            print(f"skip {kv!r}: expected key=value", file=sys.stderr)
            continue
        k, v = kv.split("=", 1)
        if v.lower() in ("true", "false"):
            v = v.lower() == "true"
        entry[k] = v
    meta[rel] = entry
    save_meta(meta)
    print(f"updated {rel}: {entry}")


def cmd_hold(args, hold):
    meta = load_meta()
    rel = args.spec.replace("\\", "/")
    entry = meta.get(rel, {})
    entry["hold"] = hold
    meta[rel] = entry
    save_meta(meta)
    print(f"{'HOLD' if hold else 'RESUME'} {rel}")


# ============================================================ HTTP server ===
def _spawn_run(spec_rel):
    """Open a new PowerShell console window and run the test there.
    Returns immediately so the dashboard stays responsive.
    """
    ps_cmd = (
        f"Set-Location -LiteralPath '{ROOT}'; "
        f"Write-Host '> .\\run.ps1 {spec_rel}' -ForegroundColor Cyan; "
        f".\\run.ps1 '{spec_rel}'; "
        f"Write-Host ''; Write-Host 'Press Enter to close...' -ForegroundColor Yellow; "
        f"[void][System.Console]::ReadLine()"
    )
    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000010  # CREATE_NEW_CONSOLE
    return subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", ps_cmd],
        creationflags=creationflags, cwd=ROOT,
    )


def _spawn_run_all():
    ps_cmd = (
        f"Set-Location -LiteralPath '{ROOT}'; "
        f"$specs = Get-ChildItem test_cases\\*.yaml; "
        f"foreach ($s in $specs) {{ "
        f"  Write-Host ('=== ' + $s.Name + ' ===') -ForegroundColor Cyan; "
        f"  & .\\run.ps1 $s.FullName -q "
        f"}}; "
        f"Write-Host ''; Write-Host 'All done. Press Enter to close...' -ForegroundColor Yellow; "
        f"[void][System.Console]::ReadLine()"
    )
    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000010
    return subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", ps_cmd],
        creationflags=creationflags, cwd=ROOT,
    )


def _safe_path(rel):
    """Return absolute path inside ROOT, or None if it would escape."""
    full = os.path.normpath(os.path.join(ROOT, rel))
    if not full.startswith(os.path.normpath(ROOT)):
        return None
    return full


def make_handler():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write("[dash] " + (fmt % args) + "\n")

        # ---- helpers -----------------------------------------------------
        def _send_json(self, code, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, code, body, ctype="text/html; charset=utf-8"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_404(self, msg="not found"):
            self._send_bytes(404, msg, "text/plain; charset=utf-8")

        def _read_form(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            return urllib.parse.parse_qs(raw)

        # ---- routes ------------------------------------------------------
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(url.path)
            if path in ("/", "/dashboard.html", "/index.html"):
                specs = load_specs(); runs = load_results(); meta = load_meta()
                rows = aggregate(specs, runs, meta)
                return self._send_bytes(200, build_html(rows, runs))
            if path == "/api/ping":
                return self._send_json(200, {"ok": True})
            # Static files (results/, screenshots/, test_cases/, dashboard_meta.json)
            rel = path.lstrip("/")
            if not rel:
                return self._send_404()
            allowed = ("results/", "screenshots/", "test_cases/", "docs/")
            if not (rel.startswith(allowed) or rel == "dashboard_meta.json"):
                return self._send_404()
            full = _safe_path(rel)
            if not full or not os.path.exists(full):
                return self._send_404()
            if os.path.isdir(full):
                # Render gallery for screenshots/ paths; plain listing otherwise
                if rel.split("/")[0] == "screenshots":
                    return self._send_bytes(200, render_gallery(rel, full))
                items = sorted(os.listdir(full))
                links = "".join(
                    f'<li><a href="{html.escape(i)}{"/" if os.path.isdir(os.path.join(full,i)) else ""}">{html.escape(i)}</a></li>'
                    for i in items
                )
                return self._send_bytes(200, f"<h2>{html.escape(rel)}</h2><ul>{links}</ul>")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                data = f.read()
            return self._send_bytes(200, data, ctype)

        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            path = url.path
            form = self._read_form()
            spec = (form.get("spec", [""])[0] or "").replace("\\", "/")

            if path == "/api/run":
                if not spec:
                    return self._send_json(400, {"error": "missing spec"})
                full = _safe_path(spec)
                if not full or not os.path.exists(full):
                    return self._send_json(404, {"error": f"no such spec: {spec}"})
                try:
                    p = _spawn_run(spec)
                    return self._send_json(202, {"ok": True, "pid": p.pid, "spec": spec})
                except Exception as e:
                    return self._send_json(500, {"error": str(e)})

            if path == "/api/run_all":
                try:
                    p = _spawn_run_all()
                    return self._send_json(202, {"ok": True, "pid": p.pid})
                except Exception as e:
                    return self._send_json(500, {"error": str(e)})

            if path in ("/api/hold", "/api/resume"):
                meta = load_meta()
                entry = meta.get(spec, {})
                entry["hold"] = (path == "/api/hold")
                meta[spec] = entry
                save_meta(meta)
                return self._send_json(200, {"ok": True, "hold": entry["hold"]})

            if path == "/api/delete":
                full = _safe_path(spec)
                if not full or not os.path.exists(full):
                    return self._send_json(404, {"error": "no such spec"})
                try:
                    os.remove(full)
                    meta = load_meta()
                    if spec in meta:
                        del meta[spec]; save_meta(meta)
                    return self._send_json(200, {"ok": True})
                except Exception as e:
                    return self._send_json(500, {"error": str(e)})

            if path == "/api/edit":
                full = _safe_path(spec)
                if not full or not os.path.exists(full):
                    return self._send_json(404, {"error": "no such spec"})
                # Try VS Code, then notepad
                try:
                    subprocess.Popen(["code", full], shell=True)
                except Exception:
                    try:
                        subprocess.Popen(["notepad", full])
                    except Exception as e:
                        return self._send_json(500, {"error": str(e)})
                return self._send_json(200, {"ok": True})

            if path == "/api/delete_image":
                rel = (form.get("path", [""])[0] or "").replace("\\", "/").lstrip("/")
                if not rel.startswith("screenshots/"):
                    return self._send_json(400, {"error": "path must be inside screenshots/"})
                full = _safe_path(rel)
                if not full or not os.path.isfile(full):
                    return self._send_json(404, {"error": "no such file"})
                try:
                    os.remove(full)
                    return self._send_json(200, {"ok": True})
                except Exception as e:
                    return self._send_json(500, {"error": str(e)})

            if path == "/api/delete_folder":
                rel = (form.get("path", [""])[0] or "").replace("\\", "/").lstrip("/").rstrip("/")
                if not rel.startswith("screenshots/") or rel == "screenshots":
                    return self._send_json(400, {"error": "must be a subfolder under screenshots/"})
                full = _safe_path(rel)
                if not full or not os.path.isdir(full):
                    return self._send_json(404, {"error": "no such folder"})
                try:
                    import shutil
                    shutil.rmtree(full)
                    return self._send_json(200, {"ok": True})
                except Exception as e:
                    return self._send_json(500, {"error": str(e)})

            return self._send_404("unknown endpoint")

    return Handler


def serve(host, port, open_browser):
    handler = make_handler()
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{'localhost' if host in ('0.0.0.0','127.0.0.1') else host}:{port}/"
    print(f"ui-auto dashboard serving at {url}")
    print(f"  repo root: {ROOT}")
    print("  Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
        server.server_close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, "dashboard.html"))
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--hold", metavar="SPEC", help="mark a spec on-hold")
    ap.add_argument("--resume", metavar="SPEC", help="clear on-hold for a spec")
    ap.add_argument("--set", nargs="+", metavar=("SPEC", "K=V"),
                    help="set sidecar metadata: --set <spec> id=TC-001 priority=P1 ...")
    ap.add_argument("--serve", action="store_true",
                    help="run a local web server with working Run/Hold/Delete buttons")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()

    if a.hold:
        cmd_hold(argparse.Namespace(spec=a.hold), True); return
    if a.resume:
        cmd_hold(argparse.Namespace(spec=a.resume), False); return
    if a.set:
        if len(a.set) < 2:
            ap.error("--set requires <spec> followed by one or more key=value")
        cmd_set(argparse.Namespace(spec=a.set[0], kv=a.set[1:])); return

    if a.serve:
        return serve(a.host, a.port, open_browser=a.open or True)

    specs = load_specs()
    runs = load_results()
    meta = load_meta()
    rows = aggregate(specs, runs, meta)
    out = os.path.abspath(a.out)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_html(rows, runs))
    print(f"wrote {os.path.relpath(out, ROOT)} ({len(rows)} cases, {len(runs)} runs)")
    if a.open:
        webbrowser.open("file:///" + out.replace("\\", "/"))


if __name__ == "__main__":
    main()

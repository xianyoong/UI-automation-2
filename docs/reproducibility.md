# Reproducibility notes

- All inputs are pinned in the spec (no random generation at run time).
- Window/control targeting via UIA names/ids, not hard-coded coordinates. The only mouse-coordinate clicks derive `(x, y)` from UIA-reported rectangles, so they survive window-position changes.
- Console validation uses UIA text — independent of fonts, themes, OCR.
- Screenshots are evidence only; pass/fail is decided by the UIA assertion.
- `uv.lock` pins every transitive dependency with content hashes.
- `.python-version` pins the interpreter; `uv` will download the exact build on first sync.

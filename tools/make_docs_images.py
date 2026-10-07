"""Render every picture the README and the project page use.

The images are not mock-ups: they come out of the same painting code the
input method runs (``smartime.ui.panels``) and the same settings page the
user opens, so a change to the product shows up here on the next run and
the documentation cannot quietly drift away from the thing it describes.

    .venv\\Scripts\\python tools\\make_docs_images.py           # docs/images
    .venv\\Scripts\\python tools\\make_docs_images.py --out X   # somewhere else

Needs Pillow (in requirements.txt). The settings shots additionally need
Microsoft Edge, and are skipped with a warning if it is missing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# name -> key script typed into a fresh session. The panel that the view
# asks for is the one that gets drawn, so this is exactly what the user sees.
PANELS = [
    # (file name, script, which panel)
    ("typing-suggestion", "ji3rup wu0 ", "hint"),            # what Tab would take
    ("typing-reading", "ji3rup wu0 wu0", "hint"),            # the half-typed syllable
    ("typing-dropped", "ji3ee/", "hint"),                    # a key skipped as a slip
    ("candidates", "ji35p {DOWN}", "candidates"),            # grouped, coloured
    ("candidates-english", "mvp {DOWN}", "candidates"),      # English <-> Chinese
    ("correction", "ji3ee/4dj94k27{ESC}h", "decode"),        # 按鍵 / 注音 / 國字
    ("correction-keys", "ji3ee/4dj94k27{ESC}vv{HOME}lll", "decode"),
    ("palette", "ji3::{TAB}{TAB}", "candidates"),            # symbol grid
    ("snippets", "ji3;;", "candidates"),
]
SETTINGS_VIEWS = ["general", "dict", "punct", "about"]


def render_panels(out: Path, scale: float, themes) -> list[Path]:
    from smartime.devtools.panel_preview import render
    from smartime.devtools.simulate import run
    from smartime.engine.session import Session
    from smartime.pime.server import build_engine
    from smartime.ui.theme import DARK, LIGHT

    made = []
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["SMARTIME_USER_DIR"] = tmp  # never the real memory
        engine = build_engine()
        # a word of "mine" and a learned one, so every candidate group shows
        engine.lexicon.user.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")
        engine.lexicon.user.add("珍", "ㄓㄣ", "zh", "朋友")
        engine.lexicon.user.learn("真", "ㄓㄣ", "zh")
        engine.lexicon.user.add_snippet("範例市範例區示範路 100 號\n（請寄到這裡，謝謝）", "我的地址", "addr")
        engine.lexicon.user.add_snippet("感謝您的來信！我們已經收到，會在兩個工作天內回覆您。", "", "thanks")
        engine.lexicon.invalidate()
        for name, script, kind in PANELS:
            session = Session(engine)
            run(session, script)
            view = session.view()
            panel = {"hint": view.hint_panel, "candidates": view.candidate_panel, "decode": view.panel}[kind]
            if panel is None:
                print(f"  ! {name}: no {kind} panel for {script!r}", file=sys.stderr)
                continue
            for theme in themes:
                suffix = "-dark" if theme.dark else ""
                path = out / f"{name}{suffix}.png"
                render(panel, theme, scale, path, kind)
                made.append(path)
                print(" ", path.relative_to(ROOT) if ROOT in path.parents else path)
        engine.lexicon.user.close()
        engine.lexicon.close()
    return made


def render_settings(out: Path, dark: bool) -> list[Path]:
    made = []
    for view in SETTINGS_VIEWS:
        cmd = [sys.executable, "-m", "smartime.devtools.settings_shot", str(out), "--view", view]
        if dark:
            cmd.append("--dark")
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        if r.returncode != 0:
            print(f"  ! settings/{view}: {r.stderr.strip().splitlines()[-1:] or r.stdout.strip()}", file=sys.stderr)
            continue
        made.append(out / f"settings-{view}.png")
        print(" ", (out / f"settings-{view}.png").name)
    return made


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "docs" / "images"))
    ap.add_argument("--scale", type=float, default=2.0, help="pixel density (2 = retina)")
    ap.add_argument("--dark", action="store_true", help="also render the dark theme")
    ap.add_argument("--no-settings", action="store_true", help="panels only (no Edge needed)")
    args = ap.parse_args()

    from smartime.ui.theme import DARK, LIGHT

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"==> panels -> {out}")
    render_panels(out, args.scale, [LIGHT, DARK] if args.dark else [LIGHT])
    if not args.no_settings:
        print(f"==> settings page -> {out}")
        render_settings(out, dark=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

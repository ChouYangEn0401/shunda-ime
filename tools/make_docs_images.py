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
    ("typing-suggestion-rows", "ji3ap7", "hint"),            # 快速詞 + mine on top, the dictionary's below
    ("typing-reading", "ji3rup wu0 wu0", "hint"),            # the half-typed syllable
    ("typing-dropped", "ji3ee/", "hint"),                    # a key skipped as a slip
    ("typing-fixed", "ji3 wrold ", "hint"),                  # an English word corrected
    ("candidates", "ji35p {DOWN}", "candidates"),            # grouped, coloured
    ("candidates-english", "mvp {DOWN}", "candidates"),      # English <-> Chinese
    ("candidates-page", "u4{DOWN}{PGDN}{PGDN}", "candidates"),  # 第 3／N 頁 · Home 回第 1 頁
    ("candidates-zhuyin", "su3cl3wu0 {DOWN}{UP}", "candidates"),  # the 注音 group, at the end
    ("correction-zhuyin", "su3cl3wu0 {ESC}{HOME}z", "decode"),  # z: 你 -> ㄋㄧˇ
    ("correction", "ji3ee/4dj94k27{ESC}h", "decode"),        # 按鍵 / 注音 / 國字
    ("correction-keys", "ji3ee/4dj94k27{ESC}vv{HOME}lll", "decode"),
    ("palette", "ji3::{TAB}{TAB}{TAB}", "candidates"),            # symbol grid
    ("snippets", "ji3;;", "candidates"),
    ("voice-recent", "{RCTRL}{TAB}", "candidates"),          # 錄音暫存
    ("quick-tab", "{RCTRL}{TAB}{TAB}", "candidates"),        # 快速詞, also when nothing is typed
    ("typing-composing", "ji3m06ok", "hint"),                # ● Enter 送出: not sent yet
    ("typing-quick-dropped", "o5m", "hint"),                 # 略過 o and the 快速詞 o5m, side by side
    ("typing-quick-prefix", "ji3opu", "hint"),               # the start of a 快速詞's text offers the rest
]
SETTINGS_VIEWS = ["general", "dict", "punct", "practice", "about"]
# One card (.group) of a settings page, cut out of a tall shot of it:
# file name -> (page, which card from the top, 0-based)
SETTINGS_CARDS = {"settings-quick-words": ("snippets", 2)}  # 新增片語, 我的片語, 快速詞, ...


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
        # a 快速詞 and a phrase of mine, so the two-row suggestion strip shows
        engine.lexicon.user.add_quick_word("我們", "我們下週二見，記得帶筆電！")
        engine.lexicon.user.add_quick_word("o5m", "opus-5.5-medium")
        engine.lexicon.user.add("我們的專案", "ㄨㄛˇ-ㄇㄣ˙-ㄉㄜ˙-ㄓㄨㄢ-ㄢˋ", "zh", "")
        engine.lexicon.invalidate()
        import time

        from smartime.voice import recent

        recent.add("這個功能可以先上線，細節下一版再調整", now=time.time() - 12 * 60)
        recent.add("明天下午三點開會，記得帶筆電和上週的報告", now=time.time() - 20)
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
    for name, (view, index) in SETTINGS_CARDS.items():
        path = _settings_card(out / f"{name}.png", view, index)
        if path is not None:
            made.append(path)
            print(" ", path.name)
    return made


CARD_EDGE = (214, 219, 229)  # a .group's border (--line, light theme)


def _settings_card(path: Path, view: str, index: int) -> Path | None:
    """Shoot the whole page (tall window, nothing scrolled: a scrolled page
    comes out blank in headless Edge), then cut out the index-th card by
    following its left border down the page."""
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, "-m", "smartime.devtools.settings_shot", tmp, "--view", view, "--height", "4000"]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        if r.returncode != 0:
            print(f"  ! {path.name}: {r.stderr.strip().splitlines()[-1:] or r.stdout.strip()}", file=sys.stderr)
            return None
        im = Image.open(Path(tmp) / f"settings-{view}.png").convert("RGB")
        im.load()
    # the cards' left edge: the first border-coloured column right of the rail
    y_probe = im.height // 3
    left = next((x for x in range(300, 400) if im.getpixel((x, y_probe)) == CARD_EDGE), None)
    if left is None:
        print(f"  ! {path.name}: no card edge found", file=sys.stderr)
        return None
    runs, start = [], None
    for y in range(im.height):
        edge = im.getpixel((left, y)) == CARD_EDGE
        if edge and start is None:
            start = y
        elif not edge and start is not None:
            if y - start > 20:
                runs.append((start, y))
            start = None
    if index >= len(runs):
        print(f"  ! {path.name}: only {len(runs)} cards on {view}", file=sys.stderr)
        return None
    top, bottom = runs[index]
    right = next(x for x in range(im.width - 1, left, -1) if im.getpixel((x, (top + bottom) // 2)) == CARD_EDGE)
    pad = 14  # past the rounded corners, onto the page around the card
    im.crop((left - pad, top - pad, right + pad + 1, bottom + pad)).save(path)
    return path


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

"""Render the on-screen panels for typed key scripts into PNG files, with
the same drawing code the IME uses (for design review and docs).

    uv run python -m smartime.devtools.panel_preview out_dir [--scale 1.5] [--theme light|dark|both]
    uv run python -m smartime.devtools.panel_preview out_dir --script "ji3ee/4{ESC}"

Needs Pillow (dev dependency) to write PNG.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

SAMPLES = [
    ("typing", "ji3ee/4dj94k27python"),  # stray e skipped, k27 read as ㄉㄜ˙, English word
    ("pending", "ji3ap7u."),  # unfinished syllable at the end
    ("correcting", "ji3ee/4dj94k27{ESC}h"),
    ("correcting-keys", "ji3ee/4dj94k27{ESC}vv{HOME}lll"),
    ("chosen", "ji3a87{LEFT}{UP}2{ESC}"),
    ("long", "b06c.4283tj x96k27y4b/6b06j6z83fm4u/ jp6k27jp4wu6ru.4{ESC}hhhh"),
]


def render(panel, theme, scale: float, path: Path) -> None:
    from PIL import Image

    from ..ui.canvas import Canvas, Fonts, Surface
    from ..ui.panels import paint_decode

    fonts = Fonts(scale)
    probe = Surface(4, 4)
    size = paint_decode(Canvas(probe.hdc, scale, fonts), theme, panel, draw=False)
    probe.close()
    surf = Surface(round(size.width * scale) + 1, round(size.height * scale) + 1)
    canvas = Canvas(surf.hdc, scale, fonts)
    paint_decode(canvas, theme, panel)
    Image.frombytes("RGB", (surf.width, surf.height), surf.rgb_bytes()).save(path)
    canvas.close()
    surf.close()
    fonts.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--theme", default="both", choices=("light", "dark", "both"))
    ap.add_argument("--script", help="one key script instead of the samples")
    args = ap.parse_args()

    from ..engine.panel import decode_panel
    from ..engine.session import Session
    from ..pime.server import build_engine
    from ..ui.theme import DARK, LIGHT
    from .simulate import run

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    samples = [("script", args.script)] if args.script else SAMPLES
    themes = {"light": [LIGHT], "dark": [DARK], "both": [LIGHT, DARK]}[args.theme]
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["SMARTIME_USER_DIR"] = tmp  # never touch the real memory
        engine = build_engine()
        for name, script in samples:
            session = Session(engine)
            run(session, script)
            panel = decode_panel(session)
            for theme in themes:
                path = out / f"decode-{name}-{'dark' if theme.dark else 'light'}.png"
                render(panel, theme, args.scale, path)
                print(path)
        engine.lexicon.user.close()
        engine.lexicon.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

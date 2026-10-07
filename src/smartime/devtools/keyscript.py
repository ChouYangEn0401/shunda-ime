"""Turn a sentence into the keys that type it, so a bug report can be replayed.

A report says "I typed 當我們今天針對數據的第 i 項 and got 第 喔 項". To
reproduce that we need the keystrokes, not the text. This looks every run of
Chinese up in the lexicon, converts its reading to the layout's keys, and
leaves everything else (English, spaces, punctuation) as typed:

    python -m smartime.devtools.keyscript "當我們今天針對數據的第 i 項"
    -> 2; ji3ap7rup wu0 5p 2j04g,4m4k27 2u4 i vu;4

    python -m smartime.devtools.keyscript --run "第 i 項"   # and type it

``--run`` feeds the script straight to smartime.devtools.simulate, so one
command goes from "what the user meant" to "what the IME does".
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import os
from pathlib import Path

MAX_WORD = 6  # longest run of characters looked up as one word


def script_for(text: str, lexicon, layout) -> str:
    """The keys that type ``text`` (longest-match on the lexicon's readings)."""
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if not _is_han(ch):
            out.append(ch)
            i += 1
            continue
        # longest run of Han characters we can find a reading for
        end = min(len(text), i + MAX_WORD)
        while end > i and not _is_han(text[end - 1]):
            end -= 1
        for j in range(end, i, -1):
            word = text[i:j]
            reading = lexicon.reading_for(word)
            if reading:
                try:
                    out.append(layout.keys_for_reading(reading))
                except KeyError:
                    continue  # a reading this layout cannot type (rare finals)
                i = j
                break
        else:
            raise SystemExit(f"keyscript: no reading for 「{text[i]}」 (at {i})")
    return "".join(out)


def _is_han(ch: str) -> bool:
    return "㐀" <= ch <= "鿿"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", help="what the user meant to type")
    ap.add_argument("--run", action="store_true", help="also type it (smartime.devtools.simulate --steps)")
    ap.add_argument("--layout", default="dachen", choices=("dachen", "eten"))
    args = ap.parse_args()

    from ..engine.layouts import get_layout
    from .. import paths
    from ..engine.lexicon import Lexicon

    db = paths.system_db_path()
    if not db.exists():
        raise SystemExit("lexicon not built; run: python tools/build_data.py")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.setdefault("SMARTIME_USER_DIR", tmp)
        lex = Lexicon(db)
        try:
            script = script_for(args.text, lex, get_layout(args.layout))
        finally:
            lex.close()
    print(script)
    if args.run:
        from ..pime.server import build_engine
        from ..engine.session import Session
        from .simulate import describe, run

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SMARTIME_USER_DIR"] = tmp
            engine = build_engine()
            session = Session(engine)
            committed, view = run(session, script)
            print("intended :", args.text)
            print("got      :", committed + view.composition)
            print("state    :", describe(view))
            engine.lexicon.user.close()
            engine.lexicon.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

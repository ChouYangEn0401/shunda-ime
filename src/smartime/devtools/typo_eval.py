"""How well does the IME recover from typing mistakes on its own?

Takes real Chinese phrases (the project's own documents, the same source as
tests/test_golden.py), types each one with one kind of mistake made on
purpose, and counts how often the composition still comes out right — with
an empty dictionary, so learning does not hide anything. ``clean`` is
compared with the phrase itself (homophone choice); every mistake is compared
with what the correctly typed keys give, so it measures only whether the
mistake made things worse:

    clean          no mistake (the baseline every change must keep)
    reorder        two zhuyin keys of a syllable swapped (ㄜㄉ˙ for ㄉㄜ˙)
    tone_early     the tone key typed before the last symbol (2 4 8 for 2 8 4)
    tone_missing   the tone key of a syllable left out (cl m/4 for cl3 m/4)
    space_missing  the first-tone space left out (rup wu0 -> rupwu0)
    extra_double   one letter key pressed twice (cc96 for c96)
    extra_first    the very first key pressed twice
    english        common English words typed between Chinese: must stay English

    python -m smartime.devtools.typo_eval            # summary
    python -m smartime.devtools.typo_eval --show 8   # plus failures per kind

Every number is reproducible (fixed random seed). A decoder change should
raise the recovery rates without lowering ``clean`` or ``english``.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import tempfile
from pathlib import Path

KINDS = ("clean", "reorder", "tone_early", "tone_missing", "space_missing", "extra_double", "extra_first",
         "english")


def phrases(limit: int = 600) -> list[str]:
    root = Path(__file__).resolve().parents[3]
    text = "".join((root / p).read_text(encoding="utf-8")
                   for p in ("README.md", "docs/install.md", "docs/keys.md", "docs/architecture.md", "CHANGELOG.md"))
    seen: list[str] = []
    for run in re.findall(r"[一-鿿]{4,10}", text):
        if run not in seen:
            seen.append(run)
    return seen[:limit]


def syllable_keys(text: str, lexicon, layout) -> list[str] | None:
    """One key string per character (longest-match readings), or None."""
    out: list[str] = []
    i = 0
    while i < len(text):
        for j in range(min(len(text), i + 6), i, -1):
            reading = lexicon.reading_for(text[i:j])
            if reading:
                try:
                    out += [layout.keys_for_syllable(s) for s in reading.split("-")]
                except KeyError:
                    return None
                i = j
                break
        else:
            return None
    return out


def mutate(kind: str, sylls: list[str], layout, rng: random.Random) -> str | None:
    """The keys with one mistake of this kind, or None if the phrase has no
    place for it."""
    s = list(sylls)

    def is_tone(k: str) -> bool:
        return layout.tone(k) is not None

    if kind == "clean":
        return "".join(s)
    if kind == "reorder":
        spots = [i for i, k in enumerate(s) if len(k) >= 3 and k[0] != k[1]]
        if not spots:
            return None
        i = rng.choice(spots)
        s[i] = s[i][1] + s[i][0] + s[i][2:]
    elif kind == "tone_early":
        spots = [i for i, k in enumerate(s) if len(k) >= 3 and k[-1] != " " and is_tone(k[-1])]
        if not spots:
            return None
        i = rng.choice(spots)
        s[i] = s[i][:-2] + s[i][-1] + s[i][-2]
    elif kind == "tone_missing":
        # not the last syllable: at the end an unfinished syllable just waits
        spots = [i for i, k in enumerate(s[:-1]) if k[-1] != " " and is_tone(k[-1]) and len(k) >= 2]
        if not spots:
            return None
        i = rng.choice(spots)
        s[i] = s[i][:-1]
    elif kind == "space_missing":
        spots = [i for i, k in enumerate(s[:-1]) if k[-1] == " " and len(k) >= 2]
        if not spots:
            return None
        i = rng.choice(spots)
        s[i] = s[i][:-1]
    elif kind == "extra_double":
        spots = [(i, j) for i, k in enumerate(s) for j, c in enumerate(k) if c.isalpha()]
        if not spots:
            return None
        i, j = rng.choice(spots)
        s[i] = s[i][:j] + s[i][j] + s[i][j:]
    elif kind == "extra_first":
        if not s[0][0].isalpha():
            return None
        s[0] = s[0][0] + s[0]
    return "".join(s)


def english_cases(lexicon, n: int, rng: random.Random) -> list[tuple[str, str]]:
    """(keys, expected) for common English words typed inside Chinese."""
    rows = lexicon._con.execute(
        "SELECT word FROM en WHERE length(word) BETWEEN 3 AND 9 ORDER BY score DESC LIMIT ?", (n * 3,)).fetchall()
    words = [w for (w,) in rows if w.isalpha() and w.isascii()][:n]
    out = []
    for w in words:
        out.append((f"ji3{w} ", f"我{w} "))
    return out


def run(show: int = 0, limit: int = 600, seed: int = 7) -> dict[str, tuple[int, int]]:
    from .. import paths
    from ..config import Config
    from ..engine.decoder import Decoder
    from ..engine.layouts import DACHEN
    from ..engine.lexicon import Lexicon
    from ..engine.session import Engine, Session
    from ..engine.userdict import UserDict
    from .simulate import parse, press

    tmp = tempfile.mkdtemp()
    user = UserDict(Path(tmp) / "user.db")
    lex = Lexicon(paths.system_db_path(), user)
    cfg = Config()
    cfg.autocomplete = False
    cfg.learn = False
    engine = Engine(lexicon=lex, layout=DACHEN, decoder=Decoder(lex, DACHEN), config=cfg)

    def typed(keys: str) -> str:
        s = Session(engine)
        for k in parse(keys):
            press(s, k)
        return s.view().composition

    rng = random.Random(seed)
    corpus = [(p, syllable_keys(p, lex, DACHEN)) for p in phrases(limit)]
    corpus = [(p, k) for p, k in corpus if k]
    clean_of = {p: typed("".join(k)) for p, k in corpus}
    results: dict[str, tuple[int, int]] = {}
    for kind in KINDS:
        ok = total = 0
        fails = []
        if kind == "english":
            cases = english_cases(lex, 300, rng)
        else:
            # compared with what the same phrase gives typed correctly: the
            # question is whether the mistake hurt, not whether the decoder
            # picks the right homophones (that is what ``clean`` measures)
            cases = []
            for p, sylls in corpus:
                keys = mutate(kind, sylls, DACHEN, rng)
                if keys is not None:
                    cases.append((keys, p if kind == "clean" else clean_of[p]))
        for keys, expected in cases:
            got = typed(keys)
            total += 1
            if got == expected:
                ok += 1
            else:
                fails.append((keys, expected, got))
        results[kind] = (ok, total)
        print(f"{kind:14} {ok:4}/{total:<4} {100 * ok / max(1, total):5.1f}%")
        for keys, expected, got in fails[:show]:
            print(f"      {keys!r:28} want {expected}  got {got}")
    user.close()
    lex.close()
    return results


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", type=int, default=0, help="print up to N failures per kind")
    ap.add_argument("--limit", type=int, default=600, help="phrases taken from the documents")
    args = ap.parse_args()
    os.environ.setdefault("SMARTIME_NO_SENDINPUT", "1")
    os.environ.setdefault("SMARTIME_NO_PANEL", "1")
    run(args.show, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

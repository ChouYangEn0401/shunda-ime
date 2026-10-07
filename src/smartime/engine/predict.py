"""超智慧推薦 (experimental, off by default): longer suggestions than the
Tab continuation, shown in a panel of their own.

* 接下來 — from the Chinese characters just typed, follow the dictionary's
  phrase completions as a chain: the best continuation, then from its last
  characters the next one, and so on, up to a dozen characters. A few
  different starts give a few different chains.
* 也許是 — other words with exactly the same reading as the word just
  typed, when they are about as common (homophones the decoder may have got
  wrong: 鬥號 → 逗號).

Only phrase statistics, no language model: a long chain can drift in
meaning — 「今天」 continues through 「天下」 into 「天下沒有不…」, which is a
real idiom but not what was being written. That is why it is an experiment
the user turns on, and why the panel shows the characters already typed in
front of every chain: a suggestion you cannot read in full is one you
cannot judge.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_PIECE = 4  # characters added by one link of a chain
WEAK_CONTEXT = 1.0  # a one-character context must be this much more common (log10)
MID_WORD = 0.5  # ...and so must a context that starts inside a word the decoder settled
# Function characters lead anywhere (的問題是不是…): never continue from one alone.
FUNCTION_CHARS = frozenset("的了是在不有也就都而與和及或之其這那個們嗎呢吧啊著過被把對向從到讓給")


@dataclass
class Chain:
    text: str  # what would be appended
    readings: tuple[str, ...]  # one syllable per character
    score: float  # of its first link (ranks the chains)


def _extend(lex, acc_text: str, acc_readings: tuple[str, ...], min_score: float, max_chars: int,
            added: int) -> tuple[str, tuple[str, ...]]:
    """Grow a chain from its last one or two characters."""
    text, readings = "", ()
    last_piece = ""
    while added + len(text) < max_chars:
        full = acc_text + text
        full_r = acc_readings + readings
        found = None
        # a two-character overlap first; one character is weak context (的
        # leads anywhere), so through it only longer, clearly common pieces
        for k in (2, 1):
            if len(full) < k:
                continue
            prefix, prefix_r = full[-k:], full_r[-k:]
            floor = min_score + (WEAK_CONTEXT if k == 1 else 0.0)
            for phrase, reading, score in lex.completions(prefix, limit=16):
                if score < floor:
                    break
                syl = tuple(reading.split("-"))
                piece = phrase[k:][:MAX_PIECE]
                if syl[:k] != prefix_r or not piece or piece == last_piece or piece in full[-8:]:
                    continue
                if k == 1 and (len(piece) < 2 or prefix in FUNCTION_CHARS):
                    continue
                found = (piece, syl[k:k + len(piece)])
                break
            if found:
                break
        if not found:
            break
        piece, piece_r = found
        room = max_chars - added - len(text)
        text += piece[:room]
        readings += piece_r[:room]
        last_piece = piece
    return text, readings


def chains(lex, tail: list[tuple[str, str]], min_score: float, beams: int = 3, max_chars: int = 8,
           starts: frozenset[int] | None = None) -> list[Chain]:
    """``tail``: [(char, reading)] of the Chinese characters just typed (≤ 3).

    ``starts``: which suffix lengths begin at a word boundary. Continuing
    from the middle of a word is where the drift comes from — after 「今天」
    the last character alone leads into 「天下沒有不…」, a real idiom about
    something else entirely — so those have to clear a higher bar.
    """
    if not tail:
        return []
    by_k: dict[int, list[Chain]] = {}
    seen: set[str] = set()
    for k in range(len(tail), 0, -1):
        part = tail[-k:]
        prefix = "".join(c for c, _ in part)
        prefix_r = tuple(r for _, r in part)
        floor = min_score + (WEAK_CONTEXT if k == 1 and len(tail) > 1 else 0.0)
        if starts is not None and k not in starts:
            # continuing from inside a word the decoder already settled:
            # allowed, because the segmentation is not gospel (「你好」 really
            # can continue into 「你好不容易」), but it has to be clearly
            # common to be worth suggesting
            floor += MID_WORD
        for phrase, reading, score in lex.completions(prefix, limit=24):
            if score < floor:
                break
            syl = tuple(reading.split("-"))
            if syl[:k] != prefix_r or len(phrase) <= k:
                continue
            piece = phrase[k:][:MAX_PIECE]
            if piece in seen or (k == 1 and len(tail) > 1 and (len(piece) < 2 or prefix in FUNCTION_CHARS)):
                continue
            if piece[0] in FUNCTION_CHARS and len(piece) < 2:
                continue  # 「…的」 on its own is what the Tab suggestion is for
            seen.add(piece)
            by_k.setdefault(k, []).append(Chain(piece, syl[k:k + len(piece)], score))
    # different starts: the best of each context length in turn, longest first
    groups = [sorted(by_k[k], key=lambda c: -c.score) for k in sorted(by_k, reverse=True)]
    seeds: list[Chain] = []
    while any(groups):
        for g in groups:
            if g:
                seeds.append(g.pop(0))
    out: list[Chain] = []
    typed = "".join(c for c, _ in tail)
    typed_r = tuple(r for _, r in tail)
    for seed in seeds[:beams]:
        more, more_r = _extend(lex, typed + seed.text, typed_r + seed.readings, min_score, max_chars,
                               len(seed.text))
        chain = Chain(seed.text + more, seed.readings + more_r, seed.score)
        if len(chain.text) < 2:
            continue  # one character is the plain Tab suggestion, not this
        if all(c.text != chain.text for c in out):
            out.append(chain)
    return out


def alternatives(lex, tail: list[tuple[str, str]], limit: int = 2, margin: float = 1.0) -> list[tuple[int, str]]:
    """Other words read exactly like the last 2-3 characters typed: when
    those characters are not a word at all (打鬥號: 鬥號), or a much rarer
    one. Returns [(how many characters it replaces, word)], longer first."""
    out: list[tuple[int, str]] = []
    for k in (3, 2):
        if len(tail) < k:
            continue
        text = "".join(c for c, _ in tail[-k:])
        reading = "-".join(r for _, r in tail[-k:])
        phrases = lex.phrases(reading)
        mine = next((s for p, s in phrases if p == text), None)
        for p, s in phrases[:3]:
            if p != text and (mine is None or s > mine + margin) and all(p != w for _, w in out):
                out.append((k, p))
        if len(out) >= limit:
            break
    return out[:limit]

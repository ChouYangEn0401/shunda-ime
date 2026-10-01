"""Lattice decoder: raw key buffer -> best mixed Chinese/English segmentation.

Every keystroke the session re-decodes the *whole* uncommitted buffer, so a
later key can change how earlier keys are interpreted (unlike a classic IME
that converts each syllable irrevocably when its tone key is pressed).

Each candidate interpretation of a key span is an edge ("segment") with a
log10 score; the decoder finds the highest scoring path with Viterbi. A small
state (last language, last segment kind) lets us charge a cost for switching
between Chinese and English.

Noisy-channel extensions live on the same lattice: a syllable whose keys were
typed out of order (ㄜㄉ˙ for ㄉㄜ˙) is accepted at a small cost (Phase 4 part 1).
Extra / missing / adjacent keys come next.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum

from . import bopomofo
from .layouts import Layout
from .lexicon import Lexicon


class Kind(str, Enum):
    ZH = "zh"  # Chinese phrase (one display char per syllable)
    EN = "en"  # English word / alphanumeric token, output as typed
    NUM = "num"  # digit run
    PUNCT = "punct"  # punctuation (full-width or ASCII)
    SPACE = "space"  # a literal space
    LITERAL = "literal"  # fallback: the key itself
    PENDING = "pending"  # trailing keys of an unfinished syllable (no tone yet)


@dataclass(frozen=True, slots=True)
class Key:
    char: str
    numpad: bool = False


@dataclass(frozen=True, slots=True)
class Segment:
    start: int  # key span [start, end)
    end: int
    text: str
    kind: Kind
    score: float
    readings: tuple[str, ...] = ()  # ZH only: one syllable per char
    bounds: tuple[int, ...] = ()  # ZH only: key offsets of syllable edges
    pinned: bool = False  # chosen explicitly by the user

    def units(self) -> list[tuple[int, int, str]]:
        """Split into display characters with their key spans."""
        if self.kind is Kind.ZH:
            return [(self.bounds[i], self.bounds[i + 1], self.text[i]) for i in range(len(self.readings))]
        # Every other kind displays exactly one character per key.
        return [(self.start + i, self.start + i + 1, ch) for i, ch in enumerate(self.text)]


@dataclass(frozen=True)
class Weights:
    """Scoring constants (log10), tuned on tests/test_typing_corpus.py."""

    switch_lang: float = -1.5  # Chinese <-> English transition
    en_adjacent: float = -4.0  # two English tokens with no separator
    num_adjacent: float = -4.0
    en_offset: float = 0.0  # added to English lexicon scores
    en_unknown_base: float = -9.0  # alphanumeric token not in the lexicon
    en_unknown_per_char: float = -1.0
    en_digit: float = -2.0  # each digit inside an English token (y94vscode...)
    en_single_letter: float = -3.0  # one-letter words other than a / I
    # Digit keys are also ㄅㄉㄓㄚㄞㄢ and the tones, so 283 can be 打 or the
    # number 283. Numbers must not be cheaper than real Chinese syllables.
    num: float = -5.5
    reorder: float = -1.0  # syllable keys typed out of canonical order
    punct_fullwidth: float = -1.0  # Shift+, -> ，
    punct_ascii_alt: float = -4.0  # Shift+, -> <
    punct_layout_key: float = -6.0  # , . / ; - typed as literal punctuation
    punct_other: float = -2.0  # = \ ` etc.
    space: float = -0.5
    literal: float = -15.0
    pending: float = 0.0


# Shifted / non-layout punctuation -> full-width Chinese punctuation.
FULLWIDTH_PUNCT = {
    "<": "，", ">": "。", "?": "？", "!": "！", ":": "：", '"': "；",
    "'": "、", "[": "「", "]": "」", "{": "『", "}": "』",
    "(": "（", ")": "）", "~": "～", "\\": "＼",
}
# Punctuation that closes a clause; the session commits the buffer on these.
CLAUSE_PUNCT = frozenset("，。？！：；")

_EN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_DIGITS = frozenset("0123456789")
MAX_EN_LEN = 40


@dataclass(frozen=True)
class Decoding:
    segments: tuple[Segment, ...]
    score: float

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.segments)

    def units(self) -> list[tuple[int, int, str, int]]:
        """(key_start, key_end, char, segment_index) for every display char."""
        out = []
        for idx, seg in enumerate(self.segments):
            for a, b, ch in seg.units():
                out.append((a, b, ch, idx))
        return out


# DP language state
_NONE, _ZH, _EN = 0, 1, 2


class Decoder:
    def __init__(self, lexicon: Lexicon, layout: Layout, weights: Weights | None = None):
        self.lex = lexicon
        self.layout = layout
        self.w = weights or Weights()

    # ------------------------------------------------------------------
    def decode(self, keys: Sequence[Key], pins: Sequence[Segment] = ()) -> Decoding:
        n = len(keys)
        if n == 0:
            return Decoding((), 0.0)

        pin_at = {p.start: p for p in pins}
        inside = [False] * (n + 1)  # positions strictly inside a pinned span
        for p in pins:
            for q in range(p.start + 1, p.end):
                inside[q] = True
        # Edges starting at i may not run past the next pin start.
        limit = [n] * (n + 1)
        next_start = n
        for i in range(n, -1, -1):
            limit[i] = next_start
            if i in pin_at:
                next_start = i

        syllables = self._syllable_table(keys)

        # best[i][(lang, prev_kind)] = (score, prev_i, prev_state, segment)
        best: list[dict[tuple[int, Kind | None], tuple[float, int, tuple | None, Segment | None]]] = [
            {} for _ in range(n + 1)
        ]
        best[0][(_NONE, None)] = (0.0, -1, None, None)

        for i in range(n):
            if not best[i] or inside[i]:
                continue
            if i in pin_at:
                edges: list[Segment] = [pin_at[i]]
            else:
                edges = list(self._edges_from(keys, i, limit[i], syllables))
            for seg in edges:
                for state, (score, _, _, _) in best[i].items():
                    lang, prev_kind = state
                    total = score + seg.score + self._transition(lang, prev_kind, seg.kind)
                    new_lang = _ZH if seg.kind is Kind.ZH else _EN if seg.kind is Kind.EN else lang
                    new_state = (new_lang, seg.kind)
                    cur = best[seg.end].get(new_state)
                    if cur is None or total > cur[0]:
                        best[seg.end][new_state] = (total, i, state, seg)

        # Backtrack from the best final state.
        final_state, (final_score, _, _, _) = max(best[n].items(), key=lambda kv: kv[1][0])
        segments: list[Segment] = []
        pos, state = n, final_state
        while pos > 0:
            _, prev_i, prev_state, seg = best[pos][state]
            assert seg is not None
            segments.append(seg)
            pos, state = prev_i, prev_state
        segments.reverse()
        return Decoding(tuple(segments), final_score)

    # ------------------------------------------------------------------
    def _transition(self, lang: int, prev_kind: Kind | None, kind: Kind) -> float:
        w = self.w
        cost = 0.0
        if kind is Kind.ZH and lang == _EN:
            cost += w.switch_lang
        elif kind is Kind.EN:
            if lang == _ZH:
                cost += w.switch_lang
            if prev_kind is Kind.EN:
                cost += w.en_adjacent
        elif kind is Kind.NUM and prev_kind is Kind.NUM:
            cost += w.num_adjacent
        return cost

    def _syllable_table(self, keys: Sequence[Key]) -> list[list[tuple[int, str, float]]]:
        """For each start position: [(end, syllable, channel_cost)].

        A syllable is 1-3 symbol keys followed by a tone key. Keys typed in
        canonical order cost nothing; any other order of the same symbols
        (ㄜㄉ˙ for ㄉㄜ˙, very common when typing fast) costs ``w.reorder``.
        """
        n = len(keys)
        table: list[list[tuple[int, str, float]]] = [[] for _ in range(n)]
        layout = self.layout
        valid = self.lex.valid_syllables
        for i in range(n):
            symbols: list[str] = []
            for j in range(i, min(n, i + 4)):
                k = keys[j]
                if k.numpad:
                    break
                tone = layout.tone(k.char)
                if tone is not None:
                    if symbols:
                        syl = bopomofo.canonical(symbols, tone)
                        if syl is not None and syl in valid:
                            exact = bopomofo.compose_strict(symbols, tone) == syl
                            table[i].append((j + 1, syl, 0.0 if exact else self.w.reorder))
                    break
                sym = layout.symbol(k.char)
                if sym is None:
                    break
                symbols.append(sym)
        return table

    def _edges_from(
        self, keys: Sequence[Key], i: int, limit: int, syllables: list[list[tuple[int, str, float]]]
    ) -> Iterator[Segment]:
        w = self.w
        n = len(keys)
        k = keys[i]
        ch = k.char

        # --- Chinese phrases: chains of syllables looked up in the lexicon.
        yield from self._zh_edges(i, limit, syllables)

        # --- English / alphanumeric tokens, output exactly as typed.
        if ch in _EN_CHARS and not k.numpad:
            j = i
            has_letter = False
            while j < limit and j - i < MAX_EN_LEN:
                c = keys[j].char
                if c in _EN_CHARS and not keys[j].numpad:
                    has_letter = has_letter or c in _LETTERS
                    j += 1
                elif c == "'" and j > i and j + 1 < limit and keys[j + 1].char in _LETTERS:
                    j += 1  # apostrophe inside a word: don't, it's
                    continue
                else:
                    break
                if has_letter:
                    word = "".join(x.char for x in keys[i:j])
                    yield Segment(i, j, word, Kind.EN, self._en_score(word))

        # --- Numbers.
        if ch in _DIGITS:
            j = i
            while j < limit and keys[j].char in _DIGITS:
                j += 1
                yield Segment(i, j, "".join(x.char for x in keys[i:j]), Kind.NUM, w.num)

        # --- Punctuation and spaces.
        if ch == " ":
            yield Segment(i, i + 1, " ", Kind.SPACE, w.space)
        elif ch in FULLWIDTH_PUNCT:
            yield Segment(i, i + 1, FULLWIDTH_PUNCT[ch], Kind.PUNCT, w.punct_fullwidth)
            yield Segment(i, i + 1, ch, Kind.PUNCT, w.punct_ascii_alt)
        elif self.layout.is_layout_key(ch) and not ch.isalnum():
            yield Segment(i, i + 1, ch, Kind.PUNCT, w.punct_layout_key)
        elif not ch.isalnum() and ch.isprintable():
            yield Segment(i, i + 1, ch, Kind.PUNCT, w.punct_other)

        # --- Unfinished syllable at the end of the buffer (shown raw + hint).
        if limit == n and 0 < n - i <= 3:
            symbols = []
            for x in keys[i:n]:
                sym = None if x.numpad else self.layout.symbol(x.char)
                if sym is None:
                    break
                symbols.append(sym)
            else:
                canon = bopomofo.canonical(symbols)
                if canon is not None and canon in self.lex.partial_syllables:
                    yield Segment(i, n, "".join(x.char for x in keys[i:n]), Kind.PENDING, w.pending)

        # --- Fallback so that every position stays reachable.
        yield Segment(i, i + 1, ch, Kind.LITERAL, w.literal)

    def _zh_edges(self, i: int, limit: int, syllables: list[list[tuple[int, str, float]]]) -> Iterator[Segment]:
        lex = self.lex
        max_len = lex.max_phrase_syllables
        # Depth-first over syllable chains: (end, readings, bounds, channel cost)
        stack = [(end, (syl,), (i, end), cost) for end, syl, cost in syllables[i] if end <= limit]
        while stack:
            end, readings, bounds, cost = stack.pop()
            reading = "-".join(readings)
            phrases = lex.phrases(reading)
            if phrases:
                text, score = phrases[0]
                yield Segment(i, end, text, Kind.ZH, score + cost, readings, bounds)
            if len(readings) < max_len and end < limit and lex.has_reading_prefix(reading):
                for nxt_end, syl, nxt_cost in syllables[end]:
                    if nxt_end <= limit:
                        stack.append((nxt_end, readings + (syl,), bounds + (nxt_end,), cost + nxt_cost))

    def _en_score(self, word: str) -> float:
        w = self.w
        score = self.lex.en_score(word.lower())
        if score is not None:
            score += w.en_offset
            if len(word) == 1 and word.lower() not in ("a", "i"):
                score += w.en_single_letter  # "o" is almost never meant as a word
            return score
        # Unknown token. Digits inside letters (y94vscode, k27) are typical of
        # zhuyin typed in mixed mode, not of English, so each one costs extra.
        digits = sum(c in _DIGITS for c in word)
        return w.en_unknown_base + w.en_unknown_per_char * len(word) + w.en_digit * digits

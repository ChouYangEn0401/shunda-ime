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
from dataclasses import dataclass, replace
from enum import Enum
from itertools import product

from . import bopomofo
from .layouts import Layout
from .lexicon import Lexicon
from .pinyin import TONE_DIGITS, to_pinyin


class Kind(str, Enum):
    ZH = "zh"  # Chinese phrase (one display char per syllable)
    EN = "en"  # English word / alphanumeric token, output as typed
    NUM = "num"  # digit run
    PUNCT = "punct"  # punctuation (full-width or ASCII)
    SPACE = "space"  # a literal space
    LITERAL = "literal"  # fallback: the key itself
    PENDING = "pending"  # trailing keys of an unfinished syllable (no tone yet)
    DROP = "drop"  # a stray key (typed by accident) that produces no output


# Typed as they are, one display character per key: the kinds whose
# boundary with Chinese the decoder has to guess (gamesu3, 10284).
TOKEN_KINDS = (Kind.EN, Kind.NUM, Kind.LITERAL)


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
    en_single_letter: float = -3.0  # one-letter words other than "a" / capital "I"
    # ... unless it stands alone between spaces (第 i 項, 用 x 表示, P 和 Q).
    # There the space is the user's own separator, so the letter is English
    # and the space after it is not a first-tone key: without this, frequent
    # one-syllable words win (u -> 一, i -> 喔) and eat the separator.
    en_delimited_letter: float = 4.0  # replaces en_single_letter when delimited
    # Digit keys are also ㄅㄉㄓㄚㄞㄢ and the tones, so 283 can be 打 or the
    # number 283. Numbers must not be cheaper than real Chinese syllables.
    num: float = -5.5
    reorder: float = -1.0  # syllable keys typed out of canonical order
    # The tone key typed one symbol too early: 2 4 8 (ㄉˋㄚ) for 2 8 4 大.
    tone_early: float = -1.5
    # ... when what was typed up to the tone is a syllable already (dj4 酷,
    # 2u4 地): reading on (dj4i as 擴) must not beat 酷喔, so it costs more
    tone_early_valid: float = -4.0
    # The tone key left out between two syllables (cl m/4: ㄏㄠ ㄩㄥˋ for 好用);
    # the next key starts a syllable of its own, so the boundary is plain.
    # Which tone it was is the lexicon's guess, hence dearer than a reorder.
    tone_missing: float = -2.5
    tone1_missing: float = -2.0  # the first-tone space left out (rupwu0 今天)
    # A stray lowercase/layout key typed by accident (fast typing, or left
    # behind by Backspace) is dropped rather than shown as a lone letter.
    drop: float = -6.5  # must stay below the rarest real syllable (ㄟ -5.9 + space)
    # The same key twice in a row (cc96 for c96: a bounce or a double press).
    # Zhuyin never needs that — a syllable cannot hold one symbol twice and a
    # tone key sits between syllables — so it is the likeliest slip of all.
    drop_double: float = -1.5
    punct_preferred: float = -1.0  # the configured style for Shift+symbol
    punct_alternative: float = -4.0  # the other style (still in the candidates)
    punct_layout_key: float = -6.0  # , . / ; - typed as literal punctuation
    punct_other: float = -2.0  # = \ ` etc.
    space: float = -0.5
    # A space typed right after a finished Chinese syllable is a separator:
    # in Chinese typing it only appears before English (第 i 項, 用 x 表示).
    zh_space_zh: float = -3.0  # Chinese again right after such a space
    en_after_zh_space: float = 1.5  # English there: no language-switch cost
    drop_after_space: float = -3.0  # a key typed right after a space is deliberate
    literal: float = -15.0
    pending: float = 0.0
    cangjie_rank: float = -0.3  # per place behind the most common char of a code
    # An unfinished tail: in pinyin a complete syllable must win (women ->
    # 我們, not 我 + "men" still waiting); Cangjie needs a space to finish a
    # code, so its tail waits unless it is a likely English word (auto mode).
    pending_pinyin: float = -12.0
    pending_cangjie: float = -6.0
    # 瘋狂模式 (experimental): a syllable typed only by its first symbol(s).
    # Typing the whole syllable with its tone stays cheaper.
    abbr: float = -1.2  # per abbreviated syllable
    abbr_symbol: float = 0.3  # each symbol typed beyond the first (more certain)
    pending_crazy: float = -9.0  # an unfinished syllable shows raw only if no word fits


# Shifted / non-layout punctuation -> full-width Chinese punctuation.
FULLWIDTH_PUNCT = {
    "<": "，", ">": "。", "?": "？", "!": "！", ":": "：", '"': "＂",  # ； is Ctrl+;
    "'": "、", "[": "「", "]": "」", "{": "『", "}": "』",
    "(": "（", ")": "）", "~": "～", "\\": "＼",
}
# Other symbols a punctuation key can stand for, offered in the candidate
# window after the full-width and half-width forms.
PUNCT_VARIANTS = {
    '"': "“”「」；", "'": "‘’", "<": "《〈", ">": "》〉", "[": "【〔", "]": "】〕",
    "{": "｛", "}": "｝", "?": "", "!": "", ":": "", "(": "", ")": "", "~": "", "\\": "",
}
# Punctuation that was typed as itself rather than through a keycap — Ctrl+,
# inserts 「，」 as the key — has no ASCII key to look the variants up by, so
# every form of a symbol is also indexed by the symbol. Pressing ↓ on it then
# still offers the other width and the related marks (reported: 「標點沒辦法
# 透過『下』去操作」).
PUNCT_FORMS = [
    "，,", "。.", "？?", "！!", "：:", "；;", "、\\", "＂\"“”", "＇'‘’",
    "「『【〔［[", "」』】〕］]", "（(｛{", "）)｝}", "《<〈", "》>〉",
    "～~", "＼\\", "—－-", "…‥·",
]
PUNCT_ALTERNATIVES = {ch: forms for forms in PUNCT_FORMS for ch in forms}
# Keys that may be dropped as accidental: lowercase letters plus the layout's
# own non-letter zhuyin keys (大千 , . / ; -  倚天 , . / ; ' - =). Never
# digits, spaces, capitals or shifted symbols.
_LOWER = frozenset("abcdefghijklmnopqrstuvwxyz")
# Punctuation that closes a clause; the session commits the buffer on these.
CLAUSE_PUNCT = frozenset("，。？！：；")

# Input schemes for Chinese. Zhuyin keys depend on the layout (大千/倚天);
# pinyin and Cangjie use letters, so , . ; are ordinary punctuation there.
SCHEMES = ("zhuyin", "pinyin", "cangjie")
PLAIN_PUNCT = {",": "，", ".": "。", ";": "；", "\\": "、"}
CANGJIE_RADICALS = dict(zip("abcdefghijklmnopqrstuvwxyz", "日月金木水火土竹戈十大中一弓人心手口尸廿山女田難卜重"))
_CJ_TOP = 4  # characters per code tried when looking for multi-character words

_EN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_DIGITS = frozenset("0123456789")
MAX_EN_LEN = 40
MAX_ABBR_KEYS = 8  # 瘋狂模式: keys looked at from one position
MAX_ABBR_SYLLABLES = 6


def _tones_match(reading: str, tones) -> bool:
    """Typed pinyin tones (None = not typed) agree with a reading."""
    for syl, tone in zip(reading.split("-"), tones):
        if tone is not None and bopomofo.tone_of(syl) != tone:
            return False
    return True


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
    def __init__(self, lexicon: Lexicon, layout: Layout, weights: Weights | None = None,
                 halfwidth_symbols: str = '"'):
        self.lex = lexicon
        self.layout = layout
        self.w = weights or Weights()
        self.halfwidth_symbols = frozenset(halfwidth_symbols)
        self.reorder_tolerance = True
        self.drop_enabled = True
        self.crazy = False  # 瘋狂模式
        self._set_layout(layout)

    def _set_layout(self, layout: Layout) -> None:
        self.layout = layout
        self.droppable = _LOWER | frozenset(
            k for k in layout.symbols if not k.isalnum())

    def apply_config(self, cfg) -> None:
        """Settings that change decoding (from config.Config)."""
        from .punct import halfwidth_set

        self.halfwidth_symbols = halfwidth_set(cfg)
        if cfg.layout != self.layout.name:
            from .layouts import get_layout

            self._set_layout(get_layout(cfg.layout))
        self.reorder_tolerance = cfg.reorder_tolerance
        self.drop_enabled = cfg.drop_stray_keys != "off"
        self.crazy = bool(getattr(cfg, "crazy_mode", False))
        if self.crazy:
            self.lex.warm_abbreviations()
        base = Weights()
        self.w = replace(
            base,
            drop=-8.5 if cfg.drop_stray_keys == "conservative" else base.drop,
            en_single_letter=base.en_single_letter if cfg.single_letter_context else 0.0,
            pending=base.pending_crazy if self.crazy else base.pending,
        )

    # ------------------------------------------------------------------
    def decode(self, keys: Sequence[Key], pins: Sequence[Segment] = (), allow_english: bool = True,
               scheme: str = "zhuyin", joints: Sequence[int] = (), open_at: int | None = None) -> Decoding:
        """``allow_english=False`` is a pure Chinese mode: no English tokens.
        ``scheme``: how Chinese is typed (zhuyin, pinyin, cangjie).

        ``joints``: positions no syllable or word may straddle — where keys
        typed into the middle of the composition meet the keys that were
        there, or a boundary the user chose. A phrase may still span one at
        a syllable joint, so 氣 typed after 天 still reads in context as
        天氣. ``open_at``: where the user is typing in the middle — an
        unfinished syllable may stop there, as it may at the end (nowhere
        else: a half syllable left inside the text is never a good read)."""
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
        # cut[i]: how far one syllable or token starting at i may reach
        joint_set = {j for j in joints if 0 < j < n}
        if open_at is not None and 0 < open_at < n:
            joint_set.add(open_at)
        open_set = {open_at} & joint_set
        cut = [n] * (n + 1)
        nxt = n
        for i in range(n, -1, -1):
            cut[i] = min(nxt, limit[i])
            if i in joint_set:
                nxt = i

        syllables = self._unit_table(keys, scheme)

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
                edges = list(self._edges_from(keys, i, limit[i], syllables, allow_english, scheme,
                                              cut, open_set))
            for seg in edges:
                for state, (score, _, _, _) in best[i].items():
                    lang, prev_kind = state
                    if seg.kind is Kind.DROP:
                        # Invisible: the context continues as if the key were
                        # not there (so dropping can't split an English word
                        # for free — en_adjacent still applies across it).
                        total = score + seg.score
                        if prev_kind is Kind.SPACE:
                            total += self.w.drop_after_space
                        new_state = state
                    else:
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

    def zh_alternatives(self, keys: Sequence[Key], start: int, max_syllables: int = 4,
                        scheme: str = "zhuyin") -> list[Segment]:
        """Every Chinese reading of the keys starting at ``start`` — all
        phrases, not only the best — for the candidate window. Lets the user
        turn something decoded as English/raw (``i␣``, ``mvp␣``) into Chinese
        (喔, 勳). Longer phrases first, then by score."""
        if scheme == "pinyin":
            return self._pinyin_alternatives(keys, start, max_syllables)
        if scheme == "cangjie":
            return self._cangjie_alternatives(keys, start)
        syllables = self._syllable_table(keys)
        out: list[Segment] = []
        stack = [(end, (syl,), (start, end), cost) for end, syl, cost in syllables[start]] if start < len(keys) else []
        while stack:
            end, readings, bounds, cost = stack.pop()
            reading = "-".join(readings)
            for text, score in self.lex.phrases(reading):
                out.append(Segment(start, end, text, Kind.ZH, score + cost, readings, bounds))
            if len(readings) < max_syllables and end < len(keys) and self.lex.has_reading_prefix(reading):
                for nxt_end, syl, nxt_cost in syllables[end]:
                    stack.append((nxt_end, readings + (syl,), bounds + (nxt_end,), cost + nxt_cost))
        out.sort(key=lambda s: (-len(s.readings), -s.score))
        return out

    def unit_keys(self, scheme: str, char: str, syllable: str) -> str:
        """The keys that type one character in a scheme (Tab continuations
        insert these): 們 -> ap7 (大千) / men / oan␣."""
        if scheme == "pinyin":
            return to_pinyin(bopomofo.strip_tone(syllable)) or ""
        if scheme == "cangjie":
            code = self.lex.cangjie_code(char)
            return code + " " if code else ""
        return self.layout.keys_for_syllable(syllable)

    # ------------------------------------------------------------------ schemes
    def _unit_table(self, keys: Sequence[Key], scheme: str) -> list:
        if scheme == "pinyin":
            return self._pinyin_table(keys)
        if scheme == "cangjie":
            return self._cangjie_table(keys)
        return self._syllable_table(keys)

    def _pinyin_table(self, keys: Sequence[Key]) -> list[list[tuple[int, tuple[str, ...], str | None, bool]]]:
        """For each start: [(end, toneless syllables, tone or None, ended by a
        space)]. A digit right after a syllable is its tone (ma3); an
        apostrophe separates syllables (xi'an); a space ends a word."""
        n = len(keys)
        table: list[list] = [[] for _ in range(n)]
        py = self.lex.pinyin
        for i in range(n):
            start = i + 1 if keys[i].char == "'" and i > 0 else i
            letters = ""
            for j in range(start, min(n, start + py.max_len)):
                k = keys[j]
                if k.numpad or k.char not in _LOWER:
                    break
                letters += k.char
                plains = py.lookup(letters)
                if not plains:
                    if letters not in py.prefixes:
                        break
                    continue
                end = j + 1
                options: list[tuple[int, str | None]] = [(end, None)]
                if end < n and keys[end].char in TONE_DIGITS and not keys[end].numpad:
                    options.append((end + 1, TONE_DIGITS[keys[end].char]))
                for e, tone in options:
                    table[i].append((e, plains, tone, False))
                    if e < n and keys[e].char == " ":
                        table[i].append((e + 1, plains, tone, True))
        return table

    def _pinyin_chains(self, start: int, limit: int, table, max_syllables: int):
        """Every syllable chain from ``start``: (end, plains per syllable,
        tones, bounds). A chain ends after a syllable followed by a space."""
        lex = self.lex
        stack = [(e, (pl,), (tone,), (start, e), term) for e, pl, tone, term in table[start] if e <= limit]
        while stack:
            end, plains, tones, bounds, term = stack.pop()
            yield end, plains, tones, bounds
            if term or len(plains) >= max_syllables or end >= limit:
                continue
            if not any(lex.has_plain_prefix("-".join(c)) for c in product(*plains)):
                continue
            for e2, pl2, tone2, term2 in table[end]:
                if e2 <= limit:
                    stack.append((e2, plains + (pl2,), tones + (tone2,), bounds + (e2,), term2))

    def _pinyin_phrases(self, plains, tones) -> Iterator[tuple[str, str, float]]:
        for combo in product(*plains):
            for phrase, reading, score in self.lex.plain_phrases("-".join(combo)):
                if _tones_match(reading, tones):
                    yield phrase, reading, score

    def _py_edges(self, i: int, limit: int, table) -> Iterator[Segment]:
        for end, plains, tones, bounds in self._pinyin_chains(i, limit, table, self.lex.max_phrase_syllables):
            best = max(self._pinyin_phrases(plains, tones), key=lambda t: t[2], default=None)
            if best is not None:
                phrase, reading, score = best
                yield Segment(i, end, phrase, Kind.ZH, score, tuple(reading.split("-")), bounds)

    def _pinyin_alternatives(self, keys: Sequence[Key], start: int, max_syllables: int) -> list[Segment]:
        if start >= len(keys):
            return []
        table = self._pinyin_table(keys)
        out = []
        for end, plains, tones, bounds in self._pinyin_chains(start, len(keys), table, max_syllables):
            for phrase, reading, score in self._pinyin_phrases(plains, tones):
                out.append(Segment(start, end, phrase, Kind.ZH, score, tuple(reading.split("-")), bounds))
        out.sort(key=lambda s: (-len(s.readings), -s.score))
        return out

    def _cangjie_table(self, keys: Sequence[Key]) -> list[list[tuple[int, str]]]:
        """For each start: [(end, code)] — 1-5 code letters ended by a space."""
        n = len(keys)
        table: list[list] = [[] for _ in range(n)]
        for i in range(n):
            code = ""
            for j in range(i, min(n, i + 5)):
                k = keys[j]
                if k.numpad or k.char not in _LOWER:
                    break
                code += k.char
                if j + 1 < n and keys[j + 1].char == " " and self.lex.cangjie_chars(code):
                    table[i].append((j + 2, code))
        return table

    def _cangjie_char(self, code: str) -> tuple[str, str, float] | None:
        """Best character of a code: (char, reading, score)."""
        best = None
        for rank, ch in enumerate(self.lex.cangjie_chars(code)[:8]):
            info = self.lex.text_info(ch)
            if info is None:
                continue
            score = info[1] + self.w.cangjie_rank * rank
            if best is None or score > best[2]:
                best = (ch, info[0], score)
        return best

    def _cangjie_words(self, codes: tuple[str, ...]) -> Iterator[tuple[str, str, float]]:
        """Dictionary words whose characters have these codes."""
        for combo in product(*(self.lex.cangjie_chars(c)[:_CJ_TOP] for c in codes)):
            text = "".join(combo)
            info = self.lex.text_info(text)
            if info is not None:
                yield text, info[0], info[1]

    def _cj_edges(self, i: int, limit: int, table) -> Iterator[Segment]:
        stack = [(e, (code,), (i, e)) for e, code in table[i] if e <= limit]
        while stack:
            end, codes, bounds = stack.pop()
            if len(codes) == 1:
                best = self._cangjie_char(codes[0])
            else:
                best = max(self._cangjie_words(codes), key=lambda t: t[2], default=None)
            if best is not None:
                text, reading, score = best
                yield Segment(i, end, text, Kind.ZH, score, tuple(reading.split("-")), bounds)
            if len(codes) < 3 and end < limit:
                for e2, c2 in table[end]:
                    if e2 <= limit:
                        stack.append((e2, codes + (c2,), bounds + (e2,)))

    def _cangjie_alternatives(self, keys: Sequence[Key], start: int) -> list[Segment]:
        if start >= len(keys):
            return []
        table = self._cangjie_table(keys)
        out: list[Segment] = []
        for end, code in table[start]:
            for rank, ch in enumerate(self.lex.cangjie_chars(code)):
                info = self.lex.text_info(ch)
                if info is not None:
                    out.append(Segment(start, end, ch, Kind.ZH, info[1] + self.w.cangjie_rank * rank,
                                       (info[0],), (start, end)))
            for end2, code2 in table[end] if end < len(keys) else ():
                for text, reading, score in self._cangjie_words((code, code2)):
                    out.append(Segment(start, end2, text, Kind.ZH, score, tuple(reading.split("-")),
                                       (start, end, end2)))
        # words first, then single characters in the table's order
        out.sort(key=lambda s: -len(s.readings))
        return out

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
        if prev_kind is Kind.SPACE and lang == _ZH:
            if kind is Kind.ZH:
                cost += w.zh_space_zh
            elif kind is Kind.EN:
                cost += w.en_after_zh_space
        return cost

    def _syllable_table(self, keys: Sequence[Key]) -> list[list[tuple[int, str, float]]]:
        """For each start position: [(end, syllable, channel_cost)].

        A syllable is 1-3 symbol keys followed by a tone key. Keys typed in
        canonical order cost nothing; any other order of the same symbols
        (ㄜㄉ˙ for ㄉㄜ˙, very common when typing fast) costs ``w.reorder``.

        With the tolerance on, two more slips are read as syllables: the tone
        key typed before the last symbol (ㄉˋㄚ), and the tone key left out
        where the next key plainly starts another syllable (ㄏㄠ|ㄩㄥˋ). Both
        were left as raw keys before — 248 stayed "248" and clm/4 came out
        「cl用」 — and nothing in correction mode could turn them back.
        """
        n = len(keys)
        table: list[list[tuple[int, str, float]]] = [[] for _ in range(n)]
        layout = self.layout
        valid = self.lex.valid_syllables
        tolerant = self.reorder_tolerance
        w = self.w
        doubles = self.drop_enabled
        for i in range(n):
            symbols: list[str] = []
            extra = 0.0  # a double press absorbed inside this syllable
            for j in range(i, min(n, i + 5)):
                k = keys[j]
                if k.numpad:
                    break
                tone = layout.tone(k.char)
                if tone is not None:
                    if symbols:
                        syl = bopomofo.canonical(symbols, tone)
                        if syl is not None and syl in valid:
                            exact = bopomofo.compose_strict(symbols, tone) == syl
                            if exact or tolerant:
                                table[i].append((j + 1, syl, extra + (0.0 if exact else w.reorder)))
                        # not the space: that one also separates words
                        if tolerant and tone:
                            alone = syl is not None and syl in valid
                            self._early_tone(keys, j, symbols, tone, table[i],
                                             extra + (w.tone_early_valid - w.tone_early if alone else 0.0))
                    break
                sym = layout.symbol(k.char)
                if sym is None:
                    break
                if j > i + 1 and keys[j - 1].char == k.char and k.char in _LOWER and doubles and not extra:
                    # the same key twice inside a syllable (gjpp4 順): a DROP
                    # segment cannot sit inside a syllable, so absorb it here.
                    # Not at the syllable's first key: there (ee/4) an ordinary
                    # DROP before the syllable does it, and stays visible as 略過.
                    extra = w.drop_double
                    continue
                if len(symbols) == 3:
                    break
                symbols.append(sym)
                # the same key again is a double press (drop_double), not a
                # syllable boundary whose tone was left out: 1jj6 is 不, not 不無
                # Nor from a syllable that starts on a punctuation-position key
                # (; / , . - are ㄤㄥㄝㄡㄦ): ;;th is the 片語 trigger, not ㄤ ㄤ.
                if tolerant and j + 1 < n and keys[j + 1].char != k.char and keys[i].char.isalnum():
                    self._missing_tone(keys[j + 1], j + 1, symbols, table[i], extra)
        return table

    def _early_tone(self, keys: Sequence[Key], j: int, symbols: list[str], tone: str, out: list,
                    extra: float = 0.0) -> None:
        """``keys[j]`` is a tone typed before the syllable's last symbol(s):
        add the syllable that ends after those symbols (in typed order only)."""
        valid = self.lex.valid_syllables
        more = list(symbols)
        for m in range(j + 1, min(len(keys), j + 4 - len(symbols))):
            k = keys[m]
            sym = None if k.numpad else self.layout.symbol(k.char)
            if sym is None:
                return
            more.append(sym)
            syl = bopomofo.compose_strict(more, tone)
            if syl is None:
                return
            if syl in valid:
                out.append((m + 1, syl, extra + self.w.tone_early))

    def _missing_tone(self, nxt: Key, end: int, symbols: list[str], out: list, extra: float = 0.0) -> None:
        """``symbols`` (typed in order) end right before ``nxt``, a symbol key
        that cannot continue them: a syllable whose tone key was left out.
        Every tone that makes a real syllable is offered; the phrase decides."""
        sym = None if nxt.numpad else self.layout.symbol(nxt.char)
        # two symbols at least: a lone ㄔ ㄜ ㄩ read as 吃 額 於 made almost
        # any letter a character (mvp -> 於vp, th -> 吃h)
        if sym is None or len(symbols) < 2 or bopomofo.compose_strict(symbols) is None:
            return
        if bopomofo.compose_strict(symbols + [sym]) is not None:
            return  # it could be the same syllable going on
        valid = self.lex.valid_syllables
        body = "".join(symbols)
        w = self.w
        for mark, cost in (("", w.tone1_missing), ("ˊ", w.tone_missing), ("ˇ", w.tone_missing),
                           ("ˋ", w.tone_missing), ("˙", w.tone_missing)):
            if body + mark in valid:
                out.append((end, body + mark, extra + cost))

    def _edges_from(
        self, keys: Sequence[Key], i: int, limit: int, syllables: list,
        allow_english: bool = True, scheme: str = "zhuyin",
        cut: Sequence[int] | None = None, open_at: frozenset | set = frozenset(),
    ) -> Iterator[Segment]:
        w = self.w
        n = len(keys)
        k = keys[i]
        ch = k.char
        zhuyin = scheme == "zhuyin"
        if cut is None:
            cut = [limit] * (n + 1)
        tok = cut[i]  # one token (a word, a number, a code) ends here at the latest
        open_end = tok == n or tok in open_at  # an unfinished syllable may stop here

        # --- Chinese phrases: chains of syllables (zhuyin, pinyin) or codes
        #     (Cangjie) looked up in the lexicon.
        if scheme == "pinyin":
            yield from self._py_edges(i, tok, syllables)
        elif scheme == "cangjie":
            yield from self._cj_edges(i, tok, syllables)
        else:
            yield from self._zh_edges(i, limit, syllables, cut)
            if self.crazy:
                yield from self._abbr_edges(keys, i, tok)

        # --- English / alphanumeric tokens, output exactly as typed.
        if allow_english and ch in _EN_CHARS and not k.numpad:
            j = i
            has_letter = False
            while j < tok and j - i < MAX_EN_LEN:
                c = keys[j].char
                if c in _EN_CHARS and not keys[j].numpad:
                    has_letter = has_letter or c in _LETTERS
                    j += 1
                elif c == "'" and j > i and j + 1 < tok and keys[j + 1].char in _LETTERS:
                    j += 1  # apostrophe inside a word: don't, it's
                    continue
                else:
                    break
                if has_letter:
                    word = "".join(x.char for x in keys[i:j])
                    # "delimited": the user put a space on each side themselves.
                    # Only a real space counts — at the start of the buffer
                    # there is no separator, so "o␣" is still ㄟ.
                    delimited = i > 0 and keys[i - 1].char == " " and (j >= n or keys[j].char == " ")
                    yield Segment(i, j, word, Kind.EN, self._en_score(word, delimited))

        # --- Numbers (純注音: numeric keypad only; top-row digits are zhuyin).
        numbers_ok = allow_english or not zhuyin
        if ch in _DIGITS and (numbers_ok or k.numpad):
            j = i
            while j < tok and keys[j].char in _DIGITS and (numbers_ok or keys[j].numpad):
                j += 1
                yield Segment(i, j, "".join(x.char for x in keys[i:j]), Kind.NUM, w.num)

        # --- Punctuation and spaces.
        if ch == " ":
            yield Segment(i, i + 1, " ", Kind.SPACE, w.space)
        elif ch in FULLWIDTH_PUNCT:
            # Full-width unless the user listed the symbol as half-width.
            fullwidth_first = ch not in self.halfwidth_symbols
            full, ascii_ = (w.punct_preferred, w.punct_alternative) if fullwidth_first else (
                w.punct_alternative, w.punct_preferred)
            yield Segment(i, i + 1, FULLWIDTH_PUNCT[ch], Kind.PUNCT, full)
            yield Segment(i, i + 1, ch, Kind.PUNCT, ascii_)
        elif not zhuyin and ch in PLAIN_PUNCT:
            fullwidth_first = ch not in self.halfwidth_symbols
            full, ascii_ = (w.punct_preferred, w.punct_alternative) if fullwidth_first else (
                w.punct_alternative, w.punct_preferred)
            yield Segment(i, i + 1, PLAIN_PUNCT[ch], Kind.PUNCT, full)
            yield Segment(i, i + 1, ch, Kind.PUNCT, ascii_)
        elif zhuyin and self.layout.is_layout_key(ch) and not ch.isalnum():
            yield Segment(i, i + 1, ch, Kind.PUNCT, w.punct_layout_key)
        elif not ch.isalnum() and ch.isprintable():
            yield Segment(i, i + 1, ch, Kind.PUNCT, w.punct_other)

        # --- A stray key typed by accident produces nothing.
        if zhuyin and self.drop_enabled and ch in self.droppable and not k.numpad:
            # letters only: ;; :: .. -- typed twice mean something (片語, 符號)
            double = ch in _LOWER and i + 1 < n and keys[i + 1].char == ch and not keys[i + 1].numpad
            yield Segment(i, i + 1, "", Kind.DROP, w.drop_double if double else w.drop)

        # --- Unfinished syllable / code at the end of the buffer, or where
        #     keys typed into the middle meet the rest (shown raw + hint).
        if not zhuyin and open_end:
            tail = "".join(x.char for x in keys[i:tok])
            if all(not x.numpad and x.char in _LOWER for x in keys[i:tok]) and (
                    (scheme == "pinyin" and tail in self.lex.pinyin.prefixes)
                    or (scheme == "cangjie" and len(tail) <= 5)):
                yield Segment(i, tok, tail, Kind.PENDING,
                              w.pending_pinyin if scheme == "pinyin" else w.pending_cangjie)
        elif open_end and 0 < tok - i <= 3:
            symbols = []
            for x in keys[i:tok]:
                sym = None if x.numpad else self.layout.symbol(x.char)
                if sym is None:
                    break
                symbols.append(sym)
            else:
                canon = bopomofo.canonical(symbols)
                if canon is not None and canon in self.lex.partial_syllables:
                    yield Segment(i, tok, "".join(x.char for x in keys[i:tok]), Kind.PENDING, w.pending)

        # --- Fallback so that every position stays reachable.
        yield Segment(i, i + 1, ch, Kind.LITERAL, w.literal)

    def _abbr_edges(self, keys: Sequence[Key], i: int, limit: int) -> Iterator[Segment]:
        """瘋狂模式: the zhuyin symbol keys from ``i`` (no tone keys) split into
        syllable beginnings — each part 1-3 symbols in syllable order — and
        matched against phrases whose syllables start that way."""
        syms: list[str] = []
        for j in range(i, min(limit, i + MAX_ABBR_KEYS)):
            k = keys[j]
            sym = None if k.numpad else self.layout.symbol(k.char)
            if sym is None:
                break
            syms.append(sym)
        if not syms:
            return
        cat = bopomofo.category
        # every way to split syms[0:m] into syllable beginnings, for each m
        stack: list[tuple[int, tuple[tuple[int, int], ...]]] = [(0, ())]
        while stack:
            pos, parts = stack.pop()
            if parts:
                yield from self._abbr_phrases(syms, i, parts)
            if pos >= len(syms) or len(parts) >= MAX_ABBR_SYLLABLES:
                continue
            end = pos + 1
            stack.append((end, parts + ((pos, end),)))
            while end < len(syms) and end - pos < 3 and cat(syms[end]) > cat(syms[end - 1]):
                end += 1
                stack.append((end, parts + ((pos, end),)))

    def _abbr_phrases(self, syms: list[str], i: int, parts: tuple[tuple[int, int], ...]) -> Iterator[Segment]:
        key = "".join(syms[a] for a, _ in parts)
        found = 0
        for phrase, reading, score in self.lex.abbreviations(key):
            readings = tuple(reading.split("-"))
            if len(readings) != len(parts):
                continue
            if any(bopomofo.components(syl)[:b - a] != syms[a:b] for syl, (a, b) in zip(readings, parts)):
                continue
            extra = sum(b - a - 1 for a, b in parts)
            bounds = tuple(i + a for a, _ in parts) + (i + parts[-1][1],)
            yield Segment(i, i + parts[-1][1], phrase, Kind.ZH,
                          score + self.w.abbr * len(parts) + self.w.abbr_symbol * extra, readings, bounds)
            found += 1
            if found >= 2:
                return

    def _zh_edges(self, i: int, limit: int, syllables: list[list[tuple[int, str, float]]],
                  cut: Sequence[int]) -> Iterator[Segment]:
        """Phrases from ``i`` up to ``limit`` (the next pin); each syllable
        starting at p ends by ``cut[p]`` (the next joint)."""
        lex = self.lex
        max_len = lex.max_phrase_syllables
        # Depth-first over syllable chains: (end, readings, bounds, channel cost)
        stack = [(end, (syl,), (i, end), cost) for end, syl, cost in syllables[i] if end <= cut[i]]
        while stack:
            end, readings, bounds, cost = stack.pop()
            reading = "-".join(readings)
            phrases = lex.phrases(reading)
            if phrases:
                text, score = phrases[0]
                yield Segment(i, end, text, Kind.ZH, score + cost, readings, bounds)
            if len(readings) < max_len and end < limit and lex.has_reading_prefix(reading):
                for nxt_end, syl, nxt_cost in syllables[end]:
                    if nxt_end <= cut[end]:
                        stack.append((nxt_end, readings + (syl,), bounds + (nxt_end,), cost + nxt_cost))

    def _en_score(self, word: str, delimited: bool = False) -> float:
        w = self.w
        score = self.lex.en_score(word.lower())
        if score is not None:
            score += w.en_offset
            if len(word) == 1 and word != "I" and word.lower() != "a":
                # A lone lowercase letter (o, i, e, u ...) is far more often
                # zhuyin (ㄟ, ㄛ = 喔) or a stray key than an English word —
                # unless it stands between spaces the user typed on purpose.
                score += w.en_delimited_letter if delimited else w.en_single_letter
            return score
        # Unknown token. Digits inside letters (y94vscode, k27) are typical of
        # zhuyin typed in mixed mode, not of English, so each one costs extra.
        digits = sum(c in _DIGITS for c in word)
        return w.en_unknown_base + w.en_unknown_per_char * len(word) + w.en_digit * digits

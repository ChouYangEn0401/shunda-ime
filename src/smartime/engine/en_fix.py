"""英文打錯自動更正: the English side of 注音打錯容錯.

Asked for: 「我打英文他似乎不會自己更正錯字」. Zhuyin typed fast comes out
right because the decoder also reads the usual slips (keys swapped, the tone
too early, a stray key); English words came out exactly as typed, and an
unknown word was even cut into odd pieces (wrold -> wr + old).

What counts as a slip, and why so narrow:

- Only a finished word: letters with no letter right before them, and a
  space or punctuation right after. Half a word while typing is never
  "corrected" (gaug is gauge in a moment), Enter sends exactly what is on
  screen, and a word glued to zhuyin keys (gamesu3) is a different problem
  (↓ 重新分組). A word left unfixed still has the fix in its ↓ list.
- Only words the word list does not know. The list (wordfreq, 80 000 words)
  has wand, newt, tome, hare… right next to and, new, time, are: going by
  frequency alone rewrote about a thousand real words. A word that is in the
  list is left alone — except the misspellings below, which are in the list
  only because people misspell them that often (teh, recieve, becuase).
- One slip, of the kinds fast typing makes: two neighbours swapped (tried
  first: thye is they, not the), one key missing, a key next to the right one,
  or one key too many — the last only when it is a neighbour of the key
  before or after it or a repeat, so pnpm, scss and jsonl stay (a free extra
  key turned them into npm, css and json).
- Only towards a common word (EN_COMMON), the user's own English words,
  and the curated terms, and never from one of those.

The decoder offers the correction as one more reading (decoder.Weights
.en_typo), shown with the amber ↺ like a reordered syllable, and ↓ has the
word as typed. Picking it teaches the user dictionary, which is checked
first: a word you kept is never corrected again.
"""

from __future__ import annotations

from collections.abc import Iterator

EN_COMMON = -5.0  # log10 frequency: the ~7 000 most common words

_LOWER = "abcdefghijklmnopqrstuvwxyz"
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_POS = {ch: (r, c) for r, row in enumerate(_ROWS) for c, ch in enumerate(row)}

# Misspellings common enough to be in the word list themselves. Each one is
# read as the word meant; tests/test_en_fix.py checks that every fix is in
# the list and no typo is a word in its own right.
KNOWN_TYPOS = {
    "teh": "the", "hte": "the", "adn": "and", "taht": "that", "thta": "that", "waht": "what",
    "wiht": "with", "wich": "which", "whcih": "which", "thier": "their", "theri": "their",
    "recieve": "receive", "recieved": "received", "recieving": "receiving", "beleive": "believe",
    "belive": "believe", "acheive": "achieve", "becuase": "because", "becasue": "because",
    "beacuse": "because", "definately": "definitely", "definatly": "definitely", "seperate": "separate",
    "seperately": "separately", "untill": "until", "occured": "occurred", "occurence": "occurrence",
    "occurance": "occurrence", "begining": "beginning", "tommorow": "tomorrow", "tommorrow": "tomorrow",
    "tomorow": "tomorrow", "comming": "coming", "adress": "address", "accomodate": "accommodate",
    "arguement": "argument", "calender": "calendar", "commited": "committed", "concious": "conscious",
    "enviroment": "environment", "enviornment": "environment", "existance": "existence",
    "goverment": "government", "grammer": "grammar", "independant": "independent", "knowlege": "knowledge",
    "millenium": "millennium", "neccessary": "necessary", "necesary": "necessary", "noticable": "noticeable",
    "occassion": "occasion", "persistant": "persistent", "posession": "possession", "prefered": "preferred",
    "publically": "publicly", "recomend": "recommend", "reccomend": "recommend", "refered": "referred",
    "relevent": "relevant", "religous": "religious", "responsiblity": "responsibility",
    "succesful": "successful", "sucessful": "successful", "suprise": "surprise", "tendancy": "tendency",
    "truely": "truly", "wierd": "weird", "accross": "across", "agressive": "aggressive",
    "apparant": "apparent", "appearence": "appearance", "basicly": "basically", "buisness": "business",
    "bussiness": "business", "collegue": "colleague", "comittee": "committee", "commitee": "committee",
    "completly": "completely", "concensus": "consensus", "dissapoint": "disappoint",
    "embarass": "embarrass", "excercise": "exercise", "experiance": "experience", "familar": "familiar",
    "finaly": "finally", "foriegn": "foreign", "freind": "friend", "fourty": "forty", "happend": "happened",
    "immediatly": "immediately", "interupt": "interrupt", "intresting": "interesting", "lenght": "length",
    "libary": "library", "lisence": "license", "maintainance": "maintenance", "oppurtunity": "opportunity",
    "paralel": "parallel", "peice": "piece", "posible": "possible", "rember": "remember",
    "remeber": "remember", "resturant": "restaurant", "similiar": "similar", "sincerly": "sincerely",
    "speach": "speech", "strenght": "strength", "temperture": "temperature", "tounge": "tongue",
    "unfortunatly": "unfortunately", "usualy": "usually", "vehical": "vehicle", "writting": "writing",
    "fucntion": "function", "funtion": "function", "retrun": "return", "pyhton": "python",
    "databse": "database", "reponse": "response", "widht": "width", "heigth": "height",
    "paramter": "parameter", "varible": "variable", "udpate": "update", "chnage": "change",
    "mesage": "message", "managment": "management", "developement": "development", "enginner": "engineer",
    "infomation": "information",
}


def _adjacent(a: str, b: str) -> bool:
    """Next to each other on a QWERTY keyboard (rows are staggered)."""
    pa, pb = _POS.get(a), _POS.get(b)
    if pa is None or pb is None:
        return False
    (ra, ca), (rb, cb) = pa, pb
    if ra == rb:
        return abs(ca - cb) == 1
    if rb == ra - 1:
        return cb in (ca, ca + 1)
    if rb == ra + 1:
        return cb in (ca - 1, ca)
    return False


def slips(word: str) -> Iterator[tuple[int, str]]:
    """(rank, word it may have been) for one slip; rank 0 = two neighbours
    swapped, the most typical slip when typing fast; 1 = the others."""
    n = len(word)
    for i in range(n - 1):
        if word[i] != word[i + 1]:
            yield 0, word[:i] + word[i + 1] + word[i] + word[i + 2:]
    for i in range(n + 1):  # one key missing
        for c in _LOWER:
            yield 1, word[:i] + c + word[i:]
    for i in range(n):
        ch = word[i]
        for c in _LOWER:  # the key next to the right one
            if c != ch and _adjacent(ch, c):
                yield 1, word[:i] + c + word[i + 1:]
        # one key too many: hit along with a neighbour, or twice
        near = [word[k] for k in (i - 1, i + 1) if 0 <= k < n]
        if any(x == ch or _adjacent(x, ch) for x in near):
            yield 1, word[:i] + word[i + 1:]


def recase(fixed: str, typed: str) -> str:
    """The fix in the case the word was typed in (Teh -> The)."""
    return fixed[:1].upper() + fixed[1:] if typed[:1].isupper() else fixed


def correction(lex, word: str) -> tuple[str, bool] | None:
    """(the word meant, known misspelling?) for a finished English word that
    looks like a slip, else None. ``lex`` is a Lexicon."""
    if not word.isascii() or not word.isalpha():
        return None
    lower = word.lower()
    if word != lower and word != lower.capitalize():
        return None  # ABC, camelCase: names, code, acronyms
    if lex.user_en(lower) or lex.en_curated(lower):
        return None  # yours, or a term on purpose
    fixed = KNOWN_TYPOS.get(lower)
    if fixed is not None:
        return recase(fixed, word), True
    if len(lower) < 4 or lex.en_score(lower) is not None:
        return None
    best: tuple[int, float, str] | None = None
    for rank, cand in slips(lower):
        if best is not None and rank > best[0]:
            break  # a swap was found: other slips do not compete with it
        score = lex.en_score(cand)
        if score is None or not (score >= EN_COMMON or lex.user_en(cand) or lex.en_curated(cand)):
            continue
        if best is None or score > best[1]:
            best = (rank, score, cand)
    return (recase(best[2], word), False) if best else None

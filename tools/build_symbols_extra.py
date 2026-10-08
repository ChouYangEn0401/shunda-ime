"""Generate data/extra/symbols_extra.json: a much bigger, searchable symbol
catalogue than the hand-picked EMOJI_SYMBOLS, pulled from the official
Unicode Character Database (public-domain reference data — not a scrape of
any particular site, and not bundled by the installer: tools/build_installer.py
stages data/generated/smartime.db by name, never the whole data/ tree).

Users fetch the generated file themselves from Settings, a toggle + download
button the same shape as the voice models (src/smartime/voice/models.py):
nothing extra ships at install time, so startup stays exactly as fast as
before for anyone who never turns it on.

Run:  .venv\\Scripts\\python tools\\build_symbols_extra.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

UNICODE_VERSION = "16.0.0"
BASE = f"https://www.unicode.org/Public/{UNICODE_VERSION}/ucd/"
DOWNLOADS = {
    # name: (url, sha256) — pinned so a re-run is reproducible
    "UnicodeData.txt": (
        BASE + "UnicodeData.txt",
        "ff58e5823bd095166564a006e47d111130813dcf8bf234ef79fa51a870edb48f",
    ),
    "Blocks.txt": (
        BASE + "Blocks.txt",
        "f3907b395d410f1b97342292ca6bc83dd12eb4b205f2a0c48efdef99e517d7b0",
    ),
}
CACHE = ROOT / "build" / "cache"
OUT = ROOT / "data" / "extra" / "symbols_extra.json"

# BMP range this generator draws from, and the one plain-symbol block inside
# it we deliberately leave out (Supplemental Mathematical Operators, 2A00-
# 2AFF): too technical, too rarely useful, and the least likely to actually
# carry a Segoe UI Symbol glyph (this backend draws through plain GDI, see
# the note in src/smartime/engine/symbols.py — no colour-font support, so a
# missing glyph shows as a tofu box, not a fallback).
RANGE = (0x2100, 0x2BFF)
BLOCKS_ZH = {
    "Letterlike Symbols": "字母符號",
    "Arrows": "箭頭",
    "Mathematical Operators": "數學",
    "Miscellaneous Technical": "技術符號",
    "Enclosed Alphanumerics": "圈號",
    "Geometric Shapes": "圖形",
    "Miscellaneous Symbols": "雜項符號",
    "Dingbats": "裝飾符號",
    "Miscellaneous Symbols and Arrows": "符號與箭頭",
}
STOPWORDS = {"with", "and", "for", "the", "of", "to", "sign", "symbol"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def fetch(name: str) -> Path:
    url, digest = DOWNLOADS[name]
    path = CACHE / f"{name.removesuffix('.txt')}-{UNICODE_VERSION}.txt"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"[fetch] {url}")
        tmp = path.with_suffix(path.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https URL, checksummed below
        tmp.replace(path)
    got = sha256(path)
    if got != digest:
        raise SystemExit(f"checksum mismatch for {name}: got {got}, expected {digest}")
    return path


def load_blocks(path: Path) -> list[tuple[int, int, str]]:
    blocks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ".." not in line:
            continue
        rng, name = line.split(";", 1)
        start, end = rng.split("..")
        blocks.append((int(start, 16), int(end, 16), name.strip()))
    return blocks


def block_name(blocks: list[tuple[int, int, str]], codepoint: int) -> str | None:
    for start, end, name in blocks:
        if start <= codepoint <= end:
            return name
    return None


def tags_from_name(name: str) -> list[str]:
    words = re.split(r"[\s-]+", name.lower())
    return [w for w in dict.fromkeys(words) if w and w not in STOPWORDS]


def already_builtin() -> set[str]:
    from smartime.engine.symbols import CATEGORIES, EMOJI_SYMBOLS

    known = {sym for sym, _cat, _tags in EMOJI_SYMBOLS}
    for _name, groups in CATEGORIES:
        for _label, chars in groups:
            known.update(chars)
    return known


def main() -> None:
    unicode_data = fetch("UnicodeData.txt")
    blocks_file = fetch("Blocks.txt")
    allowed_blocks = [(s, e, n) for s, e, n in load_blocks(blocks_file) if n in BLOCKS_ZH]
    skip = already_builtin()

    entries: list[tuple[str, str, list[str]]] = []
    for line in unicode_data.read_text(encoding="utf-8").splitlines():
        fields = line.split(";")
        if len(fields) < 3:
            continue
        codepoint = int(fields[0], 16)
        if not (RANGE[0] <= codepoint <= RANGE[1]):
            continue
        name, category = fields[1], fields[2]
        if not category.startswith("S"):  # Sm/Sc/Sk/So only — no letters, no punctuation
            continue
        block = block_name(allowed_blocks, codepoint)
        if block is None:  # inside RANGE but in a block we didn't allowlist
            continue
        sym = chr(codepoint)
        if sym in skip:  # already in the hand-picked, always-available set
            continue
        entries.append((sym, BLOCKS_ZH[block], tags_from_name(name)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    by_block: dict[str, int] = {}
    for _sym, cat, _tags in entries:
        by_block[cat] = by_block.get(cat, 0) + 1
    print(f"[build] {OUT.relative_to(ROOT)}  {len(entries)} symbols")
    for cat, n in sorted(by_block.items(), key=lambda kv: -kv[1]):
        print(f"         {cat}: {n}")


if __name__ == "__main__":
    main()

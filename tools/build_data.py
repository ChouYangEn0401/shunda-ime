"""Build the system lexicon (data/generated/smartime.db).

Pipeline
--------
1. Download McBopomofo's ``Source/Data`` at a pinned commit (MIT licensed).
2. Run McBopomofo's own curation pipeline (frequency_builder -> main_compiler
   -> postprocess) to get ``data.txt``: ``<reading> <phrase> <log10 score>``.
   Re-using their pipeline (instead of re-implementing it) keeps their
   hand-tuned heterophony rules and post-process assertions intact.
3. Export an English unigram list from ``wordfreq`` (CC BY-SA 4.0 data).
4. Merge our own curated term list (``data/lexicon/en_terms.txt``).
5. Download the Cangjie 5 code table of 倉頡五代補完計劃 at a pinned commit
   (MIT licensed; Traditional-first, Taiwan-preference order) and keep the
   characters the lexicon knows (they have readings, so they can be learned).
6. Write everything into a single read-only SQLite file used by the engine.
   ``zh.plain`` is the reading without tone marks, for toneless pinyin.

Run:  .venv\\Scripts\\python tools\\build_data.py   (packages: requirements.txt)
"""

from __future__ import annotations

import argparse
import io
import math
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "data" / "vendor"
GENERATED_DIR = ROOT / "data" / "generated"
LEXICON_DIR = ROOT / "data" / "lexicon"

MCBOPOMOFO_SHA = "be6564acad6c4d3265c34a2e1a872d80f9db6068"  # 2026-09-29
MCBOPOMOFO_URL = f"https://codeload.github.com/openvanilla/McBopomofo/tar.gz/{MCBOPOMOFO_SHA}"

CANGJIE5_SHA = "e4a4242f518ab0d34066bbd8aa44cb0cefd61db2"  # 2026-09-20
CANGJIE5_BASE = f"https://raw.githubusercontent.com/Jackchows/Cangjie5/{CANGJIE5_SHA}/"
CANGJIE5_FILES = {  # file -> SHA-256
    "Cangjie5_TC.txt": "963d1986b3d5c710a3c013b93f2817a2b4562cf5a1aace12164598f74a3aca6b",
    "LICENSE": "cf2746abe0b37ba14fb0e735eb868d418e4d335b9040887f579da958f95ffa77",
}
CANGJIE_RE = re.compile(r"^[a-z]{1,5}$")
TONE_MARKS = str.maketrans("", "", "ˊˇˋ˙")

BOPOMOFO_RE = re.compile(r"^[ㄅ-ㄩˊˇˋ˙]+(-[ㄅ-ㄩˊˇˋ˙]+)*$")
EN_WORD_RE = re.compile(r"^[a-z][a-z0-9]*(?:['.-][a-z0-9]+)*$")
EN_TERM_RE = re.compile(r"^(?=.*[a-z])[a-z0-9]+$")

EN_TOP_N = 80_000
# Curated terms get at least this log10 frequency: a common word, so that
# a known term (mvp, vscode) beats a rare single Chinese character (勳)
# even after paying the Chinese<->English switch cost.
EN_TERM_FLOOR = -3.5


def fetch_mcbopomofo() -> Path:
    data_dir = VENDOR_DIR / f"McBopomofo-{MCBOPOMOFO_SHA[:12]}" / "Data"
    if (data_dir / "BPMFBase.txt").exists():
        return data_dir
    print(f"[build] downloading McBopomofo @ {MCBOPOMOFO_SHA[:12]} ...")
    with urllib.request.urlopen(MCBOPOMOFO_URL, timeout=120) as resp:
        blob = resp.read()
    prefix = f"McBopomofo-{MCBOPOMOFO_SHA}/Source/Data/"
    data_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.startswith(prefix) or not member.isfile():
                continue
            rel = member.name[len(prefix):]
            target = data_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    # Keep the upstream license next to the data for attribution.
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        lic = tar.extractfile(f"McBopomofo-{MCBOPOMOFO_SHA}/LICENSE.txt")
        if lic is not None:
            (data_dir.parent / "LICENSE.txt").write_bytes(lic.read())
    return data_dir


def fetch_cangjie5() -> Path:
    """Cangjie5_TC.txt (and its LICENSE) at the pinned commit, verified."""
    import hashlib

    folder = VENDOR_DIR / f"Cangjie5-{CANGJIE5_SHA[:12]}"
    folder.mkdir(parents=True, exist_ok=True)
    for name, digest in CANGJIE5_FILES.items():
        path = folder / name
        if not path.exists():
            print(f"[build] downloading Cangjie5/{name} @ {CANGJIE5_SHA[:12]} ...")
            with urllib.request.urlopen(CANGJIE5_BASE + name, timeout=120) as resp:
                path.write_bytes(resp.read())
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            path.unlink()
            raise SystemExit(f"[build] {name}: SHA-256 mismatch ({actual}); download again")
    return folder / "Cangjie5_TC.txt"


def load_cangjie_rows(table: Path, known_chars: set[str]) -> list[tuple[str, str, int]]:
    """(code, char, rank): rank = position among the characters sharing the
    code, as ordered by the table (frequency, Taiwan preference)."""
    rows: list[tuple[str, str, int]] = []
    rank: dict[str, int] = {}
    in_body = False
    with open(table, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if not in_body:
                in_body = parts[:2] == ["漢字", "倉頡碼"]
                continue
            if len(parts) < 2 or not CANGJIE_RE.match(parts[1]):
                continue
            char, code = parts[0], parts[1]
            if char not in known_chars:
                continue
            r = rank.get(code, 0)
            rank[code] = r + 1
            rows.append((code, char, r))
    if len(rows) < 15000:
        raise SystemExit(f"[build] Cangjie table looks wrong: only {len(rows)} rows")
    return rows


def run_mcbopomofo_pipeline(data_dir: Path) -> Path:
    out = data_dir / "data.txt"
    if out.exists():
        return out
    py = sys.executable
    env_cwd = str(data_dir)

    def run(*args: str) -> None:
        subprocess.run([py, "-X", "utf8", "-m", *args], cwd=env_cwd, check=True)

    print("[build] McBopomofo frequency_builder ...")
    run("curation.builders.frequency_builder")
    print("[build] McBopomofo main_compiler ...")
    run(
        "curation.compilers.main_compiler",
        "--heterophony1", "heterophony1.list",
        "--heterophony2", "heterophony2.list",
        "--heterophony3", "heterophony3.list",
        "--phrase_freq", "PhraseFreq.txt",
        "--bpmf_mappings", "BPMFMappings.txt",
        "--bpmf_base", "BPMFBase.txt",
        "--punctuations", "BPMFPunctuations.txt",
        "--symbols", "Symbols.txt",
        "--macros", "Macros.txt",
        "--output", "data-raw.txt",
    )
    print("[build] McBopomofo postprocess ...")
    run(
        "curation.compilers.postprocess",
        "--input", "data-raw.txt",
        "--directive", "Postprocess.txt",
        "--output", "data.txt",
    )
    return out


def load_zh_rows(data_txt: Path) -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float]] = []
    with open(data_txt, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split(" ")
            if len(parts) != 3:
                continue
            reading, phrase, score = parts
            # Skip punctuation/symbol/macro entries (keys like "_punctuation_x").
            if not BOPOMOFO_RE.match(reading):
                continue
            syllables = reading.split("-")
            # Drop tone-mark-only entries (e.g. "ˇ" -> "ˇ"); every syllable
            # must contain at least one real symbol.
            if any(s.strip("ˊˇˋ˙") == "" for s in syllables):
                continue
            # The engine maps one displayed character to one syllable, so
            # entries like "卡拉OK" whose length differs are skipped.
            if len(phrase) != len(syllables):
                continue
            score_f = float(score)
            if score_f <= -50:  # McBopomofo's "unknown" sentinel (-99)
                score_f = -9.0
            rows.append((reading, phrase, score_f))
    return rows


def load_en_rows() -> list[tuple[str, float, int]]:
    from wordfreq import top_n_list, word_frequency

    rows: dict[str, tuple[float, int]] = {}
    for word in top_n_list("en", EN_TOP_N):
        if not EN_WORD_RE.match(word):
            continue
        freq = word_frequency(word, "en")
        if freq <= 0:
            continue
        rows[word] = (math.log10(freq), 0)

    terms_file = LEXICON_DIR / "en_terms.txt"
    if terms_file.exists():
        for line in terms_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            word = line.lower()
            if not EN_TERM_RE.match(word):
                raise ValueError(f"en_terms.txt: unsupported term {line!r}")
            freq = word_frequency(word, "en")
            score = max(math.log10(freq) if freq > 0 else -99.0, EN_TERM_FLOOR)
            rows[word] = (score, 1)
    return [(w, s, t) for w, (s, t) in rows.items()]


def write_db(zh_rows, en_rows, cj_rows, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE zh (reading TEXT NOT NULL, phrase TEXT NOT NULL, score REAL NOT NULL, plain TEXT NOT NULL);
        CREATE TABLE en (word TEXT PRIMARY KEY, score REAL NOT NULL, curated INTEGER NOT NULL);
        CREATE TABLE cangjie (code TEXT NOT NULL, char TEXT NOT NULL, rank INTEGER NOT NULL);
        """
    )
    con.executemany("INSERT INTO zh VALUES (?, ?, ?, ?)",
                    ((r, p, s, r.translate(TONE_MARKS)) for r, p, s in zh_rows))
    con.executemany("INSERT INTO en VALUES (?, ?, ?)", en_rows)
    con.executemany("INSERT INTO cangjie VALUES (?, ?, ?)", cj_rows)
    con.executescript(
        """
        CREATE INDEX zh_reading ON zh(reading, score DESC);
        CREATE INDEX zh_phrase ON zh(phrase);
        CREATE INDEX zh_plain ON zh(plain, score DESC);
        CREATE INDEX cangjie_code ON cangjie(code, rank);
        CREATE INDEX cangjie_char ON cangjie(char);
        """
    )
    meta = {
        "schema": "2",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mcbopomofo_sha": MCBOPOMOFO_SHA,
        "en_source": f"wordfreq top {EN_TOP_N}",
        "cangjie5_sha": CANGJIE5_SHA,
        "cangjie_rows": str(len(cj_rows)),
        "zh_rows": str(len(zh_rows)),
        "en_rows": str(len(en_rows)),
    }
    con.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=GENERATED_DIR / "smartime.db")
    args = parser.parse_args()

    data_dir = fetch_mcbopomofo()
    data_txt = run_mcbopomofo_pipeline(data_dir)
    zh_rows = load_zh_rows(data_txt)
    en_rows = load_en_rows()
    single_chars = {p for r, p, _ in zh_rows if "-" not in r}
    cj_rows = load_cangjie_rows(fetch_cangjie5(), single_chars)
    try:
        write_db(zh_rows, en_rows, cj_rows, args.out)
    except PermissionError:
        sys.exit(
            f"[build] cannot replace {args.out}: it is open by the running IME backend.\n"
            "        Use: powershell -ExecutionPolicy Bypass -File scripts\\dev-reload.ps1 -Rebuild"
        )
    print(f"[build] wrote {args.out}  zh={len(zh_rows):,}  en={len(en_rows):,}  cangjie={len(cj_rows):,}")


if __name__ == "__main__":
    main()

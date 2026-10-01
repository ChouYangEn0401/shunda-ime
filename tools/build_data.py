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
5. Write everything into a single read-only SQLite file used by the engine.

Run:  uv run --group build-data python tools/build_data.py
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

BOPOMOFO_RE = re.compile(r"^[ㄅ-ㄩˊˇˋ˙]+(-[ㄅ-ㄩˊˇˋ˙]+)*$")
EN_WORD_RE = re.compile(r"^[a-z][a-z0-9]*(?:['.-][a-z0-9]+)*$")
EN_TERM_RE = re.compile(r"^(?=.*[a-z])[a-z0-9]+$")

EN_TOP_N = 80_000
# Curated terms get at least this log10 frequency (roughly "common word").
EN_TERM_FLOOR = -5.0


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


def write_db(zh_rows, en_rows, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE zh (reading TEXT NOT NULL, phrase TEXT NOT NULL, score REAL NOT NULL);
        CREATE TABLE en (word TEXT PRIMARY KEY, score REAL NOT NULL, curated INTEGER NOT NULL);
        """
    )
    con.executemany("INSERT INTO zh VALUES (?, ?, ?)", zh_rows)
    con.executemany("INSERT INTO en VALUES (?, ?, ?)", en_rows)
    con.executescript(
        """
        CREATE INDEX zh_reading ON zh(reading, score DESC);
        CREATE INDEX zh_phrase ON zh(phrase);
        """
    )
    meta = {
        "schema": "1",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mcbopomofo_sha": MCBOPOMOFO_SHA,
        "en_source": f"wordfreq top {EN_TOP_N}",
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
    write_db(zh_rows, en_rows, args.out)
    print(f"[build] wrote {args.out}  zh={len(zh_rows):,}  en={len(en_rows):,}")


if __name__ == "__main__":
    main()

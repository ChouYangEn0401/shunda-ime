"""Platform-independent input engine (stdlib only).

Layers, bottom-up:
    bopomofo  -> syllable structure (initial / medial / final / tone)
    layouts   -> physical key <-> bopomofo symbol
    lexicon   -> read-only SQLite dictionary (Chinese phrases, English words)
    decoder   -> lattice + Viterbi over the raw key buffer
    session   -> per-input-context state machine (composition, candidates, commit)
"""

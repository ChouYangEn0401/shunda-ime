import json

from smartime.config import Config


def test_old_mode_name_is_migrated(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"start_mode": "mixed"}), encoding="utf-8")
    assert Config.load(p).start_mode == "auto"


def test_invalid_values_fall_back_to_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"start_mode": "klingon", "candidates_per_page": 99, "spelling_hint": "yes"}),
                 encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.start_mode == "auto"
    assert cfg.candidates_per_page == 9
    assert cfg.spelling_hint is True


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg = Config()
    cfg.start_mode = "chinese"
    cfg.halfwidth_symbols = '"<>'
    cfg.save(p)
    loaded = Config.load(p)
    assert loaded.start_mode == "chinese" and loaded.halfwidth_symbols == '"<>'

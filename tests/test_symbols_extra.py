"""The optional, downloadable symbol pack (src/smartime/engine/symbols_extra.py):
never fetched or read until the user asks, and tolerant of a missing or
half-written file (it is just a cache the user can delete)."""

import json

import pytest

from smartime.engine import symbols_extra


class FakeResponse:
    """Just enough of urllib's response object for download() to read."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk, self._pos = self._data[self._pos:], len(self._data)
        else:
            chunk = self._data[self._pos:self._pos + n]
            self._pos += len(chunk)
        return chunk


def test_load_is_empty_before_anything_is_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(symbols_extra, "path", lambda: tmp_path / "symbols-extra.json")
    assert symbols_extra.load() == []
    assert symbols_extra.status() == {"installed": False, "count": 0}


def test_load_keeps_only_well_formed_bmp_entries(tmp_path, monkeypatch):
    target = tmp_path / "symbols-extra.json"
    monkeypatch.setattr(symbols_extra, "path", lambda: target)
    target.write_text(json.dumps([
        ["★", "星星", ["star"]],
        ["★★", "星星", ["star"]],  # not a single character
        ["★", "", ["star"]],  # no category
        ["★", "星星", "star"],  # tags not a list
        ["not-a-triple"],
        [1, "星星", ["star"]],  # not a string symbol
    ]), encoding="utf-8")
    assert symbols_extra.load() == [("★", "星星", ("star",))]
    assert symbols_extra.status() == {"installed": True, "count": 1}


def test_load_tolerates_a_corrupt_or_missing_file(tmp_path, monkeypatch):
    target = tmp_path / "symbols-extra.json"
    monkeypatch.setattr(symbols_extra, "path", lambda: target)
    target.write_text("not json", encoding="utf-8")
    assert symbols_extra.load() == []
    target.unlink()
    assert symbols_extra.load() == []


def test_download_saves_the_file_and_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(symbols_extra, "path", lambda: tmp_path / "symbols-extra.json")
    payload = json.dumps([["★", "星星", ["star"]], ["☆", "星星", ["star", "空心"]]]).encode("utf-8")
    monkeypatch.setattr(symbols_extra.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse(payload))

    progress = []
    result = symbols_extra.download(lambda done, total: progress.append((done, total)))

    assert result == symbols_extra.path()
    assert symbols_extra.load() == [("★", "星星", ("star",)), ("☆", "星星", ("star", "空心"))]
    assert progress[-1] == (len(payload), len(payload))


def test_download_leaves_the_old_file_alone_if_the_new_one_is_bad(tmp_path, monkeypatch):
    """Written through a .tmp + replace, and json-validated first — a
    truncated or garbled response must not clobber a working download."""
    target = tmp_path / "symbols-extra.json"
    monkeypatch.setattr(symbols_extra, "path", lambda: target)
    target.write_text(json.dumps([["★", "星星", ["star"]]]), encoding="utf-8")
    monkeypatch.setattr(symbols_extra.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse(b"not json"))

    with pytest.raises(ValueError):
        symbols_extra.download()
    assert symbols_extra.load() == [("★", "星星", ("star",))]
    assert not target.with_suffix(".tmp").exists()

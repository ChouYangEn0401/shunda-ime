"""The settings page's HTML is edited by hand (and by wording passes): a
broken tag shows up as raw text on the page, not as an error anywhere."""

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src/smartime/settings/ui"


def test_no_tag_lost_its_name():
    """「用哪一邊的 Shift 在< href="#keys"…」 was on the 一般 page in
    0.11.0-alpha.3: a wording pass dropped the a of <a."""
    html = (UI / "index.html").read_text(encoding="utf-8")
    broken = re.findall(r"<\s+[a-z-]+=\"[^\"]*\"", html)
    assert not broken, broken


def test_links_open_and_close_in_pairs():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert len(re.findall(r"<a[\s>]", html)) == html.count("</a>")

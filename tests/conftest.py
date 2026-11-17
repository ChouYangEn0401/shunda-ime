import pytest

from smartime import paths
from smartime.config import Config
from smartime.engine.decoder import Decoder
from smartime.engine.layouts import DACHEN
from smartime.engine.lexicon import Lexicon
from smartime.engine.session import Engine, Session


@pytest.fixture(autouse=True)
def isolated_user_dir(tmp_path, monkeypatch):
    """Never touch the real %APPDATA%\\SmartIME from tests."""
    monkeypatch.setenv("SMARTIME_USER_DIR", str(tmp_path / "user"))
    # and never open real panel windows on the desktop, or type into it
    monkeypatch.setenv("SMARTIME_NO_PANEL", "1")
    monkeypatch.setenv("SMARTIME_NO_SENDINPUT", "1")
    # and never go online on a schedule (update.start_background)
    monkeypatch.setenv("SMARTIME_NO_UPDATE_THREAD", "1")
    # the tray icon's update dot reads update.json at most every few seconds;
    # a test must not see the previous test's answer
    from smartime import update

    monkeypatch.setattr(update, "_seen", {"mtime": -1.0, "looked": 0.0, "version": ""})


@pytest.fixture(scope="session")
def lexicon():
    db = paths.system_db_path()
    if not db.exists():
        pytest.skip("lexicon not built; run: python tools/build_data.py")
    lex = Lexicon(db)
    yield lex
    lex.close()


@pytest.fixture(scope="session")
def decoder(lexicon):
    return Decoder(lexicon, DACHEN)


@pytest.fixture
def engine(lexicon, decoder):
    return Engine(lexicon=lexicon, layout=DACHEN, decoder=decoder, config=Config())


@pytest.fixture
def session(engine):
    return Session(engine)

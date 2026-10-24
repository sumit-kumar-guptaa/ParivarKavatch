"""Test environment: isolated SQLite DB, mock providers, clean state per test."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TEMP_DIR = Path(tempfile.mkdtemp(prefix="parivar_kavach_tests_"))
_DB_PATH = (_TEMP_DIR / "test.db").as_posix()

os.environ["USE_MOCKS"] = "true"
os.environ["USE_MOCK_STT"] = "true"
os.environ["USE_MOCK_TTS"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["ALERT_LOG_PATH"] = str(_TEMP_DIR / "alerts.log")
os.environ["PHONE_FILTER"] = "true"
os.environ["FAMILY_ALERT_ON_END"] = "true"


@pytest.fixture(autouse=True)
def clean_state():
    from app.session import clear_sessions
    from db.init import engine
    from db.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    clear_sessions()
    yield
    clear_sessions()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

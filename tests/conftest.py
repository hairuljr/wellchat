"""Test memakai dataset asli di data/raw (tidak di-commit); otomatis di-skip bila dataset tidak ada."""

from pathlib import Path

import pytest

from wellchat.ingest import ingest
from wellchat.store import connect

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    if not any(RAW.rglob("*.pdf")):
        pytest.skip("dataset not found in data/raw (see README)")
    out = tmp_path_factory.mktemp("build")
    ingest(RAW, out / "parsed", out / "test.db", force=True, log=lambda *_: None)
    return out


@pytest.fixture()
def db_conn(built):
    conn = connect(built / "test.db")
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def parsed_dir(built):
    return built / "parsed"

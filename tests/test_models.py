"""Pilihan model di dropdown UI dan perilakunya di aplikasi Streamlit."""

from pathlib import Path
from unittest import mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from wellchat import config, models

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture()
def app_env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OPENAI_MODEL", "model-a")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "missing.db")  # sidebar tetap dirender tanpa dataset
    st.cache_data.clear()


def _run():
    return AppTest.from_file(APP, default_timeout=30).run()


def test_choices_keep_openai_model_first_and_follow_the_allowlist(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_MODEL", "model-a")
    monkeypatch.setattr(config, "MODEL_ALLOWLIST", ["model-c", "model-x", "model-b", "model-a"])
    assert models.model_choices(["model-b", "model-a", "model-c", "embedding-1"]) == ["model-a", "model-c", "model-b"]


def test_no_allowlist_means_no_dropdown(app_env, monkeypatch):
    monkeypatch.setattr(config, "MODEL_ALLOWLIST", [])
    with mock.patch.object(models, "endpoint_models") as fetch:
        at = _run()
    assert not at.exception and not at.selectbox and not fetch.called


def test_allowlist_without_match_falls_back_to_openai_model(app_env, monkeypatch):
    monkeypatch.setattr(config, "MODEL_ALLOWLIST", ["other-provider/model"])
    with mock.patch.object(models, "endpoint_models", return_value=["gpt-x"]):
        at = _run()
    assert not at.exception and not at.selectbox
    assert any("model-a" in c.value for c in at.caption)


def test_endpoint_error_falls_back_to_openai_model(app_env, monkeypatch):
    monkeypatch.setattr(config, "MODEL_ALLOWLIST", ["model-b"])
    with mock.patch.object(models, "endpoint_models", side_effect=RuntimeError("401")):
        at = _run()
    assert not at.exception and not at.selectbox


def test_model_choice_stays_in_its_own_session(app_env, monkeypatch):
    monkeypatch.setattr(config, "MODEL_ALLOWLIST", ["model-b"])
    with mock.patch.object(models, "endpoint_models", return_value=["model-a", "model-b"]):
        a = _run()
        a.selectbox(key="model_choice").select("model-b").run()
        b = _run()
    assert a.selectbox(key="model_choice").value == "model-b"
    assert b.selectbox(key="model_choice").value == "model-a" and config.OPENAI_MODEL == "model-a"

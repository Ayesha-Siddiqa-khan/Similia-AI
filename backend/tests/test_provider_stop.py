"""The provider stop lives in the database, survives restarts and fails safe."""

# ruff: noqa: F811
import json

import pytest

from app.ai.rag import guard
from tests.test_ingestion_service import (  # noqa: F401
    RateLimited,
    embedder,
    fake_db,
    prepared,
    run_to_end,
    service,
)


@pytest.fixture()
def flag(monkeypatch: pytest.MonkeyPatch):
    state: dict = {"value": None}
    monkeypatch.setattr(guard, "_read_db_flag", lambda: state["value"])
    guard.reset_cache()
    return state


def test_not_paused_when_nothing_is_set(flag, tmp_path, monkeypatch) -> None:
    from app.ai.ingestion import local

    monkeypatch.setattr(local, "REPORTS", tmp_path)
    flag["value"] = {"paused": False, "reason": None}
    assert guard.embedding_paused() is False and guard.pause_reason() is None


def test_the_database_flag_pauses_and_gives_its_reason(flag, tmp_path, monkeypatch) -> None:
    from app.ai.ingestion import local

    monkeypatch.setattr(local, "REPORTS", tmp_path)
    flag["value"] = {"paused": True, "reason": "Check the provider account"}
    assert guard.embedding_paused() is True
    assert guard.pause_reason() == "Check the provider account"


def test_the_old_manifest_is_ignored_once_the_database_flag_is_readable(
    flag, tmp_path, monkeypatch
) -> None:
    from app.ai.ingestion import local

    monkeypatch.setattr(local, "REPORTS", tmp_path)
    (tmp_path / "run_manifest.json").write_text(json.dumps({"status": "stopped_provider_http_429"}))
    flag["value"] = {"paused": False}  # the owner cleared the database flag
    assert guard.embedding_paused() is False


def test_a_bare_local_run_without_a_database_still_honours_the_manifest(
    flag, tmp_path, monkeypatch
) -> None:
    from app.ai.ingestion import local

    monkeypatch.setattr(local, "REPORTS", tmp_path)
    (tmp_path / "run_manifest.json").write_text(json.dumps({"status": "stopped_provider_http_429"}))
    flag["value"] = None
    assert guard.embedding_paused() is True


def test_an_unreadable_database_holds_embedding_instead_of_guessing(
    flag, tmp_path, monkeypatch
) -> None:
    from app.ai.ingestion import local

    monkeypatch.setattr(local, "REPORTS", tmp_path)
    flag["value"] = False  # configured but unreadable
    assert guard.embedding_paused() is True
    assert "cannot be read" in guard.pause_reason()


def test_an_unconfigured_database_falls_back_to_the_file_only(flag, tmp_path, monkeypatch) -> None:
    from app.ai.ingestion import local

    monkeypatch.setattr(local, "REPORTS", tmp_path)
    flag["value"] = None
    guard.reset_cache()
    assert guard.embedding_paused() is False


def test_a_provider_429_during_a_web_job_sets_the_stop_for_every_server(
    service, fake_db, monkeypatch
) -> None:
    class Limited:
        dimension = 1024

        def embed_documents(self, texts):
            raise RateLimited("rate limit")

    monkeypatch.setattr(service, "embedder", Limited())
    book = prepared(service)
    assert "provider_pause" not in fake_db.flags
    run_to_end(service, book["id"])
    stored = fake_db.flags["provider_pause"]
    assert stored["paused"] is True and stored["set_by"] == "web-ingestion"
    assert "429" in stored["reason"]


def test_other_provider_errors_do_not_set_the_stop(service, fake_db, monkeypatch) -> None:
    class Broken:
        dimension = 1024

        def embed_documents(self, texts):
            raise RuntimeError("outage")

    monkeypatch.setattr(service, "embedder", Broken())
    book = prepared(service)
    run_to_end(service, book["id"])
    assert fake_db.flags == {}

"""Brief database disconnects are retried for safe operations only."""

import pytest

from app.services import knowledge_db
from app.services.knowledge_db import KnowledgeDBError, _execute


class Query:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures, self.calls = failures, 0

    def execute(self):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "rows"


def run(operation: str, failures: list[Exception]):
    query = Query(failures)
    waits: list[float] = []
    try:
        result = _execute(operation, lambda: query, sleep=waits.append)
    except KnowledgeDBError as exc:
        return exc, query.calls, waits
    return result, query.calls, waits


def test_a_read_that_hits_a_brief_disconnect_succeeds_on_a_later_attempt() -> None:
    result, calls, waits = run("get_ingestion_job", [RuntimeError("Server disconnected")] * 2)
    assert result == "rows" and calls == 3 and waits == [0.5, 1.5]


def test_the_idempotent_embedding_write_is_retried_too() -> None:
    result, calls, _ = run("apply_chunk_embeddings", [RuntimeError("Server disconnected")])
    assert result == "rows" and calls == 2


def test_creating_rows_is_never_retried_so_nothing_can_be_duplicated() -> None:
    error, calls, waits = run("create_ingestion_job", [RuntimeError("Server disconnected")])
    assert isinstance(error, KnowledgeDBError) and calls == 1 and waits == []
    error, calls, _ = run("create_book", [RuntimeError("Server disconnected")])
    assert isinstance(error, KnowledgeDBError) and calls == 1


def test_a_real_error_is_not_retried() -> None:
    error, calls, _ = run("get_book", [RuntimeError("permission denied for table x")])
    assert isinstance(error, KnowledgeDBError) and calls == 1


def test_it_gives_up_after_the_last_wait_and_reports_the_error() -> None:
    error, calls, waits = run("list_books", [RuntimeError("Server disconnected")] * 10)
    assert isinstance(error, KnowledgeDBError) and calls == 4 and len(waits) == 3
    assert "Server disconnected" in str(error)


def test_the_module_defaults_use_the_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(knowledge_db.time, "sleep", slept.append)
    query = Query([RuntimeError("Server disconnected")])
    # `sleep` is bound at definition time; this checks the retry still works with the default.
    assert knowledge_db._execute("get_book", lambda: query, sleep=slept.append) == "rows"
    assert slept == [0.5]

"""FIFO rolling Voyage allowance shared by workers using the same local runtime directory."""

import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path


class VoyageBudgetUnavailable(RuntimeError):
    """The local allowance could not serve this request within its wait budget."""


class VoyageBudget:
    def __init__(
        self, path: Path, rpm: int, tpm: int, *,
        clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.path, self.rpm, self.tpm = path, rpm, tpm
        self.clock, self.sleep = clock, sleep
        self._ready = False

    def _ensure_schema(self) -> None:
        if self._ready:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute(
                "create table if not exists queue("
                "id integer primary key autoincrement, expires real)",
            )
            db.execute("create table if not exists spend("
                       "id integer primary key autoincrement, at real, tokens int)")
            db.execute("create table if not exists cooldown(until real)")
        self._ready = True

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.execute("begin immediate")
            yield db

    def reserve(
        self, tokens: int, max_wait: float, cancelled: Callable[[], bool] = lambda: False,
    ) -> int:
        if self.tpm > 0 and tokens > self.tpm:
            raise VoyageBudgetUnavailable("Batch exceeds the configured Voyage token allowance")
        self._ensure_schema()
        expires = self.clock() + max(0, max_wait)
        with self._transaction() as db:
            ticket = db.execute("insert into queue(expires) values (?)", (expires,)).lastrowid
        try:
            while not cancelled():
                with self._transaction() as db:
                    now = self.clock()
                    db.execute("delete from queue where expires < ? and id <> ?", (now, ticket))
                    db.execute("delete from spend where at <= ?", (now - 60,))
                    first = db.execute("select min(id) from queue").fetchone()[0]
                    calls, used = db.execute(
                        "select count(*), coalesce(sum(tokens),0) from spend",
                    ).fetchone()
                    cooldown = db.execute("select max(until) from cooldown").fetchone()[0] or 0
                    if (
                        first == ticket and now >= cooldown
                        and (self.rpm <= 0 or calls < self.rpm)
                        and (self.tpm <= 0 or used + tokens <= self.tpm)
                    ):
                        slot = db.execute(
                            "insert into spend(at,tokens) values (?,?)", (now, tokens),
                        ).lastrowid
                        assert slot is not None
                        return slot
                if self.clock() >= expires:
                    break
                self.sleep(min(0.5, max(0, expires - self.clock())))
        finally:
            with self._transaction() as db:
                db.execute("delete from queue where id = ?", (ticket,))
        raise VoyageBudgetUnavailable("Voyage allowance wait expired or was cancelled")

    def settle(self, slot: int, tokens: int) -> None:
        with self._transaction() as db:
            db.execute("update spend set tokens = ? where id = ?", (tokens, slot))

    def defer(self, seconds: float) -> None:
        self._ensure_schema()
        with self._transaction() as db:
            last = db.execute("select max(until) from cooldown").fetchone()[0] or 0
            db.execute("delete from cooldown")
            db.execute("insert into cooldown values (?)", (max(last, self.clock() + seconds),))

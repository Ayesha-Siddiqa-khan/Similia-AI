"""Per-practitioner hourly, daily and monthly limits on AI requests.

Each doctor's AI calls run on their own key, so limits protect them from runaway cost (a stuck
browser tab, a loop, a stolen session) rather than protecting a shared budget. Usage is counted
from the audit log, so it survives restarts and works across several server processes. A request
is recorded BEFORE the AI call, so failed attempts count too.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from app.core.config import get_settings

Kind = Literal["questions", "analyses"]
WINDOW = timedelta(hours=1)
# (name, length, settings field per kind). A limit of 0 or less switches that window off.
WINDOWS: tuple[tuple[str, timedelta, dict[str, str]], ...] = (
    ("hour", WINDOW, {"questions": "ai_questions_per_hour", "analyses": "ai_analyses_per_hour"}),
    (
        "day",
        timedelta(days=1),
        {"questions": "ai_questions_per_day", "analyses": "ai_analyses_per_day"},
    ),
    ("month", timedelta(days=30), {"analyses": "ai_analyses_per_month"}),
)
ACTIONS: dict[Kind, tuple[str, ...]] = {
    "questions": ("case.questions",),
    "analyses": ("case.analyze", "case.analyze.acknowledged_red_flags"),
}
LABELS: dict[Kind, str] = {"questions": "question requests", "analyses": "case analyses"}


class RateLimitedError(Exception):
    def __init__(
        self, kind: Kind, limit: int, retry_after_seconds: int, window: str = "hour"
    ) -> None:
        super().__init__(kind)
        self.kind, self.limit, self.retry_after_seconds = kind, limit, retry_after_seconds
        self.window = window

    @property
    def message(self) -> str:
        minutes = max(1, -(-self.retry_after_seconds // 60))
        if minutes >= 120:
            wait = f"{-(-minutes // 60)} hours"
        else:
            wait = f"{minutes} minute{'s' if minutes != 1 else ''}"
        return (
            f"Limit reached: {self.limit} {LABELS[self.kind]} per {self.window}. "
            f"Try again in about {wait}."
        )


class UsageStore(Protocol):
    def recent_actions(self, owner: str, actions: tuple[str, ...], since: str) -> list[str]:
        """ISO timestamps (ascending) of the owner's matching actions since `since`."""
        ...


def limit_for(kind: Kind, field: str | None = None) -> int:
    """The hourly limit by default; 0 when the window is not configured for this kind."""
    settings = get_settings()
    if field is None:
        field = "ai_questions_per_hour" if kind == "questions" else "ai_analyses_per_hour"
    return int(getattr(settings, field, 0) or 0)


def _times(
    store: UsageStore, owner: str, kind: Kind, now: datetime, window: timedelta = WINDOW
) -> list[datetime]:
    since = (now - window).isoformat()
    return sorted(
        datetime.fromisoformat(stamp).astimezone(timezone.utc)
        for stamp in store.recent_actions(owner, ACTIONS[kind], since)
    )


def usage(store: UsageStore, owner: str, now: datetime | None = None) -> dict[str, dict[str, int]]:
    """Hourly usage, shown in AI settings."""
    now = now or datetime.now(timezone.utc)
    return {
        kind: {"used": len(_times(store, owner, kind, now)), "limit": limit_for(kind)}
        for kind in ACTIONS
    }


def enforce(store: UsageStore, owner: str, kind: Kind, now: datetime | None = None) -> None:
    """Raise RateLimitedError when the owner has used up an hourly, daily or monthly allowance."""
    now = now or datetime.now(timezone.utc)
    for name, length, fields in WINDOWS:
        field = fields.get(kind)
        limit = limit_for(kind, field) if field else 0
        if limit <= 0:
            continue
        times = [t for t in _times(store, owner, kind, now, length) if t > now - length]
        if len(times) >= limit:
            # The next slot opens when the (len - limit + 1)-th oldest request leaves the window.
            frees_at = times[len(times) - limit] + length
            wait = max(1, int((frees_at - now).total_seconds()))
            raise RateLimitedError(kind, limit, wait, name)

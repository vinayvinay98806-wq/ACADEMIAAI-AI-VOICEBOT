"""
Deterministic Clock and Time Provider for W3 Context & Reasoning.

Provides a unified, reproducible time management strategy:
- Default live production mode: returns real UTC wall-clock time.
- Deterministic/frozen mode: allows freezing time to an explicit reference timestamp for tests and reproducible simulations.
- Scoped context manager: ensures isolated deterministic testing without side effects.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional, Union

# Standard deterministic reference timestamp for academic fixtures and synthetic testing
DEFAULT_FIXTURE_TIMESTAMP = "2026-10-28T12:00:00+00:00"


def parse_iso_timestamp(ts: Union[str, datetime]) -> datetime:
    """Parses a timestamp string or datetime into a UTC-aware datetime."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    clean_ts = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TimeProvider:
    """
    Manages system and simulated time for W3 components.
    """

    def __init__(self, initial_frozen_time: Optional[Union[str, datetime]] = None):
        self._frozen_time: Optional[datetime] = (
            parse_iso_timestamp(initial_frozen_time) if initial_frozen_time is not None else None
        )

    def now(self) -> datetime:
        """Returns current UTC time, or the frozen time if time is frozen."""
        if self._frozen_time is not None:
            return self._frozen_time
        return datetime.now(timezone.utc)

    def now_iso(self) -> str:
        """Returns ISO 8601 string of current time."""
        return self.now().isoformat()

    def freeze(self, frozen_time: Optional[Union[str, datetime]] = None) -> datetime:
        """Freezes the clock to a specific time (defaults to DEFAULT_FIXTURE_TIMESTAMP)."""
        target = frozen_time if frozen_time is not None else DEFAULT_FIXTURE_TIMESTAMP
        self._frozen_time = parse_iso_timestamp(target)
        return self._frozen_time

    def unfreeze(self) -> None:
        """Restores normal live wall-clock time."""
        self._frozen_time = None

    def is_frozen(self) -> bool:
        """Returns True if time is currently frozen."""
        return self._frozen_time is not None

    @contextmanager
    def freeze_context(
        self, frozen_time: Optional[Union[str, datetime]] = None
    ) -> Generator[datetime, None, None]:
        """Context manager that freezes time temporarily and unfreezes on exit."""
        prev = self._frozen_time
        frozen_dt = self.freeze(frozen_time)
        try:
            yield frozen_dt
        finally:
            self._frozen_time = prev


# Global default time provider instance
DEFAULT_TIME_PROVIDER = TimeProvider()


def get_current_time() -> datetime:
    """Returns current UTC datetime from default time provider."""
    return DEFAULT_TIME_PROVIDER.now()


def get_current_timestamp() -> str:
    """Returns current ISO 8601 UTC timestamp string from default time provider."""
    return DEFAULT_TIME_PROVIDER.now_iso()


def freeze_time(frozen_time: Optional[Union[str, datetime]] = None) -> datetime:
    """Freezes the global time provider to a fixed timestamp."""
    return DEFAULT_TIME_PROVIDER.freeze(frozen_time)


def unfreeze_time() -> None:
    """Unfreezes the global time provider, resuming live clock."""
    DEFAULT_TIME_PROVIDER.unfreeze()


def is_time_frozen() -> bool:
    """Returns True if global time provider is frozen."""
    return DEFAULT_TIME_PROVIDER.is_frozen()


@contextmanager
def frozen_time_context(
    frozen_time: Optional[Union[str, datetime]] = None
) -> Generator[datetime, None, None]:
    """Context manager to temporarily freeze global time."""
    with DEFAULT_TIME_PROVIDER.freeze_context(frozen_time) as dt:
        yield dt

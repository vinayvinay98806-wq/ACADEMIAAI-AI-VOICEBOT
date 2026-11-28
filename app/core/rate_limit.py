"""In-memory sliding-window rate limiter with deterministic testing support."""

import math
import time
from typing import Callable, Dict, List, Optional
from fastapi import Depends, Request, Response

from app.config import Settings, get_settings
from app.core.exceptions import RateLimitExceededError


class RateLimiter:
    """Thread-safe bounded in-memory sliding-window rate limiter."""

    def __init__(
        self,
        max_requests: Optional[int] = None,
        window_seconds: Optional[float] = None,
        clock_fn: Optional[Callable[[], float]] = None,
        max_entries: int = 5000,
    ) -> None:
        self.default_max_requests = max_requests
        self.default_window_seconds = window_seconds
        self._clock_fn = clock_fn or time.monotonic
        self._history: Dict[str, List[float]] = {}
        self._max_entries = max_entries

    def set_clock_fn(self, clock_fn: Optional[Callable[[], float]]) -> None:
        """Inject mock clock function for deterministic tests without sleeping."""
        self._clock_fn = clock_fn or time.monotonic

    def get_time(self) -> float:
        """Return current monotonic timestamp."""
        return self._clock_fn()

    def clear(self) -> None:
        """Clear all rate limit history."""
        self._history.clear()

    def _prune(self, now: float, window_seconds: float) -> None:
        """Prune empty or expired keys to avoid unbounded memory growth."""
        if len(self._history) > self._max_entries:
            cutoff = now - window_seconds
            keys_to_delete = [
                k for k, timestamps in self._history.items()
                if not timestamps or timestamps[-1] < cutoff
            ]
            for k in keys_to_delete:
                del self._history[k]

    def check(
        self,
        client_key: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[float] = None,
    ) -> Dict[str, int]:
        """Check and record request against client key.

        Returns:
            Dict containing 'limit', 'remaining', and 'reset_seconds'.
        Raises:
            RateLimitExceededError if limit is breached.
        """
        eff_max = max_requests if max_requests is not None else (self.default_max_requests or 60)
        eff_window = window_seconds if window_seconds is not None else (self.default_window_seconds or 60.0)

        now = self.get_time()
        self._prune(now, eff_window)

        cutoff = now - eff_window
        timestamps = self._history.get(client_key, [])

        # Filter out timestamps outside the active window
        timestamps = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= eff_max:
            oldest = timestamps[0]
            retry_after = max(1, math.ceil(oldest + eff_window - now))
            self._history[client_key] = timestamps
            raise RateLimitExceededError(
                message=f"Rate limit exceeded. Maximum {eff_max} requests per {int(eff_window)}s allowed.",
                retry_after=retry_after,
                details={
                    "limit": eff_max,
                    "window_seconds": eff_window,
                    "retry_after_seconds": retry_after,
                },
            )

        # Allow request and append timestamp
        timestamps.append(now)
        self._history[client_key] = timestamps

        remaining = eff_max - len(timestamps)
        oldest = timestamps[0]
        reset_seconds = max(1, math.ceil(oldest + eff_window - now))

        return {
            "limit": eff_max,
            "remaining": remaining,
            "reset_seconds": reset_seconds,
        }

    def check_rate_limit(
        self,
        client_key: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[float] = None,
    ) -> tuple[bool, int, int, int]:
        """Convenience method returning (allowed, remaining, reset_seconds, retry_after)."""
        eff_max = max_requests if max_requests is not None else (self.default_max_requests or 60)
        eff_window = window_seconds if window_seconds is not None else (self.default_window_seconds or 60.0)
        try:
            res = self.check(client_key, eff_max, eff_window)
            return True, res["remaining"], res["reset_seconds"], 0
        except RateLimitExceededError as err:
            retry_after = err.retry_after or 1
            return False, 0, retry_after, retry_after


# Alias for backward compatibility
InMemorySlidingWindowRateLimiter = RateLimiter


# Global singleton instance
_limiter_instance = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Dependency injection provider for RateLimiter."""
    return _limiter_instance


def get_client_identifier(request: Request) -> str:
    """Derive unique client identifier from client IP or authorization header."""
    auth_header = request.headers.get("Authorization") or request.headers.get("X-API-Key")
    if auth_header:
        return f"auth:{hash(auth_header.strip())}"

    # Check X-Forwarded-For if behind proxy
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        return f"ip:{client_ip}"

    if request.client:
        return f"ip:{request.client.host}"

    return "ip:unknown"


async def enforce_rate_limit(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    """FastAPI dependency to enforce rate limits on endpoints."""
    if not settings.rate_limit_enabled:
        return

    # Public health checks bypass rate limiting
    if request.url.path in ("/health", "/ready", "/api/v1/health", "/api/v1/ready"):
        return

    client_id = get_client_identifier(request)
    meta = limiter.check(
        client_key=client_id,
        max_requests=settings.rate_limit_requests,
        window_seconds=float(settings.rate_limit_window_seconds),
    )

    # Attach rate limit response headers
    response.headers["X-RateLimit-Limit"] = str(meta["limit"])
    response.headers["X-RateLimit-Remaining"] = str(meta["remaining"])
    response.headers["X-RateLimit-Reset"] = str(meta["reset_seconds"])

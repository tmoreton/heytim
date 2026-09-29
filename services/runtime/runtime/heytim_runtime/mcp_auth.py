"""Renew connection credentials before dispatching long-running MCP requests."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import httpx


@dataclass(frozen=True)
class AccessToken:
    value: str = field(repr=False)
    refresh_at: float

    @classmethod
    def expiring(cls, value: str, lifetime: float | None = None) -> AccessToken:
        if not isinstance(value, str) or not value:
            raise ValueError("Connection access token is unavailable")
        if lifetime is None:
            return cls(value, time.monotonic())
        if (
            isinstance(lifetime, bool)
            or not isinstance(lifetime, (int, float))
            or not math.isfinite(lifetime)
            or lifetime <= 0
        ):
            raise ValueError("Connection token lifetime is invalid")
        # Unknown expiry means no caching. Refresh known tokens early, including
        # unusually short-lived tokens, without extending their provider lifetime.
        margin = min(60, lifetime / 10)
        return cls(value, time.monotonic() + lifetime - margin)

    @classmethod
    def until(cls, value: str, expires_at: str | None) -> AccessToken:
        if expires_at is None:
            return cls.expiring(value)
        expiry = datetime.fromisoformat(expires_at)
        if expiry.tzinfo is None:
            raise ValueError("Connection token expiry must include a timezone")
        return cls.expiring(value, expiry.timestamp() - time.time())


class RefreshingBearerAuth(httpx.Auth):
    """Share one renewable credential across a connection's transport threads.

    Refresh before sending a request. Never replay an MCP request after a 401,
    timeout, or server failure: a tool may have performed an external action.
    """

    def __init__(self, load: Callable[[], AccessToken], endpoints: list[str]):
        self._load = load
        self._origins = {self._origin(httpx.URL(url)) for url in endpoints}
        self._lock = threading.Lock()
        # Preserve setup-time validation and the unavailable-connection handling.
        self._token: AccessToken | None = load()

    @staticmethod
    def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
        return url.scheme, url.host, url.port

    def _current_token(self) -> AccessToken:
        with self._lock:
            if self._token is None or time.monotonic() >= self._token.refresh_at:
                self._token = self._load()
            return self._token

    def _invalidate(self, rejected: AccessToken) -> None:
        with self._lock:
            if self._token is rejected:
                self._token = None

    async def async_auth_flow(self, request: httpx.Request):
        if self._origin(request.url) not in self._origins:
            raise ValueError("Connection credential cannot be sent to this origin")
        token = await asyncio.to_thread(self._current_token)
        request.headers["Authorization"] = f"Bearer {token.value}"
        response = yield request
        if response.status_code == 401:
            await asyncio.to_thread(self._invalidate, token)

"""In-process alert broadcaster.

A single background asyncio task polls the `recommendations` table for new CRITIQUE
rows (created since the last check) and fan-outs them to every connected WebSocket
client. Kept deliberately simple (polling, not LISTEN/NOTIFY) so it needs no schema
changes to layer 3 and is trivial to unit-test.

NOTE: state lives in-process, so with multiple gunicorn workers each worker holds its
own client set and its own high-water mark. That is fine for the dashboard (a client
connects to one worker). For a true multi-worker fan-out, swap `_poll_once`'s
delivery for Redis pub/sub — see README.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from ..config import get_settings
from ..database import get_sessionmaker
from ..schemas.common import WsAlert

logger = logging.getLogger("api.alerts")


def _as_naive_utc(dt: datetime) -> datetime:
    """Drop tzinfo (converting to UTC first) so the value can be compared to
    `recommendations.created_at`, which is a naive TIMESTAMP. asyncpg refuses
    to bind an aware datetime against a naive column.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class AlertBroadcaster:
    def __init__(self) -> None:
        self._clients: set = set()
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._last_seen: Optional[datetime] = None
        self._stop = asyncio.Event()

    async def register(self, ws) -> None:
        async with self._lock:
            self._clients.add(ws)
        logger.info("ws client connected (%d total)", len(self._clients))

    async def unregister(self, ws) -> None:
        async with self._lock:
            self._clients.discard(ws)
        logger.info("ws client disconnected (%d total)", len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            targets = list(self._clients)
        dead = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def _poll_once(self) -> None:
        sm = get_sessionmaker()
        async with sm() as session:
            if self._last_seen is None:
                # first pass: establish the high-water mark, don't replay history
                # NOW() is timestamptz and would promote the whole COALESCE to
                # an aware value; cast so the high-water mark stays naive like
                # the column it is compared against.
                row = (
                    await session.execute(
                        text(
                            "SELECT COALESCE(MAX(created_at), NOW()::timestamp) "
                            "FROM recommendations"
                        )
                    )
                ).scalar()
                self._last_seen = _as_naive_utc(row or datetime.now(timezone.utc))
                return
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, severity, title, description, created_at
                        FROM recommendations
                        WHERE severity = 'CRITIQUE' AND created_at > :since
                        ORDER BY created_at ASC
                        """
                    ),
                    {"since": _as_naive_utc(self._last_seen)},
                )
            ).all()
        for r in rows:
            self._last_seen = r.created_at
            alert = WsAlert(
                severity=r.severity,
                title=r.title,
                description=r.description,
                recommendation_id=r.id,
                timestamp=(r.created_at or datetime.now(timezone.utc)).isoformat(),
            )
            await self.broadcast(alert.model_dump())
            logger.info("broadcast alert %s to %d clients", r.id, self.client_count)

    async def _run(self) -> None:
        interval = get_settings().alert_poll_seconds
        while not self._stop.is_set():
            try:
                await self._poll_once()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("alert poll failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run())
            logger.info("alert broadcaster started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        logger.info("alert broadcaster stopped")


broadcaster = AlertBroadcaster()

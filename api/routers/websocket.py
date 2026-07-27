"""WS /ws/alerts — pushes real-time CRITIQUE alerts to authenticated clients.

Browsers can't set Authorization headers on a WebSocket, so the JWT access token is
passed as the `token` query param: ws://host/ws/alerts?token=<access_token>.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from ..alerts.broadcaster import broadcaster
from ..security import decode_token

logger = logging.getLogger("api.ws")

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket, token: str = Query(...)) -> None:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise JWTError("not an access token")
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    await broadcaster.register(websocket)
    try:
        # keep the connection open; ignore any inbound frames (client is read-only)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.debug("ws error: %s", exc)
    finally:
        await broadcaster.unregister(websocket)

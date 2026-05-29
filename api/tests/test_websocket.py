"""Tests for WebSocket real-time task updates."""

import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from api.routes.tasks import ConnectionManager, manager


class TestConnectionManager:
    """Unit tests for ConnectionManager."""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.receive_text = AsyncMock()

        client_id = await cm.connect(ws)
        assert client_id.startswith("client_")
        assert cm.connected_count == 1

        cm.disconnect(ws)
        assert cm.connected_count == 0

    @pytest.mark.asyncio
    async def test_subscribe_and_broadcast(self):
        cm = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2.send_text = AsyncMock()
        ws1.receive_text = AsyncMock()
        ws2.receive_text = AsyncMock()

        await cm.connect(ws1)
        await cm.connect(ws2)
        await cm.subscribe(ws1, 42)
        await cm.subscribe(ws2, 42)

        await cm.broadcast_task_update(42, {"status": "completed"})

        # Both should have received the message
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

        # Verify message format
        msg = json.loads(ws1.send_text.call_args[0][0])
        assert msg["type"] == "task_update"
        assert msg["task_id"] == 42
        assert msg["data"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_text = AsyncMock()

        await cm.connect(ws)
        await cm.subscribe(ws, 42)
        await cm.unsubscribe(ws, 42)

        await cm.broadcast_task_update(42, {"status": "completed"})
        # After unsubscribe, no message should be sent
        assert ws.send_text.call_count == 0

    @pytest.mark.asyncio
    async def test_filtered_broadcast(self):
        """Only subscribers of the specific task receive updates."""
        cm = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2.send_text = AsyncMock()

        await cm.connect(ws1)
        await cm.connect(ws2)
        await cm.subscribe(ws1, 1)
        await cm.subscribe(ws2, 2)

        await cm.broadcast_task_update(1, {"status": "done"})

        ws1.send_text.assert_called_once()
        ws2.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_dead_connections(self):
        """Dead connections should be removed during broadcast."""
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_text = AsyncMock(side_effect=Exception("Connection closed"))

        await cm.connect(ws)
        await cm.subscribe(ws, 42)

        await cm.broadcast_task_update(42, {"status": "done"})

        # After cleanup, connection should be removed
        assert cm.connected_count == 0

    @pytest.mark.asyncio
    async def test_heartbeat(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        ws.send_text = AsyncMock()

        await cm.send_heartbeat(ws)

        ws.send_text.assert_called_once()
        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["type"] == "heartbeat"
        assert "timestamp" in msg


# ———— Integration tests ————


@pytest.fixture
def app_with_ws():
    """Create a FastAPI app with the WebSocket endpoint."""
    from fastapi import FastAPI
    from api.routes.tasks import router

    app = FastAPI()
    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(app_with_ws):
    from fastapi.testclient import TestClient
    return TestClient(app_with_ws)


def test_websocket_connect(client):
    """WebSocket should accept connections."""
    with client.websocket_connect("/tasks/ws") as ws:
        # Connection should succeed
        assert ws is not None


def test_websocket_subscribe(client):
    """Should be able to subscribe to a task."""
    with client.websocket_connect("/tasks/ws") as ws:
        ws.send_json({"type": "subscribe", "task_id": 42})
        response = ws.receive_json()
        assert response["type"] == "subscribed"
        assert response["task_id"] == 42


def test_websocket_unsubscribe(client):
    """Should be able to unsubscribe from a task."""
    with client.websocket_connect("/tasks/ws") as ws:
        ws.send_json({"type": "subscribe", "task_id": 42})
        ws.receive_json()  # subscribed response

        ws.send_json({"type": "unsubscribe", "task_id": 42})
        response = ws.receive_json()
        assert response["type"] == "unsubscribed"
        assert response["task_id"] == 42


def test_websocket_ping_pong(client):
    """Ping should get pong response."""
    with client.websocket_connect("/tasks/ws") as ws:
        ws.send_json({"type": "ping"})
        response = ws.receive_json()
        assert response["type"] == "pong"


def test_websocket_invalid_json(client):
    """Invalid JSON should get error response."""
    with client.websocket_connect("/tasks/ws") as ws:
        ws.send_text("not json")
        response = ws.receive_json()
        assert response["type"] == "error"


def test_websocket_multiple_clients(client):
    """Multiple clients should connect independently."""
    with client.websocket_connect("/tasks/ws") as ws1, \
         client.websocket_connect("/tasks/ws") as ws2:
        ws1.send_json({"type": "subscribe", "task_id": 1})
        ws2.send_json({"type": "subscribe", "task_id": 2})

        r1 = ws1.receive_json()
        r2 = ws2.receive_json()

        assert r1["type"] == "subscribed"
        assert r1["task_id"] == 1
        assert r2["type"] == "subscribed"
        assert r2["task_id"] == 2


def test_websocket_disconnect_cleanup(client):
    """Disconnected clients should be cleaned up."""
    with client.websocket_connect("/tasks/ws") as ws:
        ws.send_json({"type": "subscribe", "task_id": 42})
        ws.receive_json()  # subscribed

    # Connection exited — manager should have cleaned up
    assert manager.connected_count == 0
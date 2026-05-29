"""Tests for the request ID middleware."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from api.main import app

REQUEST_ID_HEADER = "X-Request-ID"


@pytest.mark.asyncio
async def test_request_id_generated_when_not_provided():
    """When no X-Request-ID header is sent, the middleware generates a UUID."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert REQUEST_ID_HEADER in response.headers

    request_id = response.headers[REQUEST_ID_HEADER]
    # Verify it's a valid UUID
    parsed = uuid.UUID(request_id)
    assert str(parsed) == request_id


@pytest.mark.asyncio
async def test_request_id_accepted_from_client():
    """When a client sends X-Request-ID, the middleware uses that value."""
    client_id = "my-trace-id-42"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health", headers={REQUEST_ID_HEADER: client_id}
        )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == client_id


@pytest.mark.asyncio
async def test_request_id_is_unique_per_request():
    """Each request without a client ID gets a unique request ID."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.get("/health")
        resp2 = await client.get("/health")

    id1 = resp1.headers[REQUEST_ID_HEADER]
    id2 = resp2.headers[REQUEST_ID_HEADER]
    assert id1 != id2


@pytest.mark.asyncio
async def test_request_id_on_all_endpoints():
    """The X-Request-ID header is present on all endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        endpoints = [
            ("GET", "/health"),
            ("GET", "/agents"),
            ("GET", "/tasks"),
            ("GET", "/leaderboard"),
        ]
        for method, path in endpoints:
            response = await client.request(method, path)
            assert REQUEST_ID_HEADER in response.headers, (
                f"Missing {REQUEST_ID_HEADER} on {method} {path}"
            )
            # Verify UUID format
            uuid.UUID(response.headers[REQUEST_ID_HEADER])


@pytest.mark.asyncio
async def test_client_request_id_is_valid_uuid():
    """Client-provided request IDs that are valid UUIDs are accepted."""
    valid_uuid = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health", headers={REQUEST_ID_HEADER: valid_uuid}
        )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == valid_uuid


@pytest.mark.asyncio
async def test_request_id_survives_error_responses():
    """Even 4xx/5xx responses include the X-Request-ID header."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/agents/nonexistent")

    assert response.status_code == 404
    assert REQUEST_ID_HEADER in response.headers
    uuid.UUID(response.headers[REQUEST_ID_HEADER])

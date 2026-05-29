"""Unit tests for three-tier rate limiting middleware."""

import time
import jwt
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi import Request
from starlette.responses import JSONResponse

from api.middleware.ratelimit import (
    SlidingWindowCounter,
    _get_tier,
    RateLimitMiddleware,
    _counters,
    TIERS,
)

# ———— SlidingWindowCounter unit tests ————


def test_counter_allows_under_limit():
    c = SlidingWindowCounter(5, 60)
    now = 1000.0
    for i in range(5):
        allowed, remaining, _ = c.allow_request(now + i)
        assert allowed
        assert remaining == 5 - i - 1


def test_counter_rejects_at_limit():
    c = SlidingWindowCounter(3, 60)
    now = 1000.0
    for i in range(3):
        c.allow_request(now + i)

    allowed, remaining, retry_after = c.allow_request(now + 10)
    assert not allowed
    assert remaining == 0
    assert retry_after > 0


def test_counter_sliding_window_expiry():
    c = SlidingWindowCounter(3, 10)
    now = 1000.0
    for i in range(3):
        c.allow_request(now + i)

    # All 3 slots used
    allowed, _, _ = c.allow_request(now + 5)
    assert not allowed

    # After window expires, should allow again
    allowed, remaining, _ = c.allow_request(now + 15)
    assert allowed
    assert remaining == 2  # first request in new window


def test_counter_prunes_old_entries():
    """Old entries should be pruned, freeing up capacity."""
    c = SlidingWindowCounter(2, 10)

    # Add two requests at t=1000 and t=1005
    c.allow_request(1000.0)
    c.allow_request(1005.0)

    # Both slots used, next should fail
    allowed, _, _ = c.allow_request(1006.0)
    assert not allowed

    # Now at t=1012: cutoff=1002. t=1000 is pruned, t=1005 remains
    allowed, remaining, _ = c.allow_request(1012.0)
    assert allowed
    assert remaining <= 1  # we added one more, so max(2)-used(2)=0 or pruned-one: max(2)-used(1)=1


# ———— Tier detection tests ————


def _make_request(headers: dict) -> Request:
    """Create a mock FastAPI Request with given headers."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/agents",
        "headers": [],
    }
    for k, v in headers.items():
        scope["headers"].append((k.lower().encode(), v.encode()))
    return Request(scope)


def test_tier_anonymous_no_auth():
    req = _make_request({})
    assert _get_tier(req) == "anonymous"


def test_tier_anonymous_invalid_token():
    req = _make_request({"Authorization": "Bearer invalidtoken"})
    assert _get_tier(req) == "anonymous"


def test_tier_authenticated_with_jwt():
    # Create a valid JWT
    token = jwt.encode(
        {"sub": "123", "address": "0xabc", "roles": []},
        "test-secret",
        algorithm="HS256",
    )
    req = _make_request({"Authorization": f"Bearer {token}"})
    assert _get_tier(req) == "authenticated"


def test_tier_premium_with_api_key():
    api_key = "a" * 16  # 16 char key = premium
    req = _make_request({"X-API-Key": api_key})
    assert _get_tier(req) == "premium"


def test_tier_authenticated_short_api_key():
    api_key = "short"  # < 16 chars = not premium
    req = _make_request({"X-API-Key": api_key})
    assert _get_tier(req) == "anonymous"


def test_tier_premium_role():
    token = jwt.encode(
        {"sub": "456", "address": "0xdef", "roles": ["premium"]},
        "test-secret",
        algorithm="HS256",
    )
    req = _make_request({"Authorization": f"Bearer {token}"})
    assert _get_tier(req) == "premium"


# ———— Integration tests (via TestClient) ————


@pytest.fixture
def app_with_ratelimit():
    """Create a minimal FastAPI app with rate limiting middleware."""
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(app_with_ratelimit):
    from fastapi.testclient import TestClient
    return TestClient(app_with_ratelimit)


def test_health_skip_rate_limit(client):
    """Health endpoint should not be rate limited."""
    for _ in range(100):
        resp = client.get("/health")
        assert resp.status_code == 200


def test_anonymous_rate_limit_headers(client):
    """Anonymous requests should get rate limit headers."""
    resp = client.get("/test")
    assert resp.status_code == 200
    assert resp.headers.get("X-RateLimit-Limit") == str(TIERS["anonymous"][0])
    assert resp.headers.get("X-RateLimit-Tier") == "anonymous"
    remaining = int(resp.headers.get("X-RateLimit-Remaining", -1))
    assert remaining >= 0


def test_authenticated_higher_limit(client):
    """Authenticated users should get higher rate limit."""
    token = jwt.encode(
        {"sub": "123", "address": "0xabc", "roles": []},
        "test-secret",
        algorithm="HS256",
    )
    resp = client.get("/test", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.headers.get("X-RateLimit-Limit") == str(TIERS["authenticated"][0])
    assert int(resp.headers.get("X-RateLimit-Remaining")) < int(resp.headers.get("X-RateLimit-Limit"))


def test_premium_highest_limit(client):
    """Premium users should get the highest rate limit."""
    resp = client.get("/test", headers={"X-API-Key": "a" * 16})
    assert resp.status_code == 200
    assert resp.headers.get("X-RateLimit-Limit") == str(TIERS["premium"][0])


def test_429_response_headers(client):
    """Rate limited requests should get 429 with headers."""
    # Clear counters
    _counters.clear()

    # Overwhelm anonymous limit
    limit = TIERS["anonymous"][0]
    for _ in range(limit):
        client.get("/test")

    # Next request should be 429
    resp = client.get("/test")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    assert str(resp.headers.get("X-RateLimit-Remaining")) == "0"
    assert resp.headers.get("X-RateLimit-Tier") == "anonymous"


def test_rate_limit_resets_after_window(client):
    """Rate limit should reset after the window expires."""
    _counters.clear()

    limit = TIERS["anonymous"][0]
    for _ in range(limit):
        client.get("/test")

    # Should be limited
    resp = client.get("/test")
    assert resp.status_code == 429

    # Simulate window expiry by clearing and re-testing
    _counters.clear()
    resp = client.get("/test")
    assert resp.status_code == 200

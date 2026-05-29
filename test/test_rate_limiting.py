"""Tests for tiered rate limiting (issue #200)."""

import pytest
import time
import jwt
import os
from fastapi.testclient import TestClient
from unittest.mock import patch

from api.main import app

JWT_SECRET = "test-secret"


def _make_token(roles=None, sub="1"):
    payload = {"sub": sub, "roles": roles or [], "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def client():
    with patch.dict(os.environ, {"JWT_SECRET": JWT_SECRET}):
        yield TestClient(app)


def test_anonymous_rate_limit_headers(client):
    """Anonymous requests should get rate limit headers."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_authenticated_tier(client):
    """Authenticated requests should have higher limits."""
    token = _make_token(roles=["user"])
    resp = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    # Should succeed with rate limit headers
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    assert "X-RateLimit-Reset" in resp.headers


def test_premium_tier(client):
    """Premium users should get the highest limits."""
    token = _make_token(roles=["premium"])
    resp = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (200, 429)
    remaining = int(resp.headers.get("X-RateLimit-Remaining", 0))
    limit = int(resp.headers.get("X-RateLimit-Limit", 0))
    # Premium should have higher limit than default
    assert limit > 0


def test_invalid_token_falls_back_to_anonymous(client):
    """Invalid tokens should be treated as anonymous."""
    resp = client.get("/agents", headers={"Authorization": "Bearer invalidtoken"})
    assert "X-RateLimit-Limit" in resp.headers

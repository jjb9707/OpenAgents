"""Tests for agent endpoints including URL validation (issue #139).

Contributor (Issue #139):
  - jjb9707 (https://github.com/jjb9707)
"""

import pytest
import jwt
import os
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime

from api.main import app

JWT_SECRET = "test-secret"


def _make_token(roles=None, sub="1", address="0xabc"):
    payload = {"sub": sub, "address": address, "roles": roles or [], "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def client():
    with patch.dict(os.environ, {"JWT_SECRET": JWT_SECRET}):
        from api.models.database import init_db, engine, Base
        Base.metadata.create_all(bind=engine)
        yield TestClient(app)


@pytest.fixture
def auth_header():
    return {"Authorization": f"Bearer {_make_token()}"}


# ---------------------------------------------------------------------------
# register_agent endpoint tests
# ---------------------------------------------------------------------------


class TestRegisterAgentURLValidation:
    """Tests for the /agents/register endpoint URL validation."""

    def test_missing_endpoint_url(self, client, auth_header):
        """Should reject a request without endpoint_url."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        errors = resp.json().get("detail", [])
        assert any("endpoint_url" in str(e) for e in errors)

    def test_invalid_scheme_ftp(self, client, auth_header):
        """Should reject non-http/https schemes."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "ftp://example.com/agent"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "http or https" in resp.text

    def test_invalid_scheme_file(self, client, auth_header):
        """Should reject file:// scheme."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "file:///etc/passwd"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "http or https" in resp.text

    def test_invalid_scheme_ws(self, client, auth_header):
        """Should reject ws:// scheme."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "ws://example.com/agent"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "http or https" in resp.text

    def test_no_host(self, client, auth_header):
        """Should reject URLs without a host."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "http:///path"},
            headers=auth_header,
        )
        assert resp.status_code == 422

    def test_empty_url(self, client, auth_header):
        """Should reject empty endpoint_url."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": ""},
            headers=auth_header,
        )
        assert resp.status_code == 422


class TestRegisterAgentSSRFProtection:
    """SSRF protection: reject private/internal IPs."""

    def test_loopback_ip(self, client, auth_header):
        """Should reject 127.0.0.1."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "http://127.0.0.1:8545"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "private" in resp.text.lower() or "internal" in resp.text.lower() or "127.0.0.1" in resp.text

    def test_loopback_hostname(self, client, auth_header):
        """Should reject localhost."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "http://localhost:8545"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "private" in resp.text.lower() or "internal" in resp.text.lower()

    def test_private_10_range(self, client, auth_header):
        """Should reject 10.x.x.x addresses."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "http://10.0.0.1:8080"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "private" in resp.text.lower() or "internal" in resp.text.lower()

    def test_private_172_range(self, client, auth_header):
        """Should reject 172.16-31.x.x addresses."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "http://172.16.0.1:8080"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "private" in resp.text.lower() or "internal" in resp.text.lower()

    def test_private_192_168(self, client, auth_header):
        """Should reject 192.168.x.x addresses."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "http://192.168.1.1:8080"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "private" in resp.text.lower() or "internal" in resp.text.lower()

    def test_private_172_31(self, client, auth_header):
        """Should reject 172.31.x.x (upper bound of private 172 block)."""
        resp = client.post(
            "/agents/register",
            json={"name": "test-agent", "endpoint_url": "http://172.31.255.255:8080"},
            headers=auth_header,
        )
        assert resp.status_code == 422
        assert "private" in resp.text.lower() or "internal" in resp.text.lower()

    def test_public_ip_allowed(self, client, auth_header):
        """Should allow public IPs (8.8.8.8)."""
        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.head.return_value = MagicMock(status_code=200)
            mock_client.return_value.__enter__.return_value = mock_instance

            resp = client.post(
                "/agents/register",
                json={"name": "test-agent", "endpoint_url": "http://8.8.8.8:8080"},
                headers=auth_header,
            )
            # If validation passes, it should proceed (200=success or 500=db error; 422=validation fail)
            assert resp.status_code != 422


class TestRegisterAgentReachability:
    """Reachability check via HEAD request."""

    def test_reachable_endpoint(self, client, auth_header):
        """Should accept a reachable endpoint."""
        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.head.return_value = MagicMock(status_code=200)
            mock_client.return_value.__enter__.return_value = mock_instance

            resp = client.post(
                "/agents/register",
                json={
                    "name": "reachable-agent",
                    "endpoint_url": "https://api.openai.com/v1",
                },
                headers=auth_header,
            )
            # 422 would indicate validation failure; 200/500 means it passed reachability
            assert resp.status_code != 422

    def test_unreachable_endpoint(self, client, auth_header):
        """Should reject an unreachable endpoint (connection refused)."""
        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            from httpx import ConnectError
            mock_instance.head.side_effect = ConnectError("Connection refused")
            mock_client.return_value.__enter__.return_value = mock_instance

            resp = client.post(
                "/agents/register",
                json={
                    "name": "unreachable-agent",
                    "endpoint_url": "http://192.0.2.1:9999",
                },
                headers=auth_header,
            )
            assert resp.status_code == 422
            assert "connect" in resp.text.lower() or "unreachable" in resp.text.lower()

    def test_timeout_endpoint(self, client, auth_header):
        """Should reject endpoints that time out."""
        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            from httpx import TimeoutException
            mock_instance.head.side_effect = TimeoutException("Timed out")
            mock_client.return_value.__enter__.return_value = mock_instance

            resp = client.post(
                "/agents/register",
                json={
                    "name": "timeout-agent",
                    "endpoint_url": "https://example.com:81",
                },
                headers=auth_header,
            )
            assert resp.status_code == 422
            assert "time" in resp.text.lower()


class TestRegisterAgentAuth:
    """Authentication checks for register_agent."""

    def test_unauthenticated_request(self, client):
        """Should reject requests without auth token."""
        resp = client.post(
            "/agents/register",
            json={
                "name": "no-auth-agent",
                "endpoint_url": "https://example.com/agent",
            },
        )
        # FastAPI's HTTPBearer returns 401 when no token is provided
        assert resp.status_code == 401

    def test_invalid_token(self, client):
        """Should reject requests with invalid token."""
        resp = client.post(
            "/agents/register",
            json={
                "name": "bad-token-agent",
                "endpoint_url": "https://example.com/agent",
            },
            headers={"Authorization": "Bearer invalidtoken"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Unit tests for the SSRF helper (direct function test)
# ---------------------------------------------------------------------------


class TestIsPrivateIp:
    """Unit tests for the _is_private_ip helper function."""

    def test_private_ips(self):
        from api.routes.agents import _is_private_ip

        assert _is_private_ip("127.0.0.1") is True
        assert _is_private_ip("127.255.255.255") is True
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("10.255.255.255") is True
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("172.31.255.255") is True
        assert _is_private_ip("192.168.0.1") is True
        assert _is_private_ip("192.168.255.255") is True
        assert _is_private_ip("169.254.1.1") is True
        assert _is_private_ip("0.0.0.0") is True

    def test_non_private_ips(self):
        from api.routes.agents import _is_private_ip

        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False
        assert _is_private_ip("172.15.255.255") is False
        assert _is_private_ip("172.32.0.1") is False
        assert _is_private_ip("192.167.255.255") is False
        assert _is_private_ip("192.169.0.1") is False
        assert _is_private_ip("100.63.255.255") is False
        assert _is_private_ip("100.128.0.1") is False
        assert _is_private_ip("198.17.255.255") is False
        assert _is_private_ip("198.20.0.1") is False

    def test_non_ip_strings(self):
        from api.routes.agents import _is_private_ip

        assert _is_private_ip("") is False
        assert _is_private_ip("not-an-ip") is False
        assert _is_private_ip(None) is False
        assert _is_private_ip("256.0.0.1") is False
        assert _is_private_ip("10.0.0") is False

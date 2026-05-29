"""Tests for CORS middleware configuration."""

import os
from unittest import mock

from httpx import ASGITransport, Client

from api.main import app


def _client():
    """Return a test client bound to the FastAPI app."""
    return Client(transport=ASGITransport(app=app), base_url="http://test")


class TestCORSMiddleware:
    """Verify CORS headers are set correctly."""

    def test_cors_headers_on_get(self):
        """A GET response should include Access-Control-Allow-Origin."""
        with _client() as client:
            resp = client.get("/health", headers={"Origin": "http://example.com"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"

    def test_cors_credentials_header(self):
        """Access-Control-Allow-Credentials must be true."""
        with _client() as client:
            resp = client.get("/health", headers={"Origin": "http://example.com"})
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_cors_preflight_options(self):
        """OPTIONS preflight should return allowed methods."""
        with _client() as client:
            resp = client.options(
                "/health",
                headers={
                    "Origin": "http://example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.status_code == 200
        methods = resp.headers.get("access-control-allow-methods", "")
        for m in ("GET", "POST", "PUT", "DELETE", "OPTIONS"):
            assert m in methods, f"Expected {m} in allowed methods"

    def test_cors_allow_headers_wildcard(self):
        """Access-Control-Allow-Headers should be *."""
        with _client() as client:
            resp = client.options(
                "/health",
                headers={
                    "Origin": "http://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
        assert resp.headers.get("access-control-allow-headers") == "*"

    def test_cors_custom_origins(self):
        """When CORS_ORIGINS is set, it should be respected."""
        test_origins = "https://app.example.com,https://admin.example.com"
        with mock.patch.dict(os.environ, {"CORS_ORIGINS": test_origins}):
            # Re-import to reload with env override
            import importlib
            import api.main as api_main
            importlib.reload(api_main)
            from api.main import app as reloaded_app

        with Client(
            transport=ASGITransport(app=reloaded_app), base_url="http://test"
        ) as client:
            resp = client.get(
                "/health", headers={"Origin": "https://app.example.com"}
            )
        assert resp.status_code == 200
        allow_origin = resp.headers.get("access-control-allow-origin")
        assert allow_origin == "https://app.example.com", (
            f"Expected https://app.example.com, got {allow_origin}"
        )

        # Ensure origin not in list is rejected
        with Client(
            transport=ASGITransport(app=reloaded_app), base_url="http://test"
        ) as client:
            resp = client.get("/health", headers={"Origin": "https://evil.com"})
        assert resp.headers.get("access-control-allow-origin") is None or (
            resp.headers["access-control-allow-origin"] != "https://evil.com"
        ), "Origin not in allow list should not be echoed back"

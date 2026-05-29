"""Tests for CORS middleware configuration."""

import os
from unittest import mock

from fastapi.testclient import TestClient

from api.main import app


class TestCORSMiddleware:
    """Verify CORS headers are set correctly."""

    client = TestClient(app)

    def test_cors_headers_on_get(self):
        """A GET response should include Access-Control-Allow-Origin.
        Because allow_credentials=True, Starlette echoes the request origin
        instead of returning '*' (required by the CORS spec)."""
        resp = self.client.get("/health", headers={"Origin": "http://example.com"})
        assert resp.status_code == 200
        # When credentials=True and origins=["*"], Starlette echoes the origin
        assert resp.headers.get("access-control-allow-origin") == "http://example.com"

    def test_cors_credentials_header(self):
        """Access-Control-Allow-Credentials must be true."""
        resp = self.client.get("/health", headers={"Origin": "http://example.com"})
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_cors_preflight_options(self):
        """OPTIONS preflight should return allowed methods."""
        resp = self.client.options(
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

    def test_cors_preflight_returns_origin(self):
        """Preflight response echoes the request origin when credentials enabled."""
        resp = self.client.options(
            "/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200
        assert (
            resp.headers.get("access-control-allow-origin") == "http://example.com"
        )

    def test_cors_custom_origins(self):
        """When CORS_ORIGINS is set, only those origins are allowed."""
        test_origins = "https://app.example.com,https://admin.example.com"
        with mock.patch.dict(os.environ, {"CORS_ORIGINS": test_origins}):
            import importlib
            import api.main as api_main
            importlib.reload(api_main)
            from api.main import app as reloaded_app

        client = TestClient(reloaded_app)

        # Origin in allow list should be echoed back
        resp = client.get(
            "/health", headers={"Origin": "https://app.example.com"}
        )
        assert resp.status_code == 200
        assert (
            resp.headers.get("access-control-allow-origin")
            == "https://app.example.com"
        )

        # Origin not in list should not get CORS header
        resp = client.get("/health", headers={"Origin": "https://evil.com"})
        allow_origin = resp.headers.get("access-control-allow-origin")
        assert allow_origin is None or allow_origin != "https://evil.com", (
            "Origin not in allow list should not be echoed back"
        )

    def test_cors_disallowed_origin_rejected(self):
        """A request from a disallowed origin does not get CORS headers."""
        test_origins = "https://allowed.example.com"
        with mock.patch.dict(os.environ, {"CORS_ORIGINS": test_origins}):
            import importlib
            import api.main as api_main
            importlib.reload(api_main)
            from api.main import app as reloaded_app

        client = TestClient(reloaded_app)
        resp = client.get("/health", headers={"Origin": "https://evil.com"})
        assert resp.headers.get("access-control-allow-origin") is None

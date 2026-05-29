"""Tests for structured error responses (issue #202)."""

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_not_found_returns_structured_error():
    """404 errors should return structured error with code."""
    resp = client.get("/agents/9999")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "NOT_FOUND"
    assert "message" in body
    assert "request_id" in body


def test_error_has_request_id():
    """All error responses should include request_id."""
    resp = client.get("/agents/9999")
    body = resp.json()
    assert len(body["request_id"]) == 8  # truncated UUID


def test_known_error_codes():
    """Known HTTP status codes should map to correct error codes."""
    from api.main import ERROR_CODES
    assert ERROR_CODES[400] == "VALIDATION_ERROR"
    assert ERROR_CODES[401] == "AUTH_FAILED"
    assert ERROR_CODES[403] == "FORBIDDEN"
    assert ERROR_CODES[404] == "NOT_FOUND"
    assert ERROR_CODES[429] == "RATE_LIMITED"
    assert ERROR_CODES[500] == "INTERNAL_ERROR"


def test_success_responses_unchanged():
    """Successful responses should not be affected."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

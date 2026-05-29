"""Tests for OpenAPI schema security documentation (issue #171)."""

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_openapi_schema_exists():
    """OpenAPI schema should be accessible."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "components" in schema


def test_security_schemes_present():
    """Both auth security schemes should be documented."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "BearerAuth" in schemes
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"
    assert "ApiKeyAuth" in schemes
    assert schemes["ApiKeyAuth"]["type"] == "apiKey"


def test_error_schemas_present():
    """Error response schemas should be documented."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    schemas = schema.get("components", {}).get("schemas", {})
    assert "HTTPError" in schemas
    assert "ValidationError" in schemas


def test_default_security_applied():
    """Default security should be applied to all endpoints."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    assert "security" in schema
    assert len(schema["security"]) > 0

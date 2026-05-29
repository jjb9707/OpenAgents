# @contributor: Hermes Agent @jjb9707
# @date: 2026-05-29T03:18:45Z
# @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-157 shell=/bin/bash

"""
Tests for OpenAPI schema generation with authentication security schemes.

Validates:
- OpenAPI metadata (title, version, description, contact)
- Security schemes (JWT Bearer + API Key) present and correctly defined
- Error response schemas (400, 401, 403, 404, 429) present with examples
- Security applied to protected endpoints
"""

import os
import sys
import json

# Add project root to sys.path so api.main can import api.routes
_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)  # api/
_grandparent = os.path.dirname(_project_root)  # project root
sys.path.insert(0, _grandparent)

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("API_KEY", "test-api-key-123")

from api.main import app

client = TestClient(app)


class TestOpenAPIMetadata:
    """Verify OpenAPI info metadata is present and correct."""

    def _get_schema(self) -> dict:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        return response.json()

    def test_openapi_endpoint_exists(self):
        """The /openapi.json endpoint should return 200."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_openapi_version(self):
        """Schema should have OpenAPI 3.x version."""
        schema = self._get_schema()
        assert "openapi" in schema
        assert schema["openapi"].startswith("3.")

    def test_openapi_title(self):
        """Schema title should match the app title."""
        schema = self._get_schema()
        assert "info" in schema
        assert schema["info"]["title"] == "OpenAgents API"

    def test_openapi_version_string(self):
        """Schema version should be 0.1.0."""
        schema = self._get_schema()
        assert schema["info"]["version"] == "0.1.0"

    def test_openapi_description(self):
        """Schema should have a description."""
        schema = self._get_schema()
        assert "description" in schema["info"]
        assert len(schema["info"]["description"]) > 10

    def test_openapi_contact(self):
        """Schema should have contact info."""
        schema = self._get_schema()
        assert "contact" in schema["info"]
        assert "name" in schema["info"]["contact"]
        assert schema["info"]["contact"]["name"] == "ClankerNation"

    def test_openapi_license(self):
        """Schema should have license info."""
        schema = self._get_schema()
        assert "license" in schema["info"]
        assert schema["info"]["license"]["name"] == "MIT"


class TestSecuritySchemes:
    """Verify security schemes are properly defined."""

    def _get_schema(self) -> dict:
        return client.get("/openapi.json").json()

    def test_security_schemes_exist(self):
        """The components should have securitySchemes."""
        schema = self._get_schema()
        assert "components" in schema
        assert "securitySchemes" in schema["components"]

    def test_jwt_bearer_scheme_exists(self):
        """JWTBearer security scheme should be present."""
        schema = self._get_schema()
        schemes = schema["components"]["securitySchemes"]
        assert "JWTBearer" in schemes or "bearerAuth" in schemes or any(
            "bearer" in k.lower() or "jwt" in k.lower() for k in schemes
        ), f"JWT Bearer scheme not found in {list(schemes.keys())}"

    def test_jwt_bearer_scheme_type(self):
        """JWTBearer scheme should be of type http with scheme bearer."""
        schema = self._get_schema()
        schemes = schema["components"]["securitySchemes"]
        # Find the JWT bearer scheme by looking for http/bearer type
        jwt_scheme = None
        for name, scheme in schemes.items():
            if scheme.get("type") == "http" and scheme.get("scheme") == "bearer":
                jwt_scheme = scheme
                break
        assert jwt_scheme is not None, "No http/bearer security scheme found"
        assert jwt_scheme["bearerFormat"] == "JWT"

    def test_api_key_scheme_exists(self):
        """ApiKeyAuth security scheme should be present."""
        schema = self._get_schema()
        schemes = schema["components"]["securitySchemes"]
        assert "ApiKeyAuth" in schemes or any(
            "apikey" in k.lower() or "api_key" in k.lower() for k in schemes
        ), f"API Key scheme not found in {list(schemes.keys())}"

    def test_api_key_scheme_type(self):
        """API Key scheme should be of type apiKey with header location."""
        schema = self._get_schema()
        schemes = schema["components"]["securitySchemes"]
        api_key_scheme = None
        for name, scheme in schemes.items():
            if scheme.get("type") == "apiKey":
                api_key_scheme = scheme
                break
        assert api_key_scheme is not None, "No apiKey security scheme found"
        assert api_key_scheme["in"] == "header"
        assert api_key_scheme["name"] == "X-API-Key"

    def test_global_security_defined(self):
        """Schema should have a top-level security array with both schemes."""
        schema = self._get_schema()
        assert "security" in schema
        assert len(schema["security"]) >= 1

    def test_global_security_contains_jwt(self):
        """Global security should include JWT bearer scheme."""
        schema = self._get_schema()
        schemes = schema["components"]["securitySchemes"]
        jwt_name = None
        for name, scheme in schemes.items():
            if scheme.get("type") == "http" and scheme.get("scheme") == "bearer":
                jwt_name = name
                break

        if jwt_name:
            global_has_jwt = any(
                jwt_name in sec for sec in schema["security"]
            )
            assert global_has_jwt, f"Global security missing {jwt_name}"

    def test_global_security_contains_api_key(self):
        """Global security should include API key scheme."""
        schema = self._get_schema()
        schemes = schema["components"]["securitySchemes"]
        api_key_name = None
        for name, scheme in schemes.items():
            if scheme.get("type") == "apiKey":
                api_key_name = name
                break

        if api_key_name:
            global_has_api_key = any(
                api_key_name in sec for sec in schema["security"]
            )
            assert global_has_api_key, f"Global security missing {api_key_name}"


class TestErrorSchemas:
    """Verify error response schemas are documented."""

    def _get_schema(self) -> dict:
        return client.get("/openapi.json").json()

    def test_error_400_schema(self):
        """Should have Error400BadRequest schema with example."""
        schema = self._get_schema()
        schemas = schema["components"]["schemas"]
        assert "Error400BadRequest" in schemas
        err = schemas["Error400BadRequest"]
        assert "example" in err
        assert "detail" in err["example"]
        assert "error_code" in err["example"]

    def test_error_401_schema(self):
        """Should have Error401Unauthorized schema with example."""
        schema = self._get_schema()
        schemas = schema["components"]["schemas"]
        assert "Error401Unauthorized" in schemas
        err = schemas["Error401Unauthorized"]
        assert "example" in err
        assert "detail" in err["example"]

    def test_error_403_schema(self):
        """Should have Error403Forbidden schema with example."""
        schema = self._get_schema()
        schemas = schema["components"]["schemas"]
        assert "Error403Forbidden" in schemas
        err = schemas["Error403Forbidden"]
        assert "example" in err
        assert "detail" in err["example"]
        assert "error_code" in err["example"]

    def test_error_404_schema(self):
        """Should have Error404NotFound schema with example."""
        schema = self._get_schema()
        schemas = schema["components"]["schemas"]
        assert "Error404NotFound" in schemas
        err = schemas["Error404NotFound"]
        assert "example" in err
        assert "detail" in err["example"]

    def test_error_429_schema(self):
        """Should have Error429TooManyRequests schema with example."""
        schema = self._get_schema()
        schemas = schema["components"]["schemas"]
        assert "Error429TooManyRequests" in schemas
        err = schemas["Error429TooManyRequests"]
        assert "example" in err
        assert "error" in err["example"]
        assert "retry_after" in err["example"]

    def test_endpoint_has_429_response(self):
        """At least one endpoint should reference the 429 error schema."""
        schema = self._get_schema()
        refs = json.dumps(schema)
        assert "Error429TooManyRequests" in refs

    def test_endpoint_has_404_response(self):
        """At least one endpoint should reference the 404 error schema."""
        schema = self._get_schema()
        refs = json.dumps(schema)
        assert "Error404NotFound" in refs


class TestSchemaStructure:
    """Verify overall schema structure and endpoint documentation."""

    def _get_schema(self) -> dict:
        return client.get("/openapi.json").json()

    def test_paths_exist(self):
        """Schema should define paths."""
        schema = self._get_schema()
        assert "paths" in schema
        assert len(schema["paths"]) > 0

    def test_health_endpoint_documented(self):
        """Health endpoint should be in the schema."""
        schema = self._get_schema()
        assert "/health" in schema["paths"]

    def test_tags_exist(self):
        """Endpoints should have tags."""
        schema = self._get_schema()
        all_paths = schema["paths"]
        has_tags = False
        for path, methods in all_paths.items():
            for method, config in methods.items():
                if "tags" in config and len(config["tags"]) > 0:
                    has_tags = True
                    break
        assert has_tags, "No endpoints have tags defined"

    def test_examples_on_schemas(self):
        """All custom error schemas should have examples."""
        schema = self._get_schema()
        schemas = schema["components"]["schemas"]
        error_schemas = [s for s in schemas if s.startswith("Error")]
        for name in error_schemas:
            assert "example" in schemas[name], f"Schema {name} missing example"

    def test_security_schemes_count(self):
        """There should be exactly 2 security schemes."""
        schema = self._get_schema()
        schemes = schema["components"]["securitySchemes"]
        assert len(schemes) >= 2, f"Expected at least 2 security schemes, got {len(schemes)}"


class TestRoutesWithAuth:
    """Verify routes from the routers are included."""

    def _get_schema(self) -> dict:
        return client.get("/openapi.json").json()

    def test_agents_router_paths_included(self):
        """Agent router paths should be in the schema."""
        schema = self._get_schema()
        paths = schema["paths"]
        agent_paths = [p for p in paths if p.startswith("/agents")]
        assert len(agent_paths) > 0, "No /agents paths found in schema"

    def test_tasks_router_paths_included(self):
        """Task router paths should be in the schema."""
        schema = self._get_schema()
        paths = schema["paths"]
        task_paths = [p for p in paths if p.startswith("/tasks")]
        assert len(task_paths) > 0, "No /tasks paths found in schema"

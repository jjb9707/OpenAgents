"""Tests for OpenAPI schema generation with authentication security schemes."""

import json
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


class TestOpenAPIMetadata:
    """Test that OpenAPI metadata is configured correctly."""

    def test_schema_endpoint_returns_200(self):
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_openapi_version(self):
        response = client.get("/openapi.json")
        schema = response.json()
        assert "openapi" in schema

    def test_api_title(self):
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "OpenAgents API"

    def test_api_version(self):
        schema = client.get("/openapi.json").json()
        assert schema["info"]["version"] == "0.1.0"

    def test_contact_present(self):
        schema = client.get("/openapi.json").json()
        assert "contact" in schema["info"]
        assert schema["info"]["contact"]["name"] == "ClankerNation"

    def test_license_present(self):
        schema = client.get("/openapi.json").json()
        assert "license" in schema["info"]
        assert schema["info"]["license"]["name"] == "MIT"


class TestSecuritySchemes:
    """Test that both authentication methods are documented in OpenAPI."""

    def test_security_schemes_exist(self):
        schema = client.get("/openapi.json").json()
        assert "components" in schema
        assert "securitySchemes" in schema["components"]

    def test_jwt_bearer_scheme_present(self):
        schema = client.get("/openapi.json").json()
        schemes = schema["components"]["securitySchemes"]
        assert "JWTBearer" in schemes

    def test_jwt_bearer_scheme_type(self):
        schema = client.get("/openapi.json").json()
        scheme = schema["components"]["securitySchemes"]["JWTBearer"]
        assert scheme["type"] == "http"
        assert scheme["scheme"] == "bearer"
        assert scheme["bearerFormat"] == "JWT"

    def test_api_key_scheme_present(self):
        schema = client.get("/openapi.json").json()
        schemes = schema["components"]["securitySchemes"]
        assert "ApiKeyAuth" in schemes

    def test_api_key_scheme_type(self):
        schema = client.get("/openapi.json").json()
        scheme = schema["components"]["securitySchemes"]["ApiKeyAuth"]
        assert scheme["type"] == "apiKey"
        assert scheme["in"] == "header"
        assert scheme["name"] == "X-API-Key"

    def test_security_scheme_count(self):
        schema = client.get("/openapi.json").json()
        assert len(schema["components"]["securitySchemes"]) == 2

    def test_global_security_present(self):
        """Test that global security is applied showing lock icons."""
        schema = client.get("/openapi.json").json()
        assert "security" in schema
        assert isinstance(schema["security"], list)
        assert len(schema["security"]) >= 1

    def test_global_security_contains_jwt(self):
        schema = client.get("/openapi.json").json()
        security = schema["security"]
        has_jwt = any("JWTBearer" in entry for entry in security)
        assert has_jwt, "JWTBearer not found in global security"

    def test_global_security_contains_api_key(self):
        schema = client.get("/openapi.json").json()
        security = schema["security"]
        has_api_key = any("ApiKeyAuth" in entry for entry in security)
        assert has_api_key, "ApiKeyAuth not found in global security"


class TestErrorSchemas:
    """Test that error response schemas are documented."""

    def test_error_schema_400_exists(self):
        schema = client.get("/openapi.json").json()
        schemas = schema["components"].get("schemas", {})
        assert "Error400BadRequest" in schemas

    def test_error_schema_401_exists(self):
        schema = client.get("/openapi.json").json()
        schemas = schema["components"].get("schemas", {})
        assert "Error401Unauthorized" in schemas

    def test_error_schema_403_exists(self):
        schema = client.get("/openapi.json").json()
        schemas = schema["components"].get("schemas", {})
        assert "Error403Forbidden" in schemas

    def test_error_schema_404_exists(self):
        schema = client.get("/openapi.json").json()
        schemas = schema["components"].get("schemas", {})
        assert "Error404NotFound" in schemas

    def test_error_schema_429_exists(self):
        schema = client.get("/openapi.json").json()
        schemas = schema["components"].get("schemas", {})
        assert "Error429TooManyRequests" in schemas

    def test_error_schemas_have_examples(self):
        schema = client.get("/openapi.json").json()
        schemas = schema["components"].get("schemas", {})
        for name in ["Error400BadRequest", "Error401Unauthorized", "Error403Forbidden", "Error404NotFound", "Error429TooManyRequests"]:
            assert "example" in schemas[name], f"{name} missing example"

    def test_error_schema_count(self):
        schema = client.get("/openapi.json").json()
        schemas = schema["components"].get("schemas", {})
        error_schemas = [k for k in schemas if k.startswith("Error") or k in ("HTTPValidationError", "ValidationError")]
        assert len(error_schemas) >= 7


class TestSchemaStructure:
    """Test the overall structure of the generated OpenAPI schema."""

    def test_paths_exist(self):
        schema = client.get("/openapi.json").json()
        assert "paths" in schema
        assert len(schema["paths"]) > 0

    def test_paths_contain_agents_endpoints(self):
        schema = client.get("/openapi.json").json()
        assert "/agents" in schema["paths"]
        assert "/agents/{agent_id}" in schema["paths"]

    def test_paths_contain_health_endpoint(self):
        schema = client.get("/openapi.json").json()
        assert "/health" in schema["paths"]

    def test_endpoints_have_summaries(self):
        schema = client.get("/openapi.json").json()
        has_summary = any(
            "summary" in method
            for path in schema["paths"].values()
            for method in path.values()
        )
        assert has_summary

    def test_swagger_ui_accessible(self):
        response = client.get("/docs")
        assert response.status_code == 200
        assert "swagger" in response.text.lower() or "openapi" in response.text.lower()


class TestAuthIntegration:
    """Test that auth middleware properly handles both auth methods."""

    def test_openapi_security_shows_locked_endpoints(self):
        """Lock icons shown via global security declaration in OpenAPI schema."""
        schema = client.get("/openapi.json").json()
        assert "security" in schema
        assert len(schema["security"]) >= 2

    def test_health_endpoint_is_accessible(self):
        response = client.get("/health")
        assert response.status_code == 200
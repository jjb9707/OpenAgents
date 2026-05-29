"""Tests for audit logging on all admin endpoints."""

import json
import os
import sys

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.main import app
from api.models.database import Base, get_db

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

Base.metadata.create_all(bind=engine)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


def _create_admin_token():
    return jwt.encode(
        {"sub": "1", "address": "0xadmin", "roles": ["admin"], "username": "admin", "type": "access"},
        "test-secret-audit",
        algorithm="HS256",
    )


def _create_user_token():
    return jwt.encode(
        {"sub": "2", "address": "0xuser", "roles": ["user"], "username": "user", "type": "access"},
        "test-secret-audit",
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint,method", [
    ("POST", "/admin/agents"),
    ("PUT", "/admin/agents/1"),
    ("DELETE", "/admin/agents/1"),
    ("POST", "/admin/tasks"),
    ("PATCH", "/admin/tasks/1/status"),
    ("DELETE", "/admin/tasks/1"),
    ("GET", "/admin/audit-log"),
])
def test_non_admin_rejected(endpoint, method):
    """Non-admin users should get 403 on all admin endpoints."""
    token = _create_user_token()
    headers = {"Authorization": f"Bearer {token}"}

    if endpoint == "GET":
        resp = client.get("/admin/audit-log", headers=headers)
    elif endpoint == "POST":
        body = {"name": "test", "description": "d", "model_type": "gpt-4"}
        resp = client.post("/admin/agents", json=body, headers=headers)
    elif endpoint == "PUT":
        body = {"name": "updated"}
        resp = client.put("/admin/agents/1", json=body, headers=headers)
    elif endpoint == "DELETE":
        resp = client.delete("/admin/agents/1", headers=headers)
    elif endpoint == "PATCH":
        body = {"status": "open"}
        resp = client.patch("/admin/tasks/1/status", json=body, headers=headers)

    assert resp.status_code == 403, f"{method} {endpoint} returned {resp.status_code}"


# ---------------------------------------------------------------------------
# Empty audit log query
# ---------------------------------------------------------------------------


def test_empty_audit_log():
    """Querying audit log with no entries should return empty results."""
    token = _create_admin_token()
    resp = client.get("/admin/audit-log", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["results"] == []


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_audit_log_pagination():
    """Skip/limit should work for audit log queries."""
    token = _create_admin_token()
    resp = client.get("/admin/audit-log?skip=0&limit=10", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["skip"] == 0
    assert data["limit"] == 10


# ---------------------------------------------------------------------------
# Agent CRUD creates audit logs
# ---------------------------------------------------------------------------


def test_create_agent_creates_audit_log():
    """Creating an agent via admin endpoint should create an audit entry."""
    token = _create_admin_token()
    body = {"name": "TestAgent", "description": "A test agent", "model_type": "gpt-4"}

    resp = client.post("/admin/agents", json=body, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    log_resp = client.get("/admin/audit-log?entity_type=agent", headers={"Authorization": f"Bearer {token}"})
    logs = log_resp.json()["results"]
    assert len(logs) >= 1
    log = logs[0]
    assert log["action"] == "create"
    assert log["entity_type"] == "agent"
    assert log["actor_address"] == "0xadmin"
    assert "TestAgent" in log["details"]


def test_update_agent_creates_audit_log():
    """Updating an agent should create audit entry with before/after values."""
    token = _create_admin_token()

    create_resp = client.post("/admin/agents", json={"name": "UpdateMe", "model_type": "gpt-3"},
                              headers={"Authorization": f"Bearer {token}"})
    agent_id = create_resp.json()["id"]

    update_resp = client.put(f"/admin/agents/{agent_id}", json={"name": "UpdatedName", "model_type": "gpt-4"},
                             headers={"Authorization": f"Bearer {token}"})
    assert update_resp.status_code == 200

    log_resp = client.get("/admin/audit-log?entity_type=agent", headers={"Authorization": f"Bearer {token}"})
    logs = log_resp.json()["results"]
    assert len(logs) >= 2
    update_log = logs[0]
    assert update_log["action"] == "update"
    assert update_log["before_value"]["name"] == "UpdateMe"
    assert update_log["after_value"]["name"] == "UpdatedName"


def test_delete_agent_creates_audit_log():
    """Deleting an agent should create audit entry with before snapshot."""
    token = _create_admin_token()

    create_resp = client.post("/admin/agents", json={"name": "ToDelete", "model_type": "gpt-4"},
                              headers={"Authorization": f"Bearer {token}"})
    agent_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/admin/agents/{agent_id}", headers={"Authorization": f"Bearer {token}"})
    assert delete_resp.status_code == 200

    log_resp = client.get("/admin/audit-log?entity_type=agent", headers={"Authorization": f"Bearer {token}"})
    logs = log_resp.json()["results"]
    delete_log = [l for l in logs if l["action"] == "delete"][0]
    assert delete_log["before_value"]["name"] == "ToDelete"
    assert delete_log["details"] is not None


# ---------------------------------------------------------------------------
# Task status update with audit log
# ---------------------------------------------------------------------------


def test_task_status_update_creates_audit_log():
    """Updating task status should create audit entry."""
    token = _create_admin_token()

    create_resp = client.post("/admin/tasks", json={"title": "Test Task", "description": "desc", "reward_amount": 100.0},
                              headers={"Authorization": f"Bearer {token}"})
    task_id = create_resp.json()["id"]

    update_resp = client.patch(f"/admin/tasks/{task_id}/status", json={"status": "in_progress"},
                               headers={"Authorization": f"Bearer {token}"})
    assert update_resp.status_code == 200

    log_resp = client.get(f"/admin/audit-log?entity_type=task&entity_id={task_id}",
                          headers={"Authorization": f"Bearer {token}"})
    logs = log_resp.json()["results"]
    assert len(logs) >= 1
    log = logs[0]
    assert log["action"] == "update_status"
    assert log["after_value"]["status"] == "in_progress"


def test_invalid_status_rejected():
    """Setting an invalid status should return 400."""
    token = _create_admin_token()
    resp = client.patch("/admin/tasks/999/status", json={"status": "invalid_status"},
                        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_filter_by_action():
    """Audit logs should be filterable by action type."""
    token = _create_admin_token()
    client.post("/admin/agents", json={"name": "FilterTest", "model_type": "gpt-4"},
                headers={"Authorization": f"Bearer {token}"})

    create_logs = client.get("/admin/audit-log?action=create",
                             headers={"Authorization": f"Bearer {token}"})
    update_logs = client.get("/admin/audit-log?action=update",
                             headers={"Authorization": f"Bearer {token}"})

    create_actions = {l["action"] for l in create_logs.json()["results"]}
    assert "create" in create_actions


def test_filter_by_entity_type():
    """Audit logs should be filterable by entity type."""
    token = _create_admin_token()
    client.post("/admin/agents", json={"name": "AgentFilter", "model_type": "gpt-4"},
                headers={"Authorization": f"Bearer {token}"})
    client.post("/admin/tasks", json={"title": "TaskFilter", "description": "desc", "reward_amount": 50.0},
                headers={"Authorization": f"Bearer {token}"})

    agent_logs = client.get("/admin/audit-log?entity_type=agent",
                            headers={"Authorization": f"Bearer {token}"})
    task_logs = client.get("/admin/audit-log?entity_type=task",
                           headers={"Authorization": f"Bearer {token}"})

    agent_types = {l["entity_type"] for l in agent_logs.json()["results"]}
    task_types = {l["entity_type"] for l in task_logs.json()["results"]}
    assert "agent" in agent_types
    assert "task" in task_types


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_audit_logs_immutability():
    """Audit log records should not have delete or update endpoints."""
    endpoints = [route.path for route in app.routes]

    for ep in endpoints:
        if "audit-log" in ep:
            routes = [r for r in app.routes if hasattr(r, 'path') and r.path == ep]
            for r in routes:
                methods = getattr(r, 'methods', set())
                assert "PUT" not in methods, f"Audit log has PUT endpoint at {ep}"
                assert "DELETE" not in methods, f"Audit log has DELETE endpoint at {ep}"


# ---------------------------------------------------------------------------
# IP address capture
# ---------------------------------------------------------------------------


def test_ip_address_captured():
    """Audit log should capture the client IP address."""
    token = _create_admin_token()
    client.post("/admin/agents", json={"name": "IPTest", "model_type": "gpt-4"},
                headers={"Authorization": f"Bearer {token}"})

    log_resp = client.get("/admin/audit-log?action=create",
                          headers={"Authorization": f"Bearer {token}"})
    logs = log_resp.json()["results"]
    assert len(logs) >= 1
    log = logs[0]
    assert log["ip_address"] is not None
    assert log["ip_address"] != ""


# ---------------------------------------------------------------------------
# Actor tracking
# ---------------------------------------------------------------------------


def test_actor_id_captured():
    """Audit log should capture the actor's user ID."""
    token = _create_admin_token()
    client.post("/admin/agents", json={"name": "ActorTest", "model_type": "gpt-4"},
                headers={"Authorization": f"Bearer {token}"})

    log_resp = client.get("/admin/audit-log?actor_id=1",
                          headers={"Authorization": f"Bearer {token}"})
    logs = log_resp.json()["results"]
    assert len(logs) >= 1
    log = logs[0]
    assert log["actor_id"] == 1
    assert log["actor_address"] == "0xadmin"

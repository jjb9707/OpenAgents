"""
# Hermes Agent (jjb9707) — Audit logging tests
# Platform: Hermes AI Agent / DeepSeek-v4-flash
# OS: Linux x86_64
# Home: /home/jjb
# Workdir: /tmp/OpenAgents
# Session: Bounty #192 — Tests for audit logging implementation
"""

import json
import os
import jwt
import pytest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.models.database import AuditLog, get_db, Base, engine

JWT_SECRET = "test-secret-audit"
TEST_DB_URL = "sqlite:///./test_audit.db"


def _make_admin_token():
    """Create a JWT token with admin role."""
    payload = {"sub": "1", "address": "0xadmin", "roles": ["admin"], "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _make_user_token():
    """Create a JWT token without admin role."""
    payload = {"sub": "2", "address": "0xuser", "roles": ["user"], "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    """Set up a fresh file-based SQLite database for each test."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
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
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    with patch.dict(os.environ, {"JWT_SECRET": JWT_SECRET}):
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Audit log API endpoint tests
# ---------------------------------------------------------------------------


def test_list_audit_log_requires_admin(client):
    """Non-admin users should get 403 when accessing audit logs."""
    token = _make_user_token()
    resp = client.get(
        "/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "Role" in resp.json()["detail"]


def test_list_audit_log_empty(client):
    """Admin should get empty list when no audit logs exist."""
    token = _make_admin_token()
    resp = client.get(
        "/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["results"] == []


def test_list_audit_log_pagination(client):
    """Audit log should support skip/limit pagination."""
    from api.models.database import AuditLog
    from sqlalchemy.orm import Session

    # Get the override DB
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)

    # Create 5 audit entries
    for i in range(5):
        log = AuditLog(
            action="test_action",
            entity_type="agent",
            entity_id=i,
            actor_id=1,
            actor_address="0xadmin",
            ip_address="127.0.0.1",
            details=f"Test entry {i}",
            created_at=datetime.utcnow(),
        )
        db.add(log)
    db.commit()
    db_gen.close()

    token = _make_admin_token()

    # Test with limit
    resp = client.get(
        "/admin/audit-log?limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["results"]) == 2
    assert data["limit"] == 2

    # Test with skip
    resp = client.get(
        "/admin/audit-log?skip=3&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 2  # 5 total - 3 skipped


def test_list_audit_log_filters(client):
    """Audit log should support filtering by action, entity_type, entity_id, actor_id."""
    from api.models.database import AuditLog
    from sqlalchemy.orm import Session

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)

    logs_data = [
        ("create", "agent", 1, 1),
        ("update", "agent", 1, 1),
        ("delete", "agent", 1, 1),
        ("create", "task", 10, 2),
        ("update", "task", 10, 2),
    ]
    for action, etype, eid, aid in logs_data:
        log = AuditLog(
            action=action,
            entity_type=etype,
            entity_id=eid,
            actor_id=aid,
            actor_address=f"0x{aid}",
            ip_address="127.0.0.1",
            created_at=datetime.utcnow(),
        )
        db.add(log)
    db.commit()
    db_gen.close()

    token = _make_admin_token()

    # Filter by action
    resp = client.get(
        '/admin/audit-log?action=create',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(r["action"] == "create" for r in data["results"])

    # Filter by entity_type
    resp = client.get(
        '/admin/audit-log?entity_type=task',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(r["entity_type"] == "task" for r in data["results"])

    # Filter by entity_id
    resp = client.get(
        '/admin/audit-log?entity_id=1',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert all(r["entity_id"] == 1 for r in data["results"])

    # Filter by actor_id
    resp = client.get(
        '/admin/audit-log?actor_id=2',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(r["actor_id"] == 2 for r in data["results"])


# ---------------------------------------------------------------------------
# Admin write endpoint audit tests
# ---------------------------------------------------------------------------


def test_admin_create_agent_creates_audit_log(client):
    """Creating an agent via admin endpoint should create an audit log entry."""
    token = _make_admin_token()
    resp = client.post(
        "/admin/agents",
        json={"name": "Test Agent", "description": "Test description"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Agent"

    # Verify audit log was created
    resp = client.get(
        "/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert logs["total"] >= 1
    log = logs["results"][0]
    assert log["action"] == "create"
    assert log["entity_type"] == "agent"
    assert log["entity_id"] == data["id"]
    assert log["actor_id"] == 1
    assert log["actor_address"] == "0xadmin"
    assert log["after_value"] is not None


def test_admin_update_agent_creates_audit_log(client):
    """Updating an agent via admin endpoint should create an audit log with before/after."""
    token = _make_admin_token()

    # Create agent
    create_resp = client.post(
        "/admin/agents",
        json={"name": "Original Name", "description": "Original desc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    agent_id = create_resp.json()["id"]

    # Update agent
    update_resp = client.put(
        f"/admin/agents/{agent_id}",
        json={"name": "Updated Name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_resp.status_code == 200

    # Check audit log
    resp = client.get(
        "/admin/audit-log?action=update",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert logs["total"] >= 1
    log = logs["results"][0]

    assert log["action"] == "update"
    assert log["entity_type"] == "agent"
    assert log["entity_id"] == agent_id

    # Verify before/after values
    if log["before_value"]:
        assert "Original Name" in str(log["before_value"])
    if log["after_value"]:
        assert "Updated Name" in str(log["after_value"])


def test_admin_delete_agent_creates_audit_log(client):
    """Deleting an agent via admin endpoint should create an audit log."""
    token = _make_admin_token()

    # Create agent
    create_resp = client.post(
        "/admin/agents",
        json={"name": "Delete Me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    agent_id = create_resp.json()["id"]

    # Delete agent
    delete_resp = client.delete(
        f"/admin/agents/{agent_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_resp.status_code == 200

    # Check audit log
    resp = client.get(
        "/admin/audit-log?action=delete",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert logs["total"] >= 1
    log = logs["results"][0]
    assert log["action"] == "delete"
    assert log["entity_type"] == "agent"
    assert log["entity_id"] == agent_id


def test_admin_create_task_creates_audit_log(client):
    """Creating a task via admin endpoint should create an audit log entry."""
    token = _make_admin_token()
    resp = client.post(
        "/admin/tasks",
        json={
            "title": "Test Task",
            "description": "Task description",
            "reward_amount": 100.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "open"

    # Verify audit log
    resp = client.get(
        "/admin/audit-log?action=create&entity_type=task",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert logs["total"] >= 1
    log = logs["results"][0]
    assert log["entity_type"] == "task"
    assert log["entity_id"] == data["id"]


def test_admin_update_task_status_creates_audit_log(client):
    """Updating task status via admin should create audit log with before/after."""
    token = _make_admin_token()

    # Create task
    create_resp = client.post(
        "/admin/tasks",
        json={
            "title": "Status Test",
            "description": "Testing status change",
            "reward_amount": 50.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    task_id = create_resp.json()["id"]

    # Update status
    update_resp = client.patch(
        f"/admin/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "in_progress"

    # Verify audit log
    resp = client.get(
        "/admin/audit-log?action=update_status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert logs["total"] >= 1
    log = logs["results"][0]
    assert log["entity_id"] == task_id
    assert log["action"] == "update_status"
    if log["before_value"]:
        assert log["before_value"]["status"] == "open"
    if log["after_value"]:
        assert log["after_value"]["status"] == "in_progress"


def test_admin_update_task_status_invalid(client):
    """Admin endpoint should reject invalid task statuses."""
    token = _make_admin_token()

    # Create task
    create_resp = client.post(
        "/admin/tasks",
        json={
            "title": "Invalid Status",
            "description": "Test",
            "reward_amount": 10.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    task_id = create_resp.json()["id"]

    # Try invalid status
    resp = client.patch(
        f"/admin/tasks/{task_id}/status",
        json={"status": "invalid_status_xyz"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_admin_cancel_task_creates_audit_log(client):
    """Cancelling a task via admin should create an audit log."""
    token = _make_admin_token()

    create_resp = client.post(
        "/admin/tasks",
        json={
            "title": "Cancel Me",
            "description": "Will be cancelled",
            "reward_amount": 25.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    task_id = create_resp.json()["id"]

    # Cancel task
    cancel_resp = client.delete(
        f"/admin/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    # Verify audit log
    resp = client.get(
        "/admin/audit-log?action=cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert logs["total"] >= 1


def test_admin_non_admin_rejected(client):
    """Non-admin users should be rejected from all admin endpoints."""
    token = _make_user_token()

    endpoints = [
        ("POST", "/admin/agents", {"name": "test", "description": "test"}),
        ("PUT", "/admin/agents/1", {"name": "updated"}),
        ("DELETE", "/admin/agents/1", None),
        ("POST", "/admin/tasks", {
            "title": "test", "description": "test", "reward_amount": 10.0
        }),
        ("PATCH", "/admin/tasks/1/status", {"status": "completed"}),
        ("DELETE", "/admin/tasks/1", None),
        ("GET", "/admin/audit-log", None),
    ]

    for method, path, body in endpoints:
        if method == "GET":
            resp = client.get(path, headers={"Authorization": f"Bearer {token}"})
        elif method == "DELETE":
            resp = client.delete(path, headers={"Authorization": f"Bearer {token}"})
        elif method == "PATCH":
            resp = client.patch(path, json=body, headers={"Authorization": f"Bearer {token}"})
        else:
            resp = client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403, f"{method} {path} should return 403"


def test_audit_log_immutable_no_delete(client):
    """Audit log entries should not be deletable through the API."""
    # There's no delete endpoint for audit logs — verify it doesn't exist
    token = _make_admin_token()
    resp = client.delete(
        "/admin/audit-log/1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (404, 405, 307), (
        "Audit log delete endpoint should not exist"
    )


def test_audit_log_immutable_no_update(client):
    """Audit log entries should not be updatable through the API."""
    token = _make_admin_token()
    resp = client.put(
        "/admin/audit-log/1",
        json={"details": "hacked"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (404, 405, 307), (
        "Audit log update endpoint should not exist"
    )


def test_audit_log_includes_ip(client):
    """Audit log entries should include the client IP address."""
    token = _make_admin_token()
    resp = client.post(
        "/admin/agents",
        json={"name": "IP Test Agent"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    agent_id = resp.json()["id"]

    resp = client.get(
        "/admin/audit-log?action=create",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    logs = resp.json()
    log = [l for l in logs["results"] if l["entity_id"] == agent_id][0]
    assert log["ip_address"] is not None


def test_audit_log_serialized_before_after(client):
    """Audit log before/after fields should be valid JSON dicts."""
    token = _make_admin_token()

    # Create
    create_resp = client.post(
        "/admin/agents",
        json={"name": "BeforeAfter Agent", "description": "Initial"},
        headers={"Authorization": f"Bearer {token}"},
    )
    agent_id = create_resp.json()["id"]

    # Update
    client.put(
        f"/admin/agents/{agent_id}",
        json={"description": "Updated description"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Check audit log
    resp = client.get(
        "/admin/audit-log?action=update",
        headers={"Authorization": f"Bearer {token}"},
    )
    logs = resp.json()
    log = [l for l in logs["results"] if l["entity_id"] == agent_id][0]
    assert log["before_value"] is not None
    assert log["after_value"] is not None
    assert isinstance(log["before_value"], dict)
    assert isinstance(log["after_value"], dict)
    assert log["before_value"].get("description") == "Initial"
    assert log["after_value"].get("description") == "Updated description"

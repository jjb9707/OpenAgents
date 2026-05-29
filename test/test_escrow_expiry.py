"""Tests for escrow auto-refund endpoint (issue #197)."""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

from api.main import app
from api.models.database import init_db, get_db, SessionLocal, Payment, AuditLog, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite:///./test_openagents.db"
test_engine = create_engine(TEST_DB_URL, echo=False)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    from api.middleware.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1, "address": "0xuser", "roles": ["admin"]
    }

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_fresh_escrow_not_affected(client, db_session):
    """Fresh escrow (under 30 days) should not be processed."""
    fresh = Payment(
        task_id=1, from_address="0xpayer", amount=100.0,
        status="escrowed", created_at=datetime.utcnow()
    )
    db_session.add(fresh)
    db_session.commit()

    resp = client.post("/payments/process-expired")
    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 0


def test_expired_escrow_refunded(client, db_session):
    """Escrow older than 30 days should be refunded."""
    old = Payment(
        task_id=1, from_address="0xpayer", amount=100.0,
        status="escrowed", created_at=datetime.utcnow() - timedelta(days=31)
    )
    db_session.add(old)
    db_session.commit()

    resp = client.post("/payments/process-expired")
    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 1
    assert data["refunds"][0]["amount"] == 100.0
    assert data["refunds"][0]["refund_to"] == "0xpayer"


def test_already_refunded_not_processed_again(client, db_session):
    """Already refunded escrows should not be processed."""
    refunded = Payment(
        task_id=1, from_address="0xpayer", amount=100.0,
        status="refunded", created_at=datetime.utcnow() - timedelta(days=31),
        expired_at=datetime.utcnow(), refunded_at=datetime.utcnow()
    )
    db_session.add(refunded)
    db_session.commit()

    resp = client.post("/payments/process-expired")
    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == 0


def test_audit_log_created(client, db_session):
    """Each refund should create an audit log entry."""
    old = Payment(
        task_id=1, from_address="0xpayer", amount=50.0,
        status="escrowed", created_at=datetime.utcnow() - timedelta(days=31)
    )
    db_session.add(old)
    db_session.commit()

    resp = client.post("/payments/process-expired")
    assert resp.status_code == 200

    logs = db_session.query(AuditLog).filter(
        AuditLog.action == "escrow_auto_refund"
    ).all()
    assert len(logs) == 1
    assert "50.0" in logs[0].details

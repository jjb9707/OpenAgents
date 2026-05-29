"""
# Hermes Agent (jjb9707) — Audit logging implementation
# Platform: Hermes AI Agent / DeepSeek-v4-flash
# OS: Linux x86_64
# Home: /home/jjb
# Workdir: /tmp/OpenAgents
# Session: Bounty #192 — Audit logging for all admin actions
"""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..models.database import get_db, AuditLog, Agent, Task, Payment
from ..middleware.auth import get_current_user, require_role

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _serialize(obj):
    """Convert a SQLAlchemy model instance to a JSON-safe dict."""
    if obj is None:
        return None
    if hasattr(obj, "__table__"):
        result = {}
        for col in obj.__table__.columns:
            val = getattr(obj, col.name)
            if isinstance(val, datetime):
                val = val.isoformat()
            result[col.name] = val
        return result
    return None


def create_audit_log(
    db,
    action: str,
    entity_type: str,
    entity_id: int,
    actor: dict,
    ip_address: str,
    before_value: Optional[dict] = None,
    after_value: Optional[dict] = None,
    details: Optional[str] = None,
):
    """Create an immutable audit log entry."""
    log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor.get("id"),
        actor_address=actor.get("address"),
        actor_username=actor.get("username"),
        ip_address=ip_address,
        before_value=json.dumps(before_value) if before_value else None,
        after_value=json.dumps(after_value) if after_value else None,
        details=details,
        created_at=datetime.utcnow(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ---------------------------------------------------------------------------
# Agent admin endpoints
# ---------------------------------------------------------------------------


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    model_type: str = "gpt-4"
    config: Optional[dict] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None


@router.post("/agents")
async def admin_create_agent(
    agent: AgentCreate,
    request: Request,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
):
    new_agent = Agent(
        name=agent.name,
        description=agent.description,
        model_type=agent.model_type,
        config=agent.config or {},
        owner_id=user["id"],
        created_at=datetime.utcnow(),
    )
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)

    create_audit_log(
        db,
        action="create",
        entity_type="agent",
        entity_id=new_agent.id,
        actor=user,
        ip_address=_get_client_ip(request),
        after_value=_serialize(new_agent),
        details=f"Admin created agent '{new_agent.name}'",
    )

    return {"id": new_agent.id, "name": new_agent.name, "owner": user.get("address")}


@router.put("/agents/{agent_id}")
async def admin_update_agent(
    agent_id: int,
    update: AgentUpdate,
    request: Request,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    before = _serialize(agent)
    for field, value in update.dict(exclude_unset=True).items():
        setattr(agent, field, value)
    db.commit()
    db.refresh(agent)

    create_audit_log(
        db,
        action="update",
        entity_type="agent",
        entity_id=agent.id,
        actor=user,
        ip_address=_get_client_ip(request),
        before_value=before,
        after_value=_serialize(agent),
        details=f"Admin updated agent '{agent.name}'",
    )

    return agent


@router.delete("/agents/{agent_id}")
async def admin_delete_agent(
    agent_id: int,
    request: Request,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    before = _serialize(agent)
    db.delete(agent)
    db.commit()

    create_audit_log(
        db,
        action="delete",
        entity_type="agent",
        entity_id=agent_id,
        actor=user,
        ip_address=_get_client_ip(request),
        before_value=before,
        details=f"Admin deleted agent '{agent.name}' (id={agent_id})",
    )

    return {"deleted": True, "agent_id": agent_id}


# ---------------------------------------------------------------------------
# Task admin endpoints
# ---------------------------------------------------------------------------


class TaskCreate(BaseModel):
    title: str
    description: str
    reward_amount: float
    agent_id: Optional[int] = None
    deadline: Optional[datetime] = None


class TaskStatusUpdate(BaseModel):
    status: str


VALID_STATUSES = {"open", "assigned", "in_progress", "review", "completed", "cancelled"}


@router.post("/tasks")
async def admin_create_task(
    task: TaskCreate,
    request: Request,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
):
    new_task = Task(
        title=task.title,
        description=task.description,
        reward_amount=task.reward_amount,
        creator_id=user["id"],
        agent_id=task.agent_id,
        status="open",
        created_at=datetime.utcnow(),
        deadline=task.deadline,
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    create_audit_log(
        db,
        action="create",
        entity_type="task",
        entity_id=new_task.id,
        actor=user,
        ip_address=_get_client_ip(request),
        after_value=_serialize(new_task),
        details=f"Admin created task '{new_task.title}'",
    )

    return {"id": new_task.id, "status": new_task.status}


@router.patch("/tasks/{task_id}/status")
async def admin_update_task_status(
    task_id: int,
    update: TaskStatusUpdate,
    request: Request,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
):
    if update.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{update.status}'. Must be one of {VALID_STATUSES}",
        )

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    before = _serialize(task)
    task.status = update.status
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)

    create_audit_log(
        db,
        action="update_status",
        entity_type="task",
        entity_id=task.id,
        actor=user,
        ip_address=_get_client_ip(request),
        before_value=before,
        after_value=_serialize(task),
        details=f"Admin set task {task.id} status to '{update.status}'",
    )

    return {"id": task.id, "status": task.status}


@router.delete("/tasks/{task_id}")
async def admin_cancel_task(
    task_id: int,
    request: Request,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    before = _serialize(task)
    task.status = "cancelled"
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)

    create_audit_log(
        db,
        action="cancel",
        entity_type="task",
        entity_id=task.id,
        actor=user,
        ip_address=_get_client_ip(request),
        before_value=before,
        after_value=_serialize(task),
        details=f"Admin cancelled task {task.id}",
    )

    return {"id": task.id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Payment / Escrow admin endpoints
# ---------------------------------------------------------------------------


@router.post("/payments/process-expired")
async def admin_process_expired_escrows(
    request: Request,
    user=Depends(require_role("admin")),
    db=Depends(get_db),
):
    """Admin endpoint to process expired escrows with audit logging."""
    from datetime import timedelta
    from sqlalchemy import and_

    grace_period = datetime.utcnow() - timedelta(days=30)

    expired = (
        db.query(Payment)
        .filter(
            and_(
                Payment.status == "escrowed",
                Payment.created_at < grace_period,
                Payment.expired_at.is_(None),
            )
        )
        .all()
    )

    processed = []
    for payment in expired:
        before = _serialize(payment)
        payment.status = "refunded"
        payment.expired_at = datetime.utcnow()
        payment.refunded_at = datetime.utcnow()
        after = _serialize(payment)

        create_audit_log(
            db,
            action="escrow_auto_refund",
            entity_type="payment",
            entity_id=payment.id,
            actor=user,
            ip_address=_get_client_ip(request),
            before_value=before,
            after_value=after,
            details=f"Escrow {payment.id} auto-refunded {payment.amount} to {payment.from_address}",
        )

        processed.append({
            "payment_id": payment.id,
            "task_id": payment.task_id,
            "amount": payment.amount,
            "refund_to": payment.from_address,
        })

    db.commit()

    return {
        "processed": len(processed),
        "refunds": processed,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Audit log query endpoint (immutable — no delete or update)
# ---------------------------------------------------------------------------


@router.get("/audit-log")
async def list_audit_logs(
    request: Request,
    action: Optional[str] = Query(None, description="Filter by action type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[int] = Query(None, description="Filter by entity ID"),
    actor_id: Optional[int] = Query(None, description="Filter by actor ID"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    user=Depends(require_role("admin")),
    db=Depends(get_db),
):
    """List audit log entries with filtering and pagination.
    
    The audit log is immutable — entries cannot be deleted or updated.
    """
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)

    total = query.count()
    logs = (
        query.order_by(AuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "results": [
            {
                "id": log.id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "actor_id": log.actor_id,
                "actor_address": log.actor_address,
                "actor_username": log.actor_username,
                "ip_address": log.ip_address,
                "before_value": json.loads(log.before_value) if log.before_value else None,
                "after_value": json.loads(log.after_value) if log.after_value else None,
                "details": log.details,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }

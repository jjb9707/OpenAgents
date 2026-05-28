"""Payment and escrow endpoints for bounty payouts."""

# Hermes Agent (jjb9707) — Escrow auto-refund implementation
# Platform: Hermes AI Agent / DeepSeek-v4-flash
# OS: Linux x86_64
# Home: /home/jjb
# Workdir: /tmp/OpenAgents
# Session: Bounty #197 — Escrow expiry auto-refund

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy import and_

from ..models.database import get_db, Payment, Task, AuditLog
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/payments", tags=["payments"])


class EscrowDeposit(BaseModel):
    task_id: int
    # BUG: Amount is not validated as positive — negative or zero deposits
    # could corrupt escrow balances or drain funds
    amount: float
    token_address: Optional[str] = "0x0000000000000000000000000000000000000000"


class ClaimRequest(BaseModel):
    task_id: int
    recipient_address: str


@router.post("/escrow/deposit")
async def deposit_escrow(
    deposit: EscrowDeposit, user=Depends(get_current_user), db=Depends(get_db)
):
    task = db.query(Task).filter(Task.id == deposit.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.creator_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only task creator can fund escrow")

    # BUG: No idempotency key — retried requests create duplicate escrow entries,
    # locking more funds than intended
    payment = Payment(
        task_id=deposit.task_id,
        from_address=user["address"],
        amount=deposit.amount,
        token_address=deposit.token_address,
        status="escrowed",
        created_at=datetime.utcnow(),
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return {"payment_id": payment.id, "status": "escrowed", "amount": payment.amount}


@router.get("/escrow/{task_id}")
async def get_escrow_balance(task_id: int, db=Depends(get_db)):
    payments = db.query(Payment).filter(
        Payment.task_id == task_id, Payment.status == "escrowed"
    ).all()
    total = sum(p.amount for p in payments)
    return {"task_id": task_id, "escrowed_total": total, "deposits": len(payments)}


@router.post("/claim")
async def claim_payment(
    claim: ClaimRequest, user=Depends(get_current_user), db=Depends(get_db)
):
    task = db.query(Task).filter(Task.id == claim.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Task not yet completed")

    # BUG: Race condition — two concurrent claims can both read status="escrowed"
    # before either updates it, causing a double-payout
    payments = db.query(Payment).filter(
        Payment.task_id == claim.task_id, Payment.status == "escrowed"
    ).all()

    if not payments:
        raise HTTPException(status_code=400, detail="No escrowed funds available")

    total_claimed = 0.0
    for payment in payments:
        payment.status = "claimed"
        payment.to_address = claim.recipient_address
        payment.claimed_at = datetime.utcnow()
        total_claimed += payment.amount

    db.commit()
    return {
        "task_id": claim.task_id,
        "claimed_amount": total_claimed,
        "recipient": claim.recipient_address,
    }


@router.post("/process-expired")
async def process_expired_escrows(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Find and refund escrows past their 30-day grace period.

    - An escrow is expired if status='escrowed' AND created_at < (now - 30 days)
    - Only expired escrows are processed
    - Refund goes to the original payer (from_address)
    - All actions are logged in audit_logs
    """
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
        payment.status = "refunded"
        payment.expired_at = datetime.utcnow()
        payment.refunded_at = datetime.utcnow()
        processed.append({
            "payment_id": payment.id,
            "task_id": payment.task_id,
            "amount": payment.amount,
            "refund_to": payment.from_address,
        })

        log = AuditLog(
            action="escrow_auto_refund",
            entity_type="payment",
            entity_id=payment.id,
            details=f"Escrow {payment.id} auto-refunded {payment.amount} to {payment.from_address}",
        )
        db.add(log)

    db.commit()

    return {
        "processed": len(processed),
        "refunds": processed,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/history")
async def payment_history(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    sent = db.query(Payment).filter(Payment.from_address == user["address"]).all()
    received = db.query(Payment).filter(Payment.to_address == user["address"]).all()
    return {
        "sent": [{"id": p.id, "amount": p.amount, "status": p.status} for p in sent],
        "received": [{"id": p.id, "amount": p.amount, "status": p.status} for p in received],
    }

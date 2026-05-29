# @contributor: Hermes Agent @jjb9707
# @date: 2026-05-29T03:18:45Z
# @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-157 shell=/bin/bash

"""Payment and escrow endpoints for bounty payouts."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ..models.database import get_db, Payment, Task
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/payments", tags=["payments"])


class EscrowDeposit(BaseModel):
    task_id: int
    # BUG: Amount is not validated as positive -- negative or zero deposits
    # could corrupt escrow balances or drain funds
    amount: float
    token_address: Optional[str] = "0x0000000000000000000000000000000000000000"


class ClaimRequest(BaseModel):
    task_id: int
    recipient_address: str


@router.post(
    "/escrow/deposit",
    summary="Deposit funds into escrow",
    description="Deposit tokens into escrow for a task. Requires authentication and task ownership.",
    responses={
        201: {"description": "Escrow deposit created"},
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error401Unauthorized"}
                }
            },
        },
        403: {
            "description": "Forbidden -- only task creator can fund escrow",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error403Forbidden"}
                }
            },
        },
        404: {
            "description": "Task not found",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error404NotFound"}
                }
            },
        },
    },
)
async def deposit_escrow(
    deposit: EscrowDeposit, user=Depends(get_current_user), db=Depends(get_db)
):
    task = db.query(Task).filter(Task.id == deposit.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.creator_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only task creator can fund escrow")

    # BUG: No idempotency key -- retried requests create duplicate escrow entries
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


@router.get(
    "/escrow/{task_id}",
    summary="Get escrow balance",
    description="Retrieve the total escrowed balance for a task.",
    responses={
        404: {
            "description": "Task not found",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error404NotFound"}
                }
            },
        },
    },
)
async def get_escrow_balance(task_id: int, db=Depends(get_db)):
    payments = db.query(Payment).filter(
        Payment.task_id == task_id, Payment.status == "escrowed"
    ).all()
    total = sum(p.amount for p in payments)
    return {"task_id": task_id, "escrowed_total": total, "deposits": len(payments)}


@router.post(
    "/claim",
    summary="Claim payment",
    description="Claim escrowed funds for a completed task. Requires authentication.",
    responses={
        200: {"description": "Payment claimed"},
        400: {
            "description": "Task not completed or no funds available",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error400BadRequest"}
                }
            },
        },
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error401Unauthorized"}
                }
            },
        },
        404: {
            "description": "Task not found",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error404NotFound"}
                }
            },
        },
    },
)
async def claim_payment(
    claim: ClaimRequest, user=Depends(get_current_user), db=Depends(get_db)
):
    task = db.query(Task).filter(Task.id == claim.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Task not yet completed")

    # BUG: Race condition -- two concurrent claims can both read status="escrowed"
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


@router.get(
    "/history",
    summary="Get payment history",
    description="Retrieve payment history for the authenticated user.",
    responses={
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error401Unauthorized"}
                }
            },
        },
    },
)
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
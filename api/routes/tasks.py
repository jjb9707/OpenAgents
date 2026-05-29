# @contributor: Hermes Agent @jjb9707
# @date: 2026-05-29T03:18:45Z
# @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-157 shell=/bin/bash

"""Task management endpoints for bounty assignments."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ..models.database import get_db, Task
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])

VALID_STATUSES = {"open", "assigned", "in_progress", "review", "completed", "cancelled"}


class TaskCreate(BaseModel):
    title: str
    description: str
    reward_amount: float
    agent_id: Optional[int] = None
    deadline: Optional[datetime] = None


class TaskStatusUpdate(BaseModel):
    status: str  # BUG: Not validated against VALID_STATUSES enum -- any string accepted


@router.post(
    "/",
    summary="Create a new task",
    description="Create a bounty task. Requires authentication.",
    responses={
        201: {"description": "Task created"},
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
async def create_task(task: TaskCreate, user=Depends(get_current_user), db=Depends(get_db)):
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
    return {"id": new_task.id, "status": new_task.status}


@router.get(
    "/",
    summary="List all tasks",
    description="List bounty tasks with optional status and creator filters.",
)
async def list_tasks(
    status: Optional[str] = None,
    creator: Optional[str] = None,
    skip: int = Query(0, ge=0),
    # BUG: No upper bound on limit -- clients can request millions of rows
    limit: int = Query(50, ge=1),
    db=Depends(get_db),
):
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)
    if creator:
        query = query.filter(Task.creator_id == creator)
    return query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


@router.get(
    "/{task_id}",
    summary="Get task by ID",
    description="Retrieve details of a specific task.",
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
async def get_task(task_id: int, db=Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch(
    "/{task_id}/status",
    summary="Update task status",
    description="Update task status. Requires authentication and ownership.",
    responses={
        200: {"description": "Status updated"},
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error401Unauthorized"}
                }
            },
        },
        403: {
            "description": "Forbidden -- only creator can update",
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
async def update_task_status(
    task_id: int,
    update: TaskStatusUpdate,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # BUG: Creator can mark their own task as completed -- should require
    # a third party or the assignee to confirm completion
    if task.creator_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only the creator can update status")

    task.status = update.status
    task.updated_at = datetime.utcnow()
    db.commit()
    return {"id": task.id, "status": task.status}


@router.delete(
    "/{task_id}",
    summary="Cancel task",
    description="Cancel an open or assigned task. Requires authentication and ownership.",
    responses={
        200: {"description": "Task cancelled"},
        400: {
            "description": "Cannot cancel active/in-progress task",
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
        403: {
            "description": "Forbidden -- only creator can cancel",
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
async def cancel_task(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.creator_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only the creator can cancel")
    if task.status not in ("open", "assigned"):
        raise HTTPException(status_code=400, detail="Cannot cancel an active task")
    task.status = "cancelled"
    db.commit()
    return {"id": task.id, "status": "cancelled"}
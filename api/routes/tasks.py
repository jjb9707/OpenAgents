"""
Task management endpoints for bounty assignments with WebSocket real-time updates.

@contributor: Hermes Agent @jjb9707
@date: 2026-05-29T19:00:00Z
@session-init: You are Hermes, an advanced AI assistant built by Nous Research. You operate as an autonomous agent with access to tools including terminal, file operations, and code editing. This session was started to implement GitHub bounty issue #155 - WebSocket endpoint for real-time task updates.
@runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-110 shell=/bin/bash
"""

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, Set, Dict
from datetime import datetime

from ..models.database import get_db, Task
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])

VALID_STATUSES = {"open", "assigned", "in_progress", "review", "completed", "cancelled"}


class ConnectionManager:
    """Manages WebSocket connections with per-task subscriptions."""

    def __init__(self):
        # All connected clients: websocket -> client_id
        self._clients: Dict[WebSocket, str] = {}
        # Task subscriptions: task_id -> set of websockets
        self._subscriptions: Dict[int, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket) -> str:
        await websocket.accept()
        client_id = f"client_{id(websocket)}"
        self._clients[websocket] = client_id
        return client_id

    def disconnect(self, websocket: WebSocket):
        self._clients.pop(websocket, None)
        # Remove from all subscriptions
        for task_id in list(self._subscriptions.keys()):
            self._subscriptions[task_id].discard(websocket)
            if not self._subscriptions[task_id]:
                del self._subscriptions[task_id]

    async def subscribe(self, websocket: WebSocket, task_id: int):
        if task_id not in self._subscriptions:
            self._subscriptions[task_id] = set()
        self._subscriptions[task_id].add(websocket)

    async def unsubscribe(self, websocket: WebSocket, task_id: int):
        if task_id in self._subscriptions:
            self._subscriptions[task_id].discard(websocket)
            if not self._subscriptions[task_id]:
                del self._subscriptions[task_id]

    async def broadcast_task_update(self, task_id: int, update_data: dict):
        """Broadcast a task update to all subscribers of this task."""
        message = json.dumps({
            "type": "task_update",
            "task_id": task_id,
            "data": update_data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        subscribers = self._subscriptions.get(task_id, set())
        dead = set()
        for ws in subscribers:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        # Clean up dead connections
        for ws in dead:
            self.disconnect(ws)

    async def send_heartbeat(self, websocket: WebSocket):
        """Send a heartbeat ping."""
        try:
            await websocket.send_text(json.dumps({"type": "heartbeat", "timestamp": datetime.utcnow().isoformat()}))
        except Exception:
            self.disconnect(websocket)

    @property
    def connected_count(self) -> int:
        return len(self._clients)


# Singleton connection manager
manager = ConnectionManager()


class TaskCreate(BaseModel):
    title: str
    description: str
    reward_amount: float
    agent_id: Optional[int] = None
    deadline: Optional[datetime] = None


class TaskStatusUpdate(BaseModel):
    status: str  # BUG: Not validated against VALID_STATUSES enum — any string accepted


@router.post("/")
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


@router.get("/")
async def list_tasks(
    status: Optional[str] = None,
    creator: Optional[str] = None,
    skip: int = Query(0, ge=0),
    # BUG: No upper bound on limit — clients can request millions of rows,
    # causing DB strain and potential OOM
    limit: int = Query(50, ge=1),
    db=Depends(get_db),
):
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)
    if creator:
        query = query.filter(Task.creator_id == creator)
    return query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{task_id}")
async def get_task(task_id: int, db=Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ──────────────────────────────────────────────
#  WebSocket endpoint
# ──────────────────────────────────────────────


@router.websocket("/ws")
async def task_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time task updates.

    Connect and optionally subscribe to task IDs.
    Protocol:
    - Client sends: {"type": "subscribe", "task_id": 123}
    - Client sends: {"type": "unsubscribe", "task_id": 123}
    - Server sends: {"type": "task_update", "task_id": 123, ...}
    - Server sends: {"type": "heartbeat", "timestamp": "..."} (every 30s)
    """
    client_id = await manager.connect(websocket)

    # Start heartbeat task
    async def heartbeat_loop():
        while True:
            await asyncio.sleep(30)
            try:
                await manager.send_heartbeat(websocket)
            except Exception:
                break

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", "")

                if msg_type == "subscribe":
                    task_id = msg.get("task_id")
                    if task_id is not None:
                        await manager.subscribe(websocket, task_id)
                        await websocket.send_text(json.dumps({
                            "type": "subscribed",
                            "task_id": task_id,
                        }))

                elif msg_type == "unsubscribe":
                    task_id = msg.get("task_id")
                    if task_id is not None:
                        await manager.unsubscribe(websocket, task_id)
                        await websocket.send_text(json.dumps({
                            "type": "unsubscribed",
                            "task_id": task_id,
                        }))

                elif msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON",
                }))

    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        manager.disconnect(websocket)


@router.patch("/{task_id}/status")
async def update_task_status(
    task_id: int,
    update: TaskStatusUpdate,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # BUG: Creator can mark their own task as completed — should require
    # a third party or the assignee to confirm completion
    if task.creator_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only the creator can update status")

    old_status = task.status
    task.status = update.status
    task.updated_at = datetime.utcnow()
    db.commit()

    # Broadcast the status change via WebSocket
    update_data = {
        "task_id": task.id,
        "title": task.title,
        "old_status": old_status,
        "new_status": update.status,
        "updated_by": user.get("address", str(user["id"])),
    }
    await manager.broadcast_task_update(task_id, update_data)

    return {"id": task.id, "status": task.status}


@router.delete("/{task_id}")
async def cancel_task(task_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.creator_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only the creator can cancel")
    if task.status not in ("open", "assigned"):
        raise HTTPException(status_code=400, detail="Cannot cancel an active task")
    old_status = task.status
    task.status = "cancelled"
    db.commit()

    # Broadcast cancellation
    await manager.broadcast_task_update(task_id, {
        "task_id": task.id,
        "title": task.title,
        "old_status": old_status,
        "new_status": "cancelled",
        "updated_by": user.get("address", str(user["id"])),
    })

    return {"id": task.id, "status": "cancelled"}

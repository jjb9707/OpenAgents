"""
# Hermes Agent (jjb9707) — OpenAPI security schema documentation
# Platform: Hermes AI Agent / DeepSeek-v4-flash
# OS: Linux x86_64
# Home: /home/jjb
# Workdir: /tmp/OpenAgents
# Session: Bounty #171 — OpenAPI schema generation with auth docs
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from typing import Optional, Any, Dict
from datetime import datetime

from .routes.agents import router as agents_router
from .routes.admin import router as admin_router


class ErrorResponse(BaseModel):
    detail: str


class ValidationError(BaseModel):
    detail: list[Dict[str, Any]]


app = FastAPI(
    title="OpenAgents API",
    description="Off-chain indexer and agent discovery API for the OpenAgents protocol",
    version="0.1.0",
)

app.include_router(agents_router)
app.include_router(admin_router)


# Custom OpenAPI schema with security schemes
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="OpenAgents API",
        version="0.1.0",
        description="Off-chain indexer and agent discovery API for the OpenAgents protocol",
        routes=app.routes,
    )

    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT access token. Obtain via /auth/login endpoint.",
        },
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key for programmatic access.",
        },
    }

    # Add error response schemas
    openapi_schema["components"]["schemas"]["HTTPError"] = {
        "type": "object",
        "properties": {
            "detail": {"type": "string", "description": "Error message"}
        },
        "example": {"detail": "Not found"},
    }

    openapi_schema["components"]["schemas"]["ValidationError"] = {
        "type": "object",
        "properties": {
            "detail": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "loc": {"type": "array", "items": {"type": "string"}},
                        "msg": {"type": "string"},
                        "type": {"type": "string"},
                    },
                },
            }
        },
        "example": {
            "detail": [
                {
                    "loc": ["body", "name"],
                    "msg": "field required",
                    "type": "value_error.missing",
                }
            ]
        },
    }

    # Apply security to all endpoints by default
    openapi_schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


class AgentResponse(BaseModel):
    agent_id: str
    name: str
    owner: str
    endpoint: str
    reputation: int
    tasks_completed: int
    registered_at: datetime
    active: bool


class TaskResponse(BaseModel):
    task_id: int
    creator: str
    description: str
    reward_wei: str
    deadline: datetime
    status: str
    assigned_agent: Optional[str] = None


class LeaderboardEntry(BaseModel):
    agent_id: str
    name: str
    reputation: int
    tasks_completed: int
    success_rate: float


# In-memory store (placeholder for DB)
agents_cache: dict = {}
tasks_cache: dict = {}


@app.get(
    "/agents",
    response_model=list[AgentResponse],
    responses={
        200: {"description": "List of agents"},
        400: {"model": ErrorResponse, "description": "Invalid parameters"},
    },
)
async def list_agents(
    active_only: bool = Query(True),
    min_reputation: int = Query(0),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
):
    results = list(agents_cache.values())
    if active_only:
        results = [a for a in results if a.get("active")]
    results = [a for a in results if a.get("reputation", 0) >= min_reputation]
    return results[offset : offset + limit]


@app.get(
    "/agents/{agent_id}",
    response_model=AgentResponse,
    responses={
        200: {"description": "Agent found"},
        404: {"model": ErrorResponse, "description": "Agent not found"},
    },
)
async def get_agent(agent_id: str):
    if agent_id not in agents_cache:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agents_cache[agent_id]


@app.get(
    "/tasks",
    response_model=list[TaskResponse],
    responses={
        200: {"description": "List of tasks"},
        400: {"model": ErrorResponse, "description": "Invalid status filter"},
    },
)
async def list_tasks(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
):
    results = list(tasks_cache.values())
    if status:
        results = [t for t in results if t.get("status") == status]
    return results[offset : offset + limit]


@app.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    responses={
        200: {"description": "Task found"},
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
)
async def get_task(task_id: int):
    if task_id not in tasks_cache:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks_cache[task_id]


@app.get(
    "/leaderboard",
    response_model=list[LeaderboardEntry],
    responses={200: {"description": "Leaderboard rankings"}},
)
async def leaderboard(limit: int = Query(20, le=50)):
    entries = []
    for agent in agents_cache.values():
        completed = agent.get("tasks_completed", 0)
        entries.append(
            {
                "agent_id": agent["agent_id"],
                "name": agent["name"],
                "reputation": agent.get("reputation", 0),
                "tasks_completed": completed,
                "success_rate": completed / max(completed + 1, 1),
            }
        )
    entries.sort(key=lambda x: x["reputation"], reverse=True)
    return entries[:limit]


@app.get(
    "/health",
    responses={
        200: {"description": "Health check OK"},
        429: {"model": ErrorResponse, "description": "Rate limited"},
    },
)
async def health():
    return {
        "status": "ok",
        "agents_indexed": len(agents_cache),
        "tasks_indexed": len(tasks_cache),
        "timestamp": datetime.utcnow().isoformat(),
    }

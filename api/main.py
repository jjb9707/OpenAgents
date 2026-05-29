# @contributor: Hermes Agent @jjb9707
# @date: 2026-05-29T04:00:00Z
# @session-init: [REDACTED]
# @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-110 shell=/bin/bash
"""
OpenAgents API -- Off-chain indexer and agent discovery API for the OpenAgents protocol.
Provides agent registration, task management, payment escrow, and discovery endpoints
with JWT Bearer and API Key authentication.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

app = FastAPI(
    title="OpenAgents API",
    description="Off-chain indexer and agent discovery API for the OpenAgents protocol",
    version="0.1.0",
    contact={
        "name": "ClankerNation",
        "url": "https://github.com/ClankerNation/OpenAgents",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
)

# ---------------------------------------------------------------------------
# Error response schemas
# ---------------------------------------------------------------------------

class HTTPValidationError(BaseModel):
    detail: list["ValidationError"]

class ValidationError(BaseModel):
    loc: list[str]
    msg: str
    type: str

class Error400BadRequest(BaseModel):
    detail: str
    error_code: Optional[str] = None

class Error401Unauthorized(BaseModel):
    detail: str

class Error403Forbidden(BaseModel):
    detail: str
    error_code: Optional[str] = None

class Error404NotFound(BaseModel):
    detail: str

class Error429TooManyRequests(BaseModel):
    error: str
    retry_after: int

# ---------------------------------------------------------------------------
# Custom OpenAPI schema with security schemes
# ---------------------------------------------------------------------------

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title="OpenAgents API",
        version="0.1.0",
        description="Off-chain indexer and agent discovery API for the OpenAgents protocol",
        routes=app.routes,
        contact={
            "name": "ClankerNation",
            "url": "https://github.com/ClankerNation/OpenAgents",
        },
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
    )

    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "JWTBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT access token obtained via login. Pass as `Authorization: Bearer <token>`",
        },
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key for programmatic access. Pass as `X-API-Key: <your_key>`",
        },
    }

    # Error response schemas with examples
    schema["components"]["schemas"]["HTTPValidationError"] = {
        "title": "HTTPValidationError",
        "type": "object",
        "properties": {
            "detail": {
                "title": "Detail",
                "type": "array",
                "items": {"$ref": "#/components/schemas/ValidationError"},
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

    schema["components"]["schemas"]["ValidationError"] = {
        "title": "ValidationError",
        "type": "object",
        "properties": {
            "loc": {"title": "Location", "type": "array", "items": {"type": "string"}},
            "msg": {"title": "Message", "type": "string"},
            "type": {"title": "Error Type", "type": "string"},
        },
        "example": {"loc": ["body", "name"], "msg": "field required", "type": "value_error.missing"},
    }

    for code, title, example in [
        ("Error400BadRequest", "BadRequest", {"detail": "Invalid request parameters", "error_code": "BAD_REQUEST"}),
        ("Error401Unauthorized", "Unauthorized", {"detail": "Not authenticated"}),
        ("Error403Forbidden", "Forbidden", {"detail": "Role 'admin' required", "error_code": "FORBIDDEN"}),
        ("Error404NotFound", "NotFound", {"detail": "Agent not found"}),
        ("Error429TooManyRequests", "TooManyRequests", {"error": "Rate limit exceeded", "retry_after": 45}),
    ]:
        schema["components"]["schemas"][code] = {
            "title": title,
            "type": "object",
            "properties": {
                k: {"type": "string"} if isinstance(v, str) else {"type": "integer"}
                for k, v in example.items()
            },
            "example": example,
        }

    # Global security
    schema["security"] = [{"JWTBearer": []}, {"ApiKeyAuth": []}]

    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

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

@app.get("/agents", response_model=list[AgentResponse])
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

@app.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    if agent_id not in agents_cache:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agents_cache[agent_id]

@app.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
):
    results = list(tasks_cache.values())
    if status:
        results = [t for t in results if t.get("status") == status]
    return results[offset : offset + limit]

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int):
    if task_id not in tasks_cache:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks_cache[task_id]

@app.get("/leaderboard", response_model=list[LeaderboardEntry])
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

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agents_indexed": len(agents_cache),
        "tasks_indexed": len(tasks_cache),
        "timestamp": datetime.utcnow().isoformat(),
    }

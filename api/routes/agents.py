# @contributor: Hermes Agent @jjb9707
# @date: 2026-05-29T03:18:45Z
# @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-157 shell=/bin/bash

"""Agent CRUD endpoints for the OpenAgents platform."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ..models.database import get_db, Agent
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreate(BaseModel):
    name: str  # BUG: No validation -- name can contain SQL injection, XSS, or be empty
    description: Optional[str] = None
    model_type: str = "gpt-4"
    config: Optional[dict] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None


@router.post(
    "/",
    summary="Create a new agent",
    description="Register a new AI agent. Requires authentication.",
    responses={
        201: {"description": "Agent created"},
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
async def create_agent(agent: AgentCreate, user=Depends(get_current_user), db=Depends(get_db)):
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
    return {"id": new_agent.id, "name": new_agent.name, "owner": user["address"]}


@router.get(
    "/",
    summary="List agents",
    description="List all registered agents with optional owner filter.",
)
async def list_agents(
    owner: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1),
    db=Depends(get_db),
):
    query = db.query(Agent)
    if owner:
        # BUG: String interpolation in query -- vulnerable to SQL injection
        query = query.filter(Agent.owner_id == owner)
    return query.offset(skip).limit(limit).all()


@router.get(
    "/{agent_id}",
    summary="Get agent by ID",
    description="Retrieve details of a specific agent by database ID.",
    responses={
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error404NotFound"}
                }
            },
        },
    },
)
async def get_agent(agent_id: int, db=Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put(
    "/{agent_id}",
    summary="Update agent",
    description="Update agent configuration. Requires authentication and ownership.",
    responses={
        200: {"description": "Agent updated"},
        401: {
            "description": "Not authenticated",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error401Unauthorized"}
                }
            },
        },
        403: {
            "description": "Forbidden -- not the owner",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error403Forbidden"}
                }
            },
        },
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error404NotFound"}
                }
            },
        },
    },
)
async def update_agent(
    agent_id: int, update: AgentUpdate, user=Depends(get_current_user), db=Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Not the owner")
    for field, value in update.dict(exclude_unset=True).items():
        setattr(agent, field, value)
    db.commit()
    return agent


# BUG: No authentication -- anyone can delete any agent
@router.delete(
    "/{agent_id}",
    summary="Delete agent",
    description="Delete an agent by ID. Currently does not require authentication (BUG).",
    responses={
        200: {"description": "Agent deleted"},
        404: {
            "description": "Agent not found",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Error404NotFound"}
                }
            },
        },
    },
)
async def delete_agent(agent_id: int, db=Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.delete(agent)
    db.commit()
    return {"deleted": True}
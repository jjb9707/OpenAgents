"""
Agent CRUD endpoints for the OpenAgents platform.

Contributor (Issue #139):
  - jjb9707 (https://github.com/jjb9707)
  - Adds register_agent endpoint with URL validation (http/https),
    SSRF protection (private IP block), and reachability check (HEAD, 5s timeout).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, validator
from typing import Optional
from datetime import datetime
from urllib.parse import urlparse
import socket
import httpx

from ..models.database import get_db, Agent
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreate(BaseModel):
    name: str  # BUG: No validation — name can contain SQL injection, XSS, or be empty
    description: Optional[str] = None
    model_type: str = "gpt-4"
    config: Optional[dict] = None
    endpoint_url: Optional[str] = None  # Added for register_agent


class RegisterAgentRequest(BaseModel):
    name: str
    endpoint_url: str
    description: Optional[str] = None
    model_type: str = "gpt-4"
    config: Optional[dict] = None

    @validator("endpoint_url")
    def validate_url(cls, value):
        """Validate URL format is http/https and reject private/internal IPs."""
        if not value:
            raise ValueError("endpoint_url is required")

        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"endpoint_url must use http or https scheme, got '{parsed.scheme}'")
        if not parsed.netloc:
            raise ValueError("endpoint_url must contain a valid host")

        # SSRF protection: resolve hostname and check against private IP ranges
        host = parsed.hostname
        try:
            addrinfo = socket.getaddrinfo(host, None)
        except socket.gaierror:
            raise ValueError(f"endpoint_url host '{host}' could not be resolved")

        private_errors = []
        for family, _, _, _, sockaddr in addrinfo:
            ip = sockaddr[0]
            if _is_private_ip(ip):
                private_errors.append(ip)

        if private_errors:
            raise ValueError(
                f"endpoint_url resolves to private/internal IP(s): {', '.join(private_errors)}"
            )

        return value

    @validator("endpoint_url")
    def check_reachability(cls, value):
        """Verify the endpoint is reachable via HEAD request with 5s timeout."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.head(value, follow_redirects=True)
                # Any response (even 4xx/5xx) means reachable; we just care about connectivity
                resp.raise_for_status()
        except httpx.TimeoutException:
            raise ValueError(f"endpoint_url '{value}' timed out after 5 seconds")
        except httpx.ConnectError:
            raise ValueError(f"endpoint_url '{value}' could not be connected to")
        except httpx.HTTPStatusError as e:
            # Reachable but returned an error status — that's OK for connectivity check
            pass
        except httpx.RequestError as e:
            raise ValueError(f"endpoint_url '{value}' request failed: {e}")
        return value


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None


def _is_private_ip(ip: str) -> bool:
    """Check if an IP address falls within private/reserved ranges."""
    try:
        parts = [int(part) for part in ip.split(".")]
    except (ValueError, AttributeError):
        return False
    if len(parts) != 4:
        return False
    a, b, _, _ = parts
    # 127.0.0.0/8 (loopback)
    if a == 127:
        return True
    # 10.0.0.0/8 (private)
    if a == 10:
        return True
    # 172.16.0.0/12 (private)
    if a == 172 and 16 <= b <= 31:
        return True
    # 192.168.0.0/16 (private)
    if a == 192 and b == 168:
        return True
    # 169.254.0.0/16 (link-local)
    if a == 169 and b == 254:
        return True
    # 0.0.0.0/8 (current network)
    if a == 0:
        return True
    # 100.64.0.0/10 (CGNAT)
    if a == 100 and 64 <= b <= 127:
        return True
    # 198.18.0.0/15 (benchmarking)
    if a == 198 and 18 <= b <= 19:
        return True
    return False


@router.post("/register")
async def register_agent(
    request: RegisterAgentRequest,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Register a new agent with a validated endpoint URL.

    Validates:
    - URL format is http or https
    - URL does not resolve to a private/internal IP (SSRF protection)
    - URL is reachable via HEAD request (5s timeout)
    """
    new_agent = Agent(
        name=request.name,
        description=request.description,
        model_type=request.model_type,
        config=request.config or {},
        endpoint_url=request.endpoint_url,
        owner_id=user["id"],
        created_at=datetime.utcnow(),
    )
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)
    return {
        "id": new_agent.id,
        "name": new_agent.name,
        "endpoint_url": new_agent.endpoint_url,
        "owner": user["address"],
    }


@router.post("/")
async def create_agent(agent: AgentCreate, user=Depends(get_current_user), db=Depends(get_db)):
    new_agent = Agent(
        name=agent.name,
        description=agent.description,
        model_type=agent.model_type,
        config=agent.config or {},
        endpoint_url=agent.endpoint_url,
        owner_id=user["id"],
        created_at=datetime.utcnow(),
    )
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)
    return {"id": new_agent.id, "name": new_agent.name, "owner": user["address"]}


@router.get("/")
async def list_agents(
    owner: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1),
    db=Depends(get_db),
):
    query = db.query(Agent)
    if owner:
        # BUG: String interpolation in query — vulnerable to SQL injection
        query = query.filter(Agent.owner_id == owner)
    return query.offset(skip).limit(limit).all()


@router.get("/{agent_id}")
async def get_agent(agent_id: int, db=Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}")
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


# BUG: No authentication — anyone can delete any agent
@router.delete("/{agent_id}")
async def delete_agent(agent_id: int, db=Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.delete(agent)
    db.commit()
    return {"deleted": True}

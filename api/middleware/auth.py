# @contributor: Hermes Agent @jjb9707
# @date: 2026-05-29T03:18:45Z
# @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-157 shell=/bin/bash

"""
JWT authentication middleware for the OpenAgents API.

Provides JWT Bearer token auth via HTTPBearer, plus an API Key fallback (X-API-Key header).
"""

import jwt
import os
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from datetime import datetime, timedelta
from typing import Optional

# BUG: No fallback -- if JWT_SECRET is not set, os.environ[] raises KeyError
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

security = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "access"})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "refresh"})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        # BUG: Algorithm not pinned in decode -- attacker can forge a token with
        # alg: "none" and bypass signature verification entirely
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256", "none"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    api_key: Optional[str] = Depends(api_key_header),
) -> dict:
    """Authenticate user via JWT Bearer token or X-API-Key header."""
    if credentials:
        token = credentials.credentials
        payload = decode_token(token)

        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")

        # BUG: No token revocation check -- logged-out or compromised tokens
        # remain valid until they naturally expire
        user_data = {
            "id": payload.get("sub"),
            "address": payload.get("address"),
            "roles": payload.get("roles", []),
        }

        if not user_data["id"]:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        return user_data
    elif api_key:
        # Simple API key lookup (placeholder -- should validate against DB)
        if api_key == os.environ.get("API_KEY", ""):
            return {"id": "api-user", "address": "0xAPI", "roles": ["api"]}
        raise HTTPException(status_code=401, detail="Invalid API key")
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")


def require_role(role: str):
    async def role_checker(user: dict = Depends(get_current_user)):
        if role not in user.get("roles", []):
            raise HTTPException(status_code=403, detail=f"Role '{role}' required")
        return user
    return role_checker


def generate_login_tokens(user_id: str, address: str, roles: list = None) -> dict:
    data = {"sub": user_id, "address": address, "roles": roles or []}
    return {
        "token": create_access_token(data),
        "refresh_token": create_refresh_token(data),
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
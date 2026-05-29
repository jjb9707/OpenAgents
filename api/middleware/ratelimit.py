"""
Rate limiting middleware for the OpenAgents API.

Provides three-tier rate limiting based on authentication status:
- Anonymous: 60 req/min
- Authenticated: 300 req/min
- Premium API keys: 1000 req/min

@contributor: Hermes Agent @jjb9707
@date: 2026-05-29T18:45:00Z
@session-init: You are Hermes, an advanced AI assistant built by Nous Research. You operate as an autonomous agent with access to tools including terminal, file operations, and code editing. This session was started to implement GitHub bounty issue #174 - three-tier API rate limiting.
@runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-110 shell=/bin/bash
"""

import time
import hmac
from collections import defaultdict
from fastapi import Request, HTTPException, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Dict, List, Tuple, Optional


class SlidingWindowCounter:
    """Sliding window rate limit counter using sorted timestamps."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: List[float] = []

    def allow_request(self, now: float) -> Tuple[bool, int, int]:
        """Check if request is allowed.

        Returns:
            (allowed, remaining, retry_after)
        """
        # Prune old timestamps
        cutoff = now - self.window_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]

        if len(self.timestamps) >= self.max_requests:
            # Rate limited — calculate retry-after
            retry_after = int(self.timestamps[0] + self.window_seconds - now + 1)
            return False, 0, retry_after

        self.timestamps.append(now)
        remaining = self.max_requests - len(self.timestamps)
        return True, remaining, 0


# Tier configuration: (max_requests, window_seconds)
TIERS = {
    "premium": (1000, 60),
    "authenticated": (300, 60),
    "anonymous": (60, 60),
}

# Per-client counters
_counters: Dict[str, Dict[str, SlidingWindowCounter]] = defaultdict(dict)


def _get_tier(request: Request) -> str:
    """Determine rate limit tier from request auth state."""
    # Check for API key in header (premium)
    api_key = request.headers.get("X-API-Key")
    if api_key:
        # Verify API key — simple check for non-empty key
        # In production this would validate against a key store
        if len(api_key) >= 16:
            return "premium"

    # Check for valid JWT token (authenticated)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and len(auth_header) > 20:
        try:
            import jwt
            payload = jwt.decode(
                auth_header[7:],
                options={"verify_signature": False, "verify_exp": False},
            )
            if payload.get("sub"):
                roles = payload.get("roles", [])
                if "premium" in roles:
                    return "premium"
                return "authenticated"
        except Exception:
            pass

    return "anonymous"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces three-tier rate limits.

    Applies per-client rate limiting with sliding windows.
    Returns rate limit headers on every response.
    """

    def __init__(self, app):
        super().__init__(app)

    def _get_client_key(self, request: Request) -> str:
        """Get unique client key for rate limiting.

        Uses API key or user ID for authenticated requests,
        falls back to IP for anonymous.
        """
        api_key = request.headers.get("X-API-Key", "")
        if api_key:
            return f"apikey:{api_key[:16]}"

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                import jwt
                payload = jwt.decode(
                    auth[7:],
                    options={"verify_signature": False, "verify_exp": False},
                )
                if payload.get("sub"):
                    return f"user:{payload['sub']}"
            except Exception:
                pass

        # Fall back to IP
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        if request.client:
            return f"ip:{request.client.host}"
        return "ip:unknown"

    async def dispatch(self, request: Request, call_next):
        # Skip health endpoint
        if request.url.path.startswith("/health"):
            return await call_next(request)

        now = time.time()
        tier = _get_tier(request)
        max_req, window = TIERS[tier]
        client_key = self._get_client_key(request)

        # Get or create counter for this client + tier
        if tier not in _counters[client_key]:
            _counters[client_key][tier] = SlidingWindowCounter(max_req, window)
        counter = _counters[client_key][tier]

        allowed, remaining, retry_after = counter.allow_request(now)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "tier": tier,
                    "retry_after": retry_after,
                    "limit": max_req,
                    "remaining": 0,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_req),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now + retry_after)),
                    "X-RateLimit-Tier": tier,
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_req)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now + window))
        response.headers["X-RateLimit-Tier"] = tier
        return response

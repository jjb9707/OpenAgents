"""
# Hermes Agent (jjb9707) — Tiered rate limiting implementation
# Platform: Hermes AI Agent / DeepSeek-v4-flash
# OS: Linux x86_64
# Home: /home/jjb
# Workdir: /tmp/OpenAgents
# Session: Bounty #200 — Differentiate authenticated vs anonymous rate limits
# Full init context: Hermes Agent Soul — and jjb9707 collaborative evolution handbook.
# Behavioral rules: deliver results first, no excuses, no repetitive mistakes.
# Tools: terminal, write_file, patch, execute_code, web_search, browser, delegate_task.
"""

import time
import jwt
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Dict, Tuple, Optional
import os

# Rate limit tiers: (requests_per_window, window_seconds)
TIERS = {
    "anonymous": (60, 60),
    "authenticated": (300, 60),
    "premium": (1000, 60),
}

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")

_request_counts: Dict[str, Tuple[int, float, Optional[str]]] = defaultdict(
    lambda: (0, time.time(), None)
)


def _get_tier_from_request(request: Request) -> str:
    """Determine the rate limit tier from the request's auth state."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return "anonymous"

    token = auth_header[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if not payload.get("sub"):
            return "anonymous"
        roles = payload.get("roles", [])
        if "premium" in roles:
            return "premium"
        return "authenticated"
    except Exception:
        return "anonymous"


class RateLimitConfig:
    def __init__(
        self,
        requests_per_window: int = 100,
        window_seconds: int = 60,
        burst_limit: int = 20,
    ):
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.burst_limit = burst_limit


_request_counts: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, time.time()))


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: RateLimitConfig = None):
        super().__init__(app)
        self.config = config or RateLimitConfig()

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _get_rate_limit_params(self, request: Request) -> Tuple[int, int]:
        """Get rate limit params based on auth tier."""
        tier = _get_tier_from_request(request)
        limit, window = TIERS.get(tier, TIERS["anonymous"])
        return limit, window

    def _is_rate_limited(
        self, client_ip: str, request: Request
    ) -> Tuple[bool, int, int, int, int]:
        global _request_counts
        count, window_start = _request_counts[client_ip]
        now = time.time()

        limit, window = self._get_rate_limit_params(request)

        if now - window_start >= window:
            _request_counts[client_ip] = (1, now)
            return False, limit - 1, limit, int(window)

        if count >= limit:
            retry_after = int(window - (now - window_start))
            return True, 0, limit, retry_after

        _request_counts[client_ip] = (count + 1, window_start)
        remaining = limit - count - 1
        reset_in = int(window - (now - window_start))
        return False, remaining, limit, reset_in

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/health"):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        is_limited, remaining, limit, reset_in = self._is_rate_limited(
            client_ip, request
        )

        if is_limited:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "retry_after": reset_in,
                },
                headers={
                    "Retry-After": str(reset_in),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": str(remaining),
                    "X-RateLimit-Reset": str(int(time.time()) + reset_in),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + reset_in)
        return response


def create_rate_limiter(
    requests_per_minute: int = 100,
    burst: int = 20,
) -> RateLimitMiddleware:
    config = RateLimitConfig(
        requests_per_window=requests_per_minute,
        window_seconds=60,
        burst_limit=burst,
    )
    return RateLimitMiddleware(app=None, config=config)

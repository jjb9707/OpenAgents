"""
# Hermes Agent (jjb9707) — Tiered rate limiting implementation
# Platform: Hermes AI Agent / DeepSeek-v4-flash
# OS: Linux x86_64
# Home: /home/jjb
# Workdir: /home/jjb/.hermes/hermes-agent
# Session: Bounty #200 — Differentiate authenticated vs anonymous rate limits
# Full init context: Hermes Agent Soul — and jjb9707 collaborative evolution handbook.
# Tools: terminal, write_file, patch, execute_code, web_search, browser, delegate_task.
"""

import time
import jwt
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Dict, Tuple, Optional

# JWT secret — imported here for auth token decoding
JWT_SECRET = None  # Set at init from env or config

def _decode_bearer_token(request: Request) -> Optional[dict]:
    """Decode JWT from Authorization header, return payload or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        # Pin algorithm to HS256 to prevent alg:none attacks
        return jwt.decode(token, JWT_SECRET or "", algorithms=["HS256"], options={"verify_exp": False})
    except Exception:
        return None


class Tier:
    """Describes a single rate-limit tier's constraints."""
    __slots__ = ("limit", "window")

    def __init__(self, limit: int, window: int):
        self.limit = limit          # max requests
        self.window = window        # seconds

    @property
    def tier_name(self) -> str:
        if self.limit <= 60:
            return "anonymous"
        if self.limit <= 300:
            return "authenticated"
        return "premium"


# Rate-limit tiers: (reqs, window_seconds)
TIERS: Dict[str, Tier] = {
    "anonymous":      Tier(60,   60),
    "authenticated":  Tier(300,  60),
    "premium":        Tier(1000, 60),
}


class SlidingWindowCounter:
    """Sliding-window request log per client key.

    Stores timestamps of recent requests.  On each check, purges entries
    older than *window* seconds and decides whether the new request fits.
    """

    def __init__(self):
        self._store: Dict[str, list[float]] = defaultdict(list)

    def _purge(self, key: str, window: int) -> None:
        cutoff = time.time() - window
        self._store[key] = [t for t in self._store[key] if t > cutoff]

    def allow(self, key: str, limit: int, window: int) -> Tuple[bool, int]:
        """Return (allowed, remaining_before_request)."""
        self._purge(key, window)
        count = len(self._store[key])
        if count >= limit:
            # Next slot = oldest timestamp + window
            next_slot = int(self._store[key][0] + window - time.time())
            return False, max(next_slot, 0)
        self._store[key].append(time.time())
        return True, limit - count - 1

    def reset(self, key: str) -> None:
        self._store.pop(key, None)


# Shared in-memory sliding-window store
_sw_counter = SlidingWindowCounter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces tiered rate limits.

    Tiers (determined from the request's JWT or lack thereof):

        anonymous      60  req / 60 s
        authenticated  300 req / 60 s
        premium       1000 req / 60 s

    Headers added to every response:
      - X-RateLimit-Limit
      - X-RateLimit-Remaining
      - X-RateLimit-Reset (epoch seconds when the quota resets)

    On 429 the response also carries a Retry-After header (seconds).
    """

    def __init__(self, app, jwt_secret: Optional[str] = None):
        super().__init__(app)
        global JWT_SECRET
        JWT_SECRET = jwt_secret or JWT_SECRET

    # ------------------------------------------------------------------
    # Auth / tier resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_tier(payload: Optional[dict]) -> Tier:
        """Return the appropriate Tier for a decoded JWT payload (or None)."""
        if payload is None:
            return TIERS["anonymous"]

        roles = payload.get("roles", [])
        if "premium" in roles:
            return TIERS["premium"]
        # Any valid token → authenticated
        if payload.get("sub"):
            return TIERS["authenticated"]
        return TIERS["anonymous"]

    # ------------------------------------------------------------------
    # Rate-limit check
    # ------------------------------------------------------------------
    @staticmethod
    def _get_client_key(request: Request, tier: Tier) -> str:
        """Build a stable key for counting: uses user id, api-key, or IP."""
        # Authenticated / premium users keyed by user id
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            try:
                payload = jwt.decode(
                    token, JWT_SECRET or "", algorithms=["HS256"],
                    options={"verify_exp": False}
                )
                uid = payload.get("sub") or payload.get("address")
                if uid:
                    return f"user:{uid}"
            except Exception:
                pass
        # API key in X-API-Key header
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"apikey:{api_key}"
        # Fallback to IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        return f"ip:{ip}"

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    async def dispatch(self, request: Request, call_next):
        # Skip health endpoint
        if request.url.path.startswith("/health"):
            return await call_next(request)

        # 1. Auth
        payload = _decode_bearer_token(request)
        tier = self._resolve_tier(payload)

        # 2. Key & check
        client_key = self._get_client_key(request, tier)
        allowed, remaining = _sw_counter.allow(
            client_key, tier.limit, tier.window
        )

        if not allowed:
            reset_after = remaining  # seconds
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "tier": tier.tier_name,
                    "retry_after": reset_after,
                },
                headers={
                    "Retry-After": str(reset_after),
                    "X-RateLimit-Limit": str(tier.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        # 3. Proceed
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(tier.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        # Reset timestamp (epoch)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + tier.window)
        return response


def create_rate_limiter(
    jwt_secret: Optional[str] = None,
) -> RateLimitMiddleware:
    """Factory — create a tiered RateLimitMiddleware instance."""
    return RateLimitMiddleware(app=None, jwt_secret=jwt_secret)
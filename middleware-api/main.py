
import os
import time
import uuid
from collections import defaultdict, deque
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

app = FastAPI(title="Middleware Exam API")

# Assigned configuration
ALLOWED_ORIGIN = "https://app-rorncl.example.com"
RATE_LIMIT = 13
WINDOW_SECONDS = 10

# Set these environment variables for your deployment.
# EXAM_ORIGIN should be the exact origin of the exam page, if different.
EXAM_ORIGIN = os.getenv("EXAM_ORIGIN", "").strip().rstrip("/")
EMAIL = os.getenv("EMAIL", "22f3002265@ds.study.iitm.ac.in")

allowed_origins = [ALLOWED_ORIGIN]
if EXAM_ORIGIN and EXAM_ORIGIN not in allowed_origins:
    allowed_origins.append(EXAM_ORIGIN)

# In-memory rolling-window buckets, one per client ID.
requests_by_client = defaultdict(deque)
rate_lock = Lock()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_id = request.headers.get("X-Client-Id")

        if not client_id:
            # Keep clients without an ID in a separate IP-based bucket.
            client_ip = request.client.host if request.client else "unknown"
            client_id = f"ip:{client_ip}"

        now = time.monotonic()

        with rate_lock:
            bucket = requests_by_client[client_id]

            # Remove requests outside the rolling 10-second window.
            while bucket and now - bucket[0] >= WINDOW_SECONDS:
                bucket.popleft()

            if len(bucket) >= RATE_LIMIT:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": str(WINDOW_SECONDS)},
                )

            bucket.append(now)

        return await call_next(request)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# Add middleware in reverse order because the last added runs first:
# Request context -> CORS -> rate limiter -> endpoint.
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["X-Request-ID", "X-Client-Id", "Content-Type"],
    expose_headers=["X-Request-ID"],
)

app.add_middleware(RequestContextMiddleware)


@app.get("/ping")
async def ping(request: Request):
    return {
        "email": EMAIL,
        "request_id": request.state.request_id,
    }


@app.options("/ping")
async def ping_options():
    # Normally handled by CORSMiddleware for browser preflight.
    return Response(status_code=204)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

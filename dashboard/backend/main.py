"""FastAPI backend for the AI Flow dashboard. Serves the channel's database to the frontend under /api/v1/*.
Every request requires a shared token (added by the server, not the browser) because nginx publishes this API on the open internet."""

from __future__ import annotations

import hmac
import os
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import paths
from api import actions, companies, graph, nodes, posts, pulse, stats
from db_connector import DatabaseUnavailableError

app = FastAPI(title="AI Flow Dashboard API", version="2.0.0")

# Kept in the project's .env, never in a committed file (the old service file
# leaked one to GitHub). Empty means "refuse everything": a missing secret must
# fail closed, or a typo quietly reopens the API to the internet.
DASHBOARD_TOKEN = (os.environ.get("DASHBOARD_TOKEN") or paths.env().get("DASHBOARD_TOKEN") or "").strip()

PUBLIC_PATHS = {"/api/v1/health", "/docs", "/openapi.json"}


@app.middleware("http")
async def require_token(request: Request, call_next):
    if request.url.path not in PUBLIC_PATHS:
        supplied = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        # compare_digest so a wrong token cannot be guessed a character at a time.
        if not DASHBOARD_TOKEN or not hmac.compare_digest(supplied, DASHBOARD_TOKEN):
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)

# The token is what guards this API; the browser never calls it directly, so
# origins are not the control here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(DatabaseUnavailableError)
async def db_unavailable_handler(request: Request, exc: DatabaseUnavailableError):
    print(f"[main] 503 database unavailable on {request.url.path}: {exc}")
    return JSONResponse(status_code=503, content={"error": f"database unavailable: {exc}"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Every unexpected error is logged with a full traceback to stdout, per
    # the spec's "no silent failures" requirement, then reported as a clean
    # 500 instead of leaking a stack trace to the client.
    print(f"[main] unhandled error on {request.url.path}:")
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"error": "internal server error"})


app.include_router(actions.router, prefix="/api/v1", tags=["actions"])
app.include_router(posts.router, prefix="/api/v1")
app.include_router(companies.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(pulse.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")
app.include_router(nodes.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

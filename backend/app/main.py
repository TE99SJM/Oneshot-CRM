"""FunnelHub CRM - FastAPI application entry point.

Dev:   uvicorn app.main:app --reload            (frontend served by Vite on :5173)
Prod:  uvicorn app.main:app --host 0.0.0.0     (serves the built frontend from frontend/dist)
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routers import (activities, auth, channels, contacts, dashboard, deals, ebay_public, emails, funnels, messages, oauth_apps,
                      oauth_public, integrations, orders, posts, publish, site_visitors, system)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _reset_stuck_syncs()
    from .publishing.runner import reset_interrupted
    reset_interrupted()
    tasks = []
    if os.getenv("SYNC_SCHEDULER", "true").strip().lower() not in {"0", "false", "no", "off"}:
        from .integrations.scheduler import publish_loop, scheduler_loop
        tasks = [asyncio.create_task(scheduler_loop()), asyncio.create_task(publish_loop())]
    yield
    for task in tasks:
        task.cancel()


def _reset_stuck_syncs() -> None:
    """A restart mid-sync leaves status 'running'; mark it as an error so it can run again."""
    from sqlalchemy import update

    from .database import SessionLocal
    from .models import Integration
    with SessionLocal() as db:
        db.execute(update(Integration).where(Integration.last_status == "running")
                   .values(last_status="error", last_error="Interrupted by a restart; it will retry automatically."))
        db.commit()


app = FastAPI(title=settings.app_name, version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

for r in (system, auth, dashboard, site_visitors, channels, contacts, funnels, deals, posts, activities, oauth_apps, integrations, messages, orders, ebay_public, oauth_public, emails, publish):
    app.include_router(r.router)
app.include_router(publish.public_router)

# Serve the compiled React app (if it has been built) as a single-page application.
dist = settings.frontend_dist
if (dist / "index.html").exists():
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(404, "Not found")
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

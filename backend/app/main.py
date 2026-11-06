"""FunnelHub CRM - FastAPI application entry point.

Dev:   uvicorn app.main:app --reload            (frontend served by Vite on :5173)
Prod:  uvicorn app.main:app --host 0.0.0.0     (serves the built frontend from frontend/dist)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routers import activities, auth, channels, contacts, dashboard, deals, funnels, posts, system


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

for r in (system, auth, dashboard, channels, contacts, funnels, deals, posts, activities):
    app.include_router(r.router)

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

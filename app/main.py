"""Titik masuk aplikasi Lemari."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, db
from .web import router as web_router

log = logging.getLogger("lemari")


def jalankan_migrasi() -> None:
    """Naikkan skema ke revisi terakhir saat container start (idempoten)."""
    cfg = AlembicConfig(str(config.BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", config.sqlalchemy_dsn())
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        jalankan_migrasi()
        log.info("migrasi selesai")
    except Exception as exc:  # noqa: BLE001
        # jangan matikan app: /healthz harus tetap bisa menjawab agar kelihatan penyebabnya
        log.error("migrasi gagal: %s", str(exc)[:300])
    yield


app = FastAPI(title=config.APP_NAME, version=config.VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")


class UserMiddleware(BaseHTTPMiddleware):
    """Identitas user datang dari Authelia (header Remote-User) — atau LEMARI_DEV_USER saat lokal."""

    async def dispatch(self, request: Request, call_next):
        request.state.user = request.headers.get(config.HEADER_USER) or config.DEV_USER or None
        return await call_next(request)


app.add_middleware(UserMiddleware)
app.include_router(web_router)


@app.get("/healthz")
def healthz():
    """Endpoint publik untuk Uptime Kuma / Healthchecks — tidak lewat SSO."""
    try:
        nama_db, user_db = db.sehat()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"status": "degraded", "version": config.VERSION, "error": str(exc)[:200]},
            status_code=503,
        )
    return {"status": "ok", "version": config.VERSION, "db": {"database": nama_db, "user": user_db}}


@app.get("/sw.js")
def service_worker():
    """Service worker harus disajikan dari root supaya scope-nya seluruh aplikasi."""
    berkas = config.BASE_DIR / "static" / "sw.js"
    if not berkas.exists():
        return JSONResponse({"status": "belum ada"}, status_code=404)
    return FileResponse(berkas, media_type="application/javascript")


@app.get("/manifest.webmanifest")
def manifest():
    berkas = config.BASE_DIR / "static" / "manifest.webmanifest"
    if not berkas.exists():
        return JSONResponse({"status": "belum ada"}, status_code=404)
    return FileResponse(berkas, media_type="application/manifest+json")


@app.get("/offline", response_class=HTMLResponse)
def offline():
    berkas = config.BASE_DIR / "static" / "offline.html"
    if not berkas.exists():
        return HTMLResponse("<h1>Offline</h1>", status_code=200)
    return HTMLResponse(berkas.read_text())

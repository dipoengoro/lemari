"""Titik masuk aplikasi Lemari."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, db

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))

app = FastAPI(title=config.APP_NAME, version=config.VERSION, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")


class UserMiddleware(BaseHTTPMiddleware):
    """Identitas user datang dari Authelia (header Remote-User) — atau LEMARI_DEV_USER saat lokal."""

    async def dispatch(self, request: Request, call_next):
        request.state.user = request.headers.get(config.HEADER_USER) or config.DEV_USER or None
        return await call_next(request)


app.add_middleware(UserMiddleware)


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


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    try:
        db.sehat()
        db_ok, db_error = True, None
    except Exception as exc:  # noqa: BLE001
        db_ok, db_error = False, str(exc)[:300]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": config.APP_NAME,
            "version": config.VERSION,
            "user": request.state.user,
            "db_ok": db_ok,
            "db_error": db_error,
            "domain": config.DOMAIN,
        },
    )

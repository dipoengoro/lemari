"""Konfigurasi aplikasi — semua dari environment (diisi docker-compose lewat .env)."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


DSN_RAW = _env("LEMARI_DSN") or _env("DATABASE_URL")

APP_NAME = _env("LEMARI_APP_NAME", "Lemari")
VERSION = "0.7.1"
DOMAIN = _env("LEMARI_DOMAIN", "lemari.dipo.sh")
UPLOAD_DIR = Path(_env("LEMARI_UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")))

# batas ukuran foto saat diunggah
MEDIA_MAX_PX = int(_env("LEMARI_MEDIA_MAX_PX", "1600"))
THUMB_MAX_PX = int(_env("LEMARI_THUMB_MAX_PX", "400"))

# identitas user dari Authelia (forward-auth). LEMARI_DEV_USER dipakai saat lokal.
HEADER_USER = _env("LEMARI_HEADER_USER", "Remote-User")
DEV_USER = _env("LEMARI_DEV_USER")

# AI auto-tag: penyedia model vision (LEMARI_AI_PROVIDER=deepseek|openrouter)
OPENROUTER_KEY = _env("LEMARI_OPENROUTER_KEY")
DEEPSEEK_KEY = _env("LEMARI_DEEPSEEK_KEY") or _env("DEEPSEEK_API_KEY")
AI_PROVIDER = (_env("LEMARI_AI_PROVIDER") or ("deepseek" if DEEPSEEK_KEY else "openrouter")).lower()
_BAWAAAN_MODEL = {"deepseek": "deepseek-flash", "openrouter": "google/gemini-3.8-flash"}
VISION_MODEL = _env("LEMARI_VISION_MODEL") or _BAWAAAN_MODEL.get(AI_PROVIDER, "google/gemini-3.8-flash")
AI_AKTIF = _env("LEMARI_AI", "1") not in ("0", "false", "False", "")
# mode "berpikir" DeepSeek: untuk sekadar membaca atribut barang, hasilnya sama tapi 2,5x lebih hemat
# dan 2x lebih cepat kalau dimatikan (terukur 26 Sep 2026) — nyalakan kalau mau lebih teliti.
AI_THINKING = _env("LEMARI_AI_THINKING", "0") not in ("0", "false", "False", "")

# bot Telegram
TELEGRAM_BOT_TOKEN = _env("LEMARI_TELEGRAM_BOT_TOKEN") or _env("LEMARI_BOT_TOKEN")
TELEGRAM_ALLOWED_USER = _env("LEMARI_TELEGRAM_ALLOWED_USER")
TELEGRAM_TOPIC = _env("LEMARI_TELEGRAM_TOPIC")

# token servis: dipakai bot/script internal supaya tidak perlu login SSO
SERVICE_TOKEN = _env("LEMARI_SERVICE_TOKEN")


def sqlalchemy_dsn() -> str:
    if not DSN_RAW:
        raise RuntimeError("LEMARI_DSN belum diset")
    if DSN_RAW.startswith("postgresql://"):
        return DSN_RAW.replace("postgresql://", "postgresql+psycopg://", 1)
    return DSN_RAW

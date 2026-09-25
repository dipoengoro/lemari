# 🧺 Lemari

Aplikasi pencatat semua barang yang dipakai — pakaian, sepatu, tas, aksesoris, parfum, sampai barang
yang dipinjam orang. Punya web (bisa diinstall ke home screen HP) dan bot Telegram.

Self-hosted di VPS: web di `lemari.dipo.sh` (di belakang Caddy + SSO Authelia), database Postgres,
bot Telegram `@dipo_housekeeper_bot` yang menjawab command di topik 🧺 Lemari.

## Stack

- Backend: FastAPI + SQLAlchemy 2 + Alembic
- Database: Postgres 16 (satu database + satu role khusus: `lemari`)
- Tampilan: Jinja2 + HTMX + Tailwind (server-rendered, tanpa build step Node) + PWA
- Foto: dikompres ke WebP saat upload (sisi panjang maks 1600 px) + thumbnail 400 px
- AI: model vision OpenRouter untuk mengisi draft atribut dari foto
- Bot: container terpisah, memanggil REST API internal dengan service token

## Struktur

```
app/
  config.py    # semua konfigurasi dari environment
  db.py        # engine, session, Base
  main.py      # aplikasi FastAPI (healthz, halaman)
templates/     # Jinja2 (index.html dulu, menyusul katalog)
static/        # aset statis (css, ikon, manifest PWA)
Dockerfile
docker-compose.yaml
```

## Jalan lokal

```bash
cp .env.example .env      # isi LEMARI_DSN + LEMARI_DEV_USER
uvicorn app.main:app --reload --port 8000
```

## Deploy di VPS

```bash
cd /home/opsapp/apps/lemari
docker compose up -d --build
docker compose logs -f --tail=50 lemari
curl -s localhost/healthz   # dari container lain di proxy-net
```

- Tidak ada `ports:` — ingress lewat Caddy (`lemari.dipo.sh`), `/healthz` dibiarkan publik untuk Uptime Kuma.
- Rahasia ada di `.env` (mode 600), tidak pernah di-commit.

## Rencana fase

1. Fase 0 — infrastruktur: database, repo, healthz, SSO
2. Fase 1 — skema data, katalog item, upload foto, PWA installable
3. Fase 2 — catat pemakaian + cost per wear + auto-tag AI dari foto
4. Fase 3 — cuci sendiri & laundry (batch, biaya, pengingat)
5. Fase 4 — outfit, wishlist, pinjam-meminjam
6. Fase 5 — dashboard statistik
7. Fase 6 — bot Telegram (command, kirim foto, pengingat)

## Status

Fase 0 — kerangka aplikasi, healthz, dan koneksi database.

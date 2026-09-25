"""Bot Telegram Lemari (@dipo_housekeeper_bot).

Jalan sebagai container sendiri: long polling getUpdates, hanya menanggapi di topik Lemari
dan hanya dari user id di whitelist. Perintah bersifat baca; satu-satunya jalur tulis adalah
foto → usulan AI → tombol "Simpan ke katalog" (manusia yang memutuskan).

Satu token = satu consumer. Jangan jalankan proses lain yang polling token ini (409 Conflict).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import logika

log = logging.getLogger("lemari.bot")

TOKEN = os.environ.get("LEMARI_BOT_TOKEN") or os.environ.get("LEMARI_TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME = os.environ.get("LEMARI_BOT_USERNAME", "dipo_housekeeper_bot")
DOMAIN = os.environ.get("LEMARI_DOMAIN", "lemari.dipo.sh")
TOPIC_RAW = os.environ.get("LEMARI_TELEGRAM_TOPIC", "")
API_BASE = os.environ.get("LEMARI_API_URL", "http://lemari:8000")
BOT_USER = os.environ.get("LEMARI_BOT_USER", "dipo")
DATA_DIR = Path(os.environ.get("LEMARI_BOT_DATA", "/data"))
OFFSET_FILE = DATA_DIR / "bot-offset.json"
DRAFT_FILE = DATA_DIR / "bot-draft.json"


def _pasangan_topik() -> tuple[int, int | None]:
    """LEMARI_TELEGRAM_TOPIC = '<chat_id>:<thread_id>' (thread opsional)."""
    if ":" in TOPIC_RAW:
        chat, thread = TOPIC_RAW.split(":", 1)
        return int(chat), (int(thread) if thread.strip() else None)
    return int(TOPIC_RAW), None


CHAT_ID, THREAD_ID = _pasangan_topik()
ALLOWED = {int(x) for x in os.environ.get("LEMARI_TELEGRAM_ALLOWED_USER", "").replace(" ", "").split(",") if x.strip()}

TG = f"https://api.telegram.org/bot{TOKEN}"


# ---------------------------------------------------------------- simpan state kecil

def _baca_json(path: Path, bawaan: dict) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return bawaan


def _tulis_json(path: Path, isi: dict) -> None:
    """Tulis atomik: file sementara lalu os.replace (aman kalau proses mati di tengah)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(isi))
    os.replace(tmp, path)


# ---------------------------------------------------------------- klien HTTP

klien = httpx.Client(timeout=90)


def tg(method: str, **payload) -> dict:
    try:
        r = klien.post(f"{TG}/{method}", json=payload)
        return r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram %s gagal: %s", method, exc)
        return {"ok": False, "description": str(exc)}


def kirim(teks: str, tombol: list | None = None, balas_ke: int | None = None) -> dict:
    payload = {
        "chat_id": CHAT_ID,
        "text": teks[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if THREAD_ID is not None:
        payload["message_thread_id"] = THREAD_ID
    if tombol:
        payload["reply_markup"] = {"inline_keyboard": tombol}
    if balas_ke:
        payload["reply_to_message_id"] = balas_ke
    hasil = tg("sendMessage", **payload)
    if not hasil.get("ok"):
        log.warning("sendMessage ditolak: %s", hasil.get("description"))
    return hasil


HEADER_APP = {"X-Lemari-Bot": TOKEN, "Remote-User": BOT_USER}


def app_get(jalur: str, **param) -> dict:
    try:
        r = klien.get(f"{API_BASE}{jalur}", params=param, headers=HEADER_APP)
        if r.status_code != 200:
            log.warning("API %s -> %s", jalur, r.status_code)
            return {"ok": False, "pesan": f"server menjawab {r.status_code}"}
        return r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("API %s gagal: %s", jalur, exc)
        return {"ok": False, "pesan": "tidak bisa menghubungi aplikasi Lemari"}


def app_form(jalur: str, data: dict, berkas: dict | None = None) -> httpx.Response | None:
    try:
        return klien.post(f"{API_BASE}{jalur}", data=data, files=berkas, headers=HEADER_APP, follow_redirects=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("API %s gagal: %s", jalur, exc)
        return None


def unduh_foto(file_id: str) -> tuple[bytes, str] | None:
    info = tg("getFile", file_id=file_id)
    jalur = (info.get("result") or {}).get("file_path")
    if not jalur:
        return None
    url = f"https://api.telegram.org/file/bot{TOKEN}/{jalur}"
    try:
        r = klien.get(url)
        r.raise_for_status()
        mime = "image/png" if jalur.lower().endswith(".png") else "image/jpeg"
        return r.content, mime
    except Exception as exc:  # noqa: BLE001
        log.warning("unduh foto gagal: %s", exc)
        return None


# ---------------------------------------------------------------- alur foto → usulan

def _draft_baru(file_id: str, saran: dict) -> str:
    draft = _baca_json(DRAFT_FILE, {})
    nomor = str(max((int(k) for k in draft if k.isdigit()), default=0) + 1)
    draft[nomor] = {
        "file_id": file_id,
        "saran": saran,
        "dibuat": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # simpan hanya 20 draft terakhir
    for kunci in sorted((k for k in draft if k.isdigit()), key=int)[:-20]:
        draft.pop(kunci, None)
    _tulis_json(DRAFT_FILE, draft)
    return nomor


def tangani_foto(pesan: dict) -> None:
    foto = pesan.get("photo") or []
    if not foto:
        dokumen = pesan.get("document") or {}
        if not str(dokumen.get("mime_type", "")).startswith("image/"):
            return
        file_id = dokumen.get("file_id")
    else:
        file_id = foto[-1]["file_id"]  # ukuran paling besar

    kirim("Foto diterima, ade baca dulu isinya sebentar ya…", balas_ke=pesan["message_id"])

    bahan = unduh_foto(file_id)
    if not bahan:
        kirim("Fotonya gagal ade ambil dari Telegram. Coba kirim ulang ya kak.", balas_ke=pesan["message_id"])
        return
    isi, mime = bahan

    try:
        r = klien.post(
            f"{API_BASE}/api/tebak",
            files={"foto": ("foto.jpg", isi, mime)},
            headers=HEADER_APP,
            timeout=120,
        )
        hasil = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("tebak gagal: %s", exc)
        kirim("Pembacaan AI-nya gagal (server tidak menjawab). Coba lagi ya.", balas_ke=pesan["message_id"])
        return

    if not hasil.get("ok"):
        kirim(logika.esc(f"AI tidak bisa memberi usulan: {hasil.get('pesan', 'tidak diketahui')}"), balas_ke=pesan["message_id"])
        return

    saran = hasil["saran"]
    nomor = _draft_baru(file_id, saran)
    kirim(
        logika.pesan_usulan(saran),
        tombol=[
            [
                {"text": "✅ Simpan ke katalog", "callback_data": f"simpan:{nomor}"},
                {"text": "❌ Batal", "callback_data": f"batal:{nomor}"},
            ],
            [{"text": "✏️ Lengkapi lewat web", "url": f"https://{DOMAIN}/item/baru"}],
        ],
        balas_ke=pesan["message_id"],
    )


def tangani_tombol(tap: dict) -> None:
    data = tap.get("data", "")
    pesan_id = (tap.get("message") or {}).get("message_id")
    user_id = (tap.get("from") or {}).get("id")
    if not data or ":" not in data:
        tg("answerCallbackQuery", callback_query_id=tap["id"])
        return

    aksi, nomor = data.split(":", 1)
    draft = _baca_json(DRAFT_FILE, {})
    entri = draft.get(nomor)

    if not entri:
        tg("answerCallbackQuery", callback_query_id=tap["id"], text="Draft ini sudah tidak ada.", show_alert=True)
        return

    if aksi == "batal":
        draft.pop(nomor, None)
        _tulis_json(DRAFT_FILE, draft)
        tg("answerCallbackQuery", callback_query_id=tap["id"], text="Dibatalkan")
        kirim("Oke, tidak ade simpan. Kalau mau coba foto lain, kirim saja ya kak.")
        return

    if aksi != "simpan":
        tg("answerCallbackQuery", callback_query_id=tap["id"])
        return

    saran = entri.get("saran", {})
    bahan = unduh_foto(entri["file_id"])
    if not bahan:
        tg("answerCallbackQuery", callback_query_id=tap["id"], text="Fotonya gagal diambil ulang.", show_alert=True)
        return
    isi, mime = bahan

    form = {
        "nama": str(saran.get("nama") or "Barang tanpa nama"),
        "kategori_id": str(saran.get("kategori_id") or ""),
        "jenis": str(saran.get("jenis") or ""),
        "warna_utama": str(saran.get("warna_utama") or ""),
        "warna_sekunder": str(saran.get("warna_sekunder") or ""),
        "bahan": str(saran.get("bahan") or ""),
        "pola": str(saran.get("pola") or ""),
        "okasi": str(saran.get("okasi") or ""),
        "catatan": str(saran.get("catatan") or ""),
        "status": "bersih",
        "tags": "dari-bot",
    }
    jawab = app_form("/item", form, {"foto": ("foto.jpg", isi, mime)})
    if jawab is None or jawab.status_code not in (200, 303):
        tg("answerCallbackQuery", callback_query_id=tap["id"], text="Gagal menyimpan.", show_alert=True)
        kirim(f"Maaf kak, penyimpanannya gagal (server menjawab {getattr(jawab, 'status_code', 'tidak ada jawaban')}).")
        return

    lokasi = jawab.headers.get("location", "")
    item_id = lokasi.rstrip("/").rsplit("/", 1)[-1] if lokasi else "?"
    draft.pop(nomor, None)
    _tulis_json(DRAFT_FILE, draft)
    tg("answerCallbackQuery", callback_query_id=tap["id"], text="Tersimpan ✅")
    kirim(logika.pesan_tersimpan(form["nama"], item_id, DOMAIN))


# ---------------------------------------------------------------- command


def tangani_command(teks: str) -> None:
    potongan = teks.strip().split()
    perintah = potongan[0].lstrip("/").split("@")[0].lower()
    argumen = " ".join(potongan[1:]).strip()

    if perintah in ("start", "bantu", "help"):
        kirim(logika.pesan_bantuan(BOT_USERNAME))
        return

    if perintah == "ringkas":
        kirim(logika.pesan_ringkas(app_get("/api/bot/ringkas")))
        return
    if perintah == "stat":
        data = app_get("/api/bot/ringkas")
        kirim(logika.pesan_statistik(data))
        return
    if perintah == "kotor":
        kirim(logika.pesan_kotor(app_get("/api/bot/kotor"), DOMAIN))
        return
    if perintah == "cuci":
        kirim(logika.pesan_cuci(app_get("/api/bot/cuci"), DOMAIN))
        return
    if perintah == "pinjam":
        kirim(logika.pesan_pinjam(app_get("/api/bot/pinjam"), DOMAIN))
        return
    if perintah == "cari":
        if not argumen:
            kirim("Ade cari apa? Contoh: <code>/cari kaos hitam</code>")
            return
        kirim(logika.pesan_cari(app_get("/api/bot/cari", q=argumen)))
        return


# ---------------------------------------------------------------- loop utama

def layak_diproses(pesan: dict) -> bool:
    if pesan.get("chat", {}).get("id") != CHAT_ID:
        return False
    if THREAD_ID is not None and pesan.get("message_thread_id") != THREAD_ID:
        return False
    pengirim = pesan.get("from") or {}
    if pengirim.get("is_bot"):
        return False
    if ALLOWED and pengirim.get("id") not in ALLOWED:
        log.info("abaikan pesan dari user %s (tidak di whitelist)", pengirim.get("id"))
        return False
    return True


def tangani_update(update: dict) -> None:
    if "callback_query" in update:
        tap = update["callback_query"]
        pesan = tap.get("message") or {}
        if pesan.get("chat", {}).get("id") != CHAT_ID:
            tg("answerCallbackQuery", callback_query_id=tap["id"])
            return
        if THREAD_ID is not None and pesan.get("message_thread_id") not in (None, THREAD_ID):
            tg("answerCallbackQuery", callback_query_id=tap["id"])
            return
        pengirim = tap.get("from") or {}
        if pengirim.get("is_bot") or (ALLOWED and pengirim.get("id") not in ALLOWED):
            tg("answerCallbackQuery", callback_query_id=tap["id"], text="Tidak diizinkan.", show_alert=True)
            return
        tangani_tombol(tap)
        return

    pesan = update.get("message") or update.get("edited_message") or {}
    if not pesan or not layak_diproses(pesan):
        return

    teks = (pesan.get("text") or pesan.get("caption") or "").strip()

    # jangan menanggapi pesan yang dialamatkan ke bot lain (mis. /start@diposh_bot)
    sebutan = re.findall(r"@([A-Za-z0-9_]{4,})", teks)
    if sebutan and BOT_USERNAME not in sebutan:
        return

    if pesan.get("photo") or (pesan.get("document") or {}).get("mime_type", "").startswith("image/"):
        tangani_foto(pesan)
        return
    if teks.startswith("/"):
        tangani_command(teks)
        return
    # pesan bebas: jangan berisik, cukup diamkan (topik ini juga dipakai bot lain)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # URL permintaan memuat token; cukup peringatan saja
    if not TOKEN:
        raise SystemExit("LEMARI_BOT_TOKEN belum diatur")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    aku = tg("getMe").get("result") or {}
    log.info("bot jalan sebagai @%s (id %s) · topik %s:%s · whitelist %s",
             aku.get("username"), aku.get("id"), CHAT_ID, THREAD_ID, sorted(ALLOWED) or "semua")

    # banner hanya sekali per instalasi — restart jangan menambah pesan di topik
    penanda = DATA_DIR / "bot-siap.json"
    if not penanda.exists():
        kirim(
            "🧺 Bot Lemari sudah nyala.\n\n"
            "Kirim foto barang → ade baca isinya pakai AI → kakak tinggal tekan Simpan.\n"
            f"Ketik /bantu@{BOT_USERNAME} buat lihat daftar perintah."
        )
        _tulis_json(penanda, {"mulai": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    offset = int(_baca_json(OFFSET_FILE, {"offset": 0}).get("offset", 0))
    while True:
        try:
            r = klien.post(
                f"{TG}/getUpdates",
                json={"offset": offset, "timeout": 50, "allowed_updates": ["message", "callback_query"]},
                timeout=70,
            )
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("getUpdates gagal: %s", exc)
            time.sleep(5)
            continue

        if not data.get("ok"):
            log.warning("getUpdates ditolak: %s", data.get("description"))
            time.sleep(5)
            continue

        for update in data.get("result", []):
            baru = int(update["update_id"]) + 1
            if baru > offset:
                offset = baru  # offset hanya boleh maju, jangan pernah mundur ke 0
                _tulis_json(OFFSET_FILE, {"offset": offset})
            try:
                tangani_update(update)
            except Exception as exc:  # noqa: BLE001
                log.exception("update %s gagal diproses: %s", update.get("update_id"), exc)


if __name__ == "__main__":
    main()

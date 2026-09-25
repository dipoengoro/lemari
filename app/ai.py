"""Auto-tag dari foto pakai model vision OpenRouter — hanya usulan, manusia yang memutuskan."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import time

import httpx
from PIL import Image, ImageOps

from . import config

log = logging.getLogger("lemari.ai")

URL = "https://openrouter.ai/api/v1/chat/completions"
MAKS_PX = 1024          # foto dikecilkan dulu: lebih cepat, lebih murah, lebih jarang gagal
PERCOBAAN = 3

PROMPT = """Kamu membantu mencatat barang yang dipakai sehari-hari (pakaian, sepatu, tas, aksesoris, parfum).
Lihat foto ini dan isi atribut barang dalam bahasa Indonesia.

Balas HANYA objek JSON, tanpa penjelasan, dengan kunci:
nama (nama singkat barang, maksimal 6 kata, sertakan warna),
kategori (pilih SATU persis dari daftar: {kategoris}),
jenis (kata benda spesifik, mis. kemeja, celana chino, sneakers),
warna_utama (satu warna dominan),
warna_sekunder (warna lain yang terlihat, boleh kosong),
bahan (perkiraan bahan, mis. katun, denim, kulit — kosongkan kalau tidak yakin),
pola (polos, garis, kotak, bunga, atau kosong),
okasi (salah satu: kerja, santai, formal, olahraga, tidur, atau kosong),
catatan (satu kalimat pengamatan singkat),
yakin (true kalau foto jelas menampilkan satu barang, false kalau ragu)."""


class AiGagal(RuntimeError):
    """AI tidak bisa memberi usulan — pesannya ditampilkan apa adanya ke pengguna."""


def _siapkan_gambar(gambar: bytes, mime: str) -> tuple[bytes, str]:
    """Perkecil + betulkan orientasi supaya payload ringan."""
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(gambar))).convert("RGB")
        im.thumbnail((MAKS_PX, MAKS_PX))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        return gambar, mime  # biar AI yang menilai; kalau bukan gambar, akan gagal di sisi API


def _bersihkan_json(teks: str) -> dict:
    teks = teks.strip()
    teks = re.sub(r"^```(?:json)?|```$", "", teks, flags=re.MULTILINE).strip()
    cocok = re.search(r"\{.*\}", teks, re.DOTALL)
    if not cocok:
        raise AiGagal("Balasan AI tidak berbentuk data yang bisa dibaca.")
    try:
        return json.loads(cocok.group(0))
    except json.JSONDecodeError as exc:
        raise AiGagal(f"Balasan AI tidak bisa dibaca ({exc.msg}).") from exc


def _paskan_kategori(nama: str | None, daftar: list[str]) -> str | None:
    if not nama:
        return None
    n = nama.strip().lower()
    for k in daftar:
        if k.lower() == n:
            return k
    for k in daftar:
        if n and (n in k.lower() or k.lower() in n):
            return k
    return None


def tebak_atribut(gambar: bytes, daftar_kategori: list[str], mime: str = "image/jpeg") -> dict:
    """Kembalikan usulan atribut. Naikkan AiGagal kalau tidak tersedia/gagal (upload tetap jalan)."""
    if not config.AI_AKTIF:
        raise AiGagal("Fitur auto-tag sedang dimatikan (LEMARI_AI=0).")
    if not config.OPENROUTER_KEY:
        raise AiGagal("Kunci OpenRouter belum diset di server.")

    isi_gambar, mime_pakai = _siapkan_gambar(gambar, mime)
    payload = {
        "model": config.VISION_MODEL,
        "temperature": 0.2,
        "max_tokens": 700,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT.format(kategoris=", ".join(daftar_kategori))},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_pakai};base64," + base64.b64encode(isi_gambar).decode()},
                    },
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": f"https://{config.DOMAIN}",
        "X-Title": "Lemari",
    }

    pesan_terakhir = ""
    for ke in range(1, PERCOBAAN + 1):
        try:
            with httpx.Client(timeout=90) as klien:
                resp = klien.post(URL, json=payload, headers=headers)
            if resp.status_code == 200:
                isi = resp.json()["choices"][0]["message"].get("content") or ""
                log.info("auto-tag ok: %s KiB → %s", len(isi_gambar) // 1024, str(isi)[:120].replace("\n", " "))
                hasil = _bersihkan_json(isi)
                hasil["kategori"] = _paskan_kategori(hasil.get("kategori"), daftar_kategori)
                for kunci in ("nama", "jenis", "warna_utama", "warna_sekunder", "bahan", "pola", "okasi", "catatan"):
                    nilai = hasil.get(kunci)
                    hasil[kunci] = (str(nilai).strip() if nilai else "")[:140]
                hasil["yakin"] = bool(hasil.get("yakin", True))
                return hasil

            pesan_terakhir = f"OpenRouter membalas HTTP {resp.status_code}: {resp.text[:160]}"
            log.warning("auto-tag percobaan %s: %s", ke, pesan_terakhir)
        except AiGagal:
            raise
        except Exception as exc:  # noqa: BLE001
            pesan_terakhir = f"gagal menghubungi OpenRouter ({type(exc).__name__}: {str(exc)[:120]})"
            log.warning("auto-tag percobaan %s: %s", ke, pesan_terakhir)
        if ke < PERCOBAAN:
            time.sleep(1.5 * ke)

    raise AiGagal(pesan_terakhir or "AI tidak memberi jawaban.")

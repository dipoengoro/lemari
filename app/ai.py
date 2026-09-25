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

MAKS_PX = 1024          # foto dikecilkan dulu: lebih cepat, lebih murah, lebih jarang gagal
PERCOBAAN = 3


def _penyedia() -> dict:
    """Penyedia model vision: 'deepseek' (bawaan kalau kuncinya ada) atau 'openrouter'."""
    if config.AI_PROVIDER == "deepseek":
        return {
            "nama": "DeepSeek",
            "url": "https://api.deepseek.com/chat/completions",
            "kunci": config.DEEPSEEK_KEY,
            "headers": {},
            # model penalaran: token "berpikir" ikut dihitung (terukur sampai 1600), jadi jatahnya lega
            "max_tokens": 3000,
            "json_mode": True,
            "extra": {} if config.AI_THINKING else {"thinking": {"type": "disabled"}},
        }
    return {
        "nama": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "kunci": config.OPENROUTER_KEY,
        "headers": {"HTTP-Referer": f"https://{config.DOMAIN}", "X-Title": "Lemari"},
        "max_tokens": 700,
        "json_mode": False,
        "extra": {},
    }

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
    """Ambil objek JSON dari balasan model, walau dibungkus pagar kode atau ditempeli prosa."""
    teks = teks.strip()
    teks = re.sub(r"```(?:json)?", "", teks, flags=re.IGNORECASE).strip()
    awal, akhir = teks.find("{"), teks.rfind("}")
    if awal < 0 or akhir <= awal:
        raise AiGagal("Balasan AI tidak berbentuk data yang bisa dibaca.")
    calon = teks[awal : akhir + 1]
    try:
        return json.loads(calon)
    except json.JSONDecodeError:
        # kadang ada koma berlebih sebelum penutup (model bahasa Indonesia sering begitu)
        rapi = re.sub(r",\s*([}\]])", r"\1", calon)
        try:
            return json.loads(rapi)
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
    penyedia = _penyedia()
    if not penyedia["kunci"]:
        raise AiGagal(f"Kunci {penyedia['nama']} belum diset di server.")

    isi_gambar, mime_pakai = _siapkan_gambar(gambar, mime)
    payload = {
        "model": config.VISION_MODEL,
        "temperature": 0.2,
        "max_tokens": penyedia["max_tokens"],
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
    if penyedia["json_mode"]:
        payload["response_format"] = {"type": "json_object"}
    payload.update(penyedia.get("extra", {}))
    headers = {
        "Authorization": f"Bearer {penyedia['kunci']}",
        "Content-Type": "application/json",
        **penyedia["headers"],
    }

    pesan_terakhir = ""
    for ke in range(1, PERCOBAAN + 1):
        try:
            with httpx.Client(timeout=120) as klien:
                resp = klien.post(penyedia["url"], json=payload, headers=headers)

            if resp.status_code == 400 and "response_format" in payload and "response_format" in resp.text:
                # model tidak mendukung mode JSON wajib — ulangi tanpa itu
                log.warning("auto-tag: %s menolak response_format, dicoba tanpa itu", penyedia["nama"])
                payload.pop("response_format", None)
                continue

            if resp.status_code == 200:
                jawaban = resp.json()
                isi = jawaban["choices"][0]["message"].get("content") or ""
                log.info("auto-tag ok (%s/%s): %s KiB · usage=%s → %s",
                         penyedia["nama"], config.VISION_MODEL, len(isi_gambar) // 1024,
                         jawaban.get("usage"), str(isi)[:120].replace("\n", " "))
                try:
                    hasil = _bersihkan_json(isi)
                except AiGagal as exc:
                    # model kadang menjawab prosa tanpa JSON — itu kegagalan percobaan, bukan alasan menyerah
                    pesan_terakhir = str(exc)
                    log.warning("auto-tag percobaan %s: %s | balasan mentah: %s",
                                ke, exc, str(isi)[:300].replace("\n", " "))
                    if ke < PERCOBAAN:
                        time.sleep(1.5 * ke)
                    continue
                hasil["kategori"] = _paskan_kategori(hasil.get("kategori"), daftar_kategori)
                for kunci in ("nama", "jenis", "warna_utama", "warna_sekunder", "bahan", "pola", "okasi", "catatan"):
                    nilai = hasil.get(kunci)
                    hasil[kunci] = (str(nilai).strip() if nilai else "")[:140]
                hasil["yakin"] = bool(hasil.get("yakin", True))
                return hasil

            pesan_terakhir = f"{penyedia['nama']} membalas HTTP {resp.status_code}: {resp.text[:160]}"
            log.warning("auto-tag percobaan %s: %s", ke, pesan_terakhir)
        except AiGagal:
            raise
        except Exception as exc:  # noqa: BLE001
            pesan_terakhir = f"gagal menghubungi {penyedia['nama']} ({type(exc).__name__}: {str(exc)[:120]})"
            log.warning("auto-tag percobaan %s: %s", ke, pesan_terakhir)
        if ke < PERCOBAAN:
            time.sleep(1.5 * ke)

    raise AiGagal(pesan_terakhir or "AI tidak memberi jawaban.")

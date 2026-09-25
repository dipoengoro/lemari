"""Olah foto unggahan: EXIF rotate, resize, WebP + thumbnail, dedup sha256."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageOps

from . import config

WEBP_KUALITAS = 82


def _tujuan(sha: str, suffix: str = "") -> Path:
    folder = config.UPLOAD_DIR / sha[:2]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{sha}{suffix}.webp"


def simpan_foto(data: bytes) -> dict:
    """Simpan satu foto (bytes apa adanya dari upload) dan kembalikan metadata.

    Nama file = sha256 isi ASLI, jadi upload foto yang sama dua kali tidak menggandakan file.
    """
    sha = hashlib.sha256(data).hexdigest()
    penuh = _tujuan(sha)
    kecil = _tujuan(sha, "_thumb")

    if penuh.exists() and kecil.exists():
        with Image.open(penuh) as img:
            lebar, tinggi = img.size
        return {
            "sha256": sha,
            "path_relatif": penuh.relative_to(config.UPLOAD_DIR).as_posix(),
            "thumb_relatif": kecil.relative_to(config.UPLOAD_DIR).as_posix(),
            "lebar": lebar,
            "tinggi": tinggi,
            "baru": False,
        }

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        besar = img.copy()
        besar.thumbnail((config.MEDIA_MAX_PX, config.MEDIA_MAX_PX), Image.LANCZOS)
        lebar, tinggi = besar.size
        besar.save(penuh, "WEBP", quality=WEBP_KUALITAS, method=5)

        thumb = img.copy()
        thumb.thumbnail((config.THUMB_MAX_PX, config.THUMB_MAX_PX), Image.LANCZOS)
        thumb.save(kecil, "WEBP", quality=WEBP_KUALITAS, method=5)

    return {
        "sha256": sha,
        "path_relatif": penuh.relative_to(config.UPLOAD_DIR).as_posix(),
        "thumb_relatif": kecil.relative_to(config.UPLOAD_DIR).as_posix(),
        "lebar": lebar,
        "tinggi": tinggi,
        "baru": True,
    }

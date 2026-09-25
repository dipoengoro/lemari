"""API ringkas untuk bot Telegram (JSON, dipakai container `lemari-bot`).

Hanya baca — pembuatan item dan pencatatan pemakaian tetap lewat rute form yang sudah teruji
(`POST /item`, `POST /pakai`) supaya logika olah foto cuma ada satu tempat.
Diproteksi header `X-Lemari-Bot` yang nilainya = token bot (server-to-server, tidak lewat Caddy).
"""

from __future__ import annotations

from datetime import date as _tanggal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import config
from .db import get_session

router = APIRouter(prefix="/api/bot", tags=["bot"])


def _izin(x_lemari_bot: str | None = Header(default=None)) -> JSONResponse | None:
    if not config.TELEGRAM_BOT_TOKEN:
        return JSONResponse({"ok": False, "pesan": "token bot belum diatur di server"}, status_code=503)
    if x_lemari_bot != config.TELEGRAM_BOT_TOKEN:
        return JSONResponse({"ok": False, "pesan": "tidak diizinkan"}, status_code=403)
    return None


def _baris(session: Session, kueri: str, param: dict | None = None) -> list[dict]:
    hasil = session.execute(text(kueri), param or {}).mappings().all()
    return [dict(r) for r in hasil]


def _angka(nilai) -> float:
    return float(nilai or 0)


@router.get("/ringkas")
def ringkas(x_lemari_bot: str | None = Header(default=None), session: Session = Depends(get_session)):
    """Ringkasan angka untuk command /ringkas."""
    tolak = _izin(x_lemari_bot)
    if tolak:
        return tolak
    baris = _baris(
        session,
        """
        select (select count(*) from items)                                          as barang,
               (select coalesce(sum(harga_beli), 0) from items)                      as nilai,
               (select count(*) from items where status = 'kotor')                   as kotor,
               (select count(*) from items where status in ('dicuci', 'laundry'))    as sedang_dicuci,
               (select count(*) from wash_batches where selesai = false)             as batch_jalan,
               (select count(*) from wash_batches where selesai = false and jalur = 'laundry'
                  and estimasi_selesai is not null and estimasi_selesai < current_date) as laundry_lewat,
               (select count(*) from v_pinjaman_aktif)                               as pinjam_aktif,
               (select count(*) from v_pinjaman_aktif where lewat_hari > 0)          as pinjam_lewat,
               (select coalesce(sum(biaya), 0) from wash_batches where jalur = 'laundry' and selesai
                  and to_char(tanggal_mulai, 'YYYY-MM') = to_char(current_date, 'YYYY-MM')) as laundry_bulan_ini,
               (select count(*) from wear_log where tanggal = current_date)          as pakai_hari_ini,
               (select count(*) from wear_log where tanggal >= current_date - 30)    as pakai_30,
               (select coalesce(sum(perkiraan_harga), 0) from wishlist where status = 'ide') as wishlist,
               (select count(*) from items where harga_beli is null or harga_beli = 0) as tanpa_harga
        """,
    )[0]
    baris["nilai"] = _angka(baris["nilai"])
    baris["laundry_bulan_ini"] = _angka(baris["laundry_bulan_ini"])
    baris["wishlist"] = _angka(baris["wishlist"])
    return {"ok": True, "ringkas": baris}


@router.get("/kotor")
def kotor(limit: int = Query(25, ge=1, le=100), x_lemari_bot: str | None = Header(default=None),
          session: Session = Depends(get_session)):
    """Barang berstatus kotor (siap masuk batch cuci)."""
    tolak = _izin(x_lemari_bot)
    if tolak:
        return tolak
    baris = _baris(
        session,
        """
        select i.id, i.nama, coalesce(c.nama, '-') as kategori, coalesce(l.nama, '-') as lokasi
          from items i
          left join categories c on c.id = i.kategori_id
          left join locations l on l.id = i.lokasi_id
         where i.status = 'kotor'
         order by i.updated_at desc
         limit :limit
        """,
        {"limit": limit},
    )
    total = session.execute(text("select count(*) from items where status = 'kotor'")).scalar_one()
    return {"ok": True, "total": int(total), "barang": baris}


@router.get("/cuci")
def cuci(x_lemari_bot: str | None = Header(default=None), session: Session = Depends(get_session)):
    """Batch cuci yang masih berjalan + barang yang nyangkut tanpa batch."""
    tolak = _izin(x_lemari_bot)
    if tolak:
        return tolak
    batch = _baris(
        session,
        """
        select b.id, b.jalur, b.nama_laundry, b.tanggal_mulai, b.estimasi_selesai, b.biaya,
               (current_date - b.tanggal_mulai) as hari,
               coalesce(string_agg(i.nama, ', ' order by i.nama), '-') as barang,
               count(wi.item_id) as jumlah
          from wash_batches b
          left join wash_items wi on wi.batch_id = b.id
          left join items i on i.id = wi.item_id
         where b.selesai = false
         group by b.id
         order by b.id
        """,
    )
    for b in batch:
        b["lewat_estimasi"] = bool(b["estimasi_selesai"]) and b["estimasi_selesai"] < _tanggal.today()
        b["biaya"] = _angka(b["biaya"])
    nyangkut = _baris(
        session,
        """
        select i.id, i.nama, i.status
          from items i
         where i.status in ('dicuci', 'laundry')
           and not exists (select 1 from wash_items wi
                             join wash_batches wb on wb.id = wi.batch_id
                            where wi.item_id = i.id and wb.selesai = false)
         order by i.updated_at
         limit 25
        """,
    )
    return {"ok": True, "batch": batch, "nyangkut": nyangkut}


@router.get("/pinjam")
def pinjam(x_lemari_bot: str | None = Header(default=None), session: Session = Depends(get_session)):
    """Pinjaman yang belum kembali, dua arah, dengan hitungan lewat jatuh tempo."""
    tolak = _izin(x_lemari_bot)
    if tolak:
        return tolak
    baris = _baris(
        session,
        """
        select p.id, p.arah, p.nama_pihak, p.kontak, p.tanggal_pinjam, p.jatuh_tempo,
               coalesce(p.lewat_hari, 0) as lewat_hari, p.item_id, p.item_nama as barang, p.status_item
          from v_pinjaman_aktif p
         order by p.jatuh_tempo nulls last, p.id
        """,
    )
    return {"ok": True, "pinjaman": baris}


@router.get("/cari")
def cari(q: str = Query(min_length=1), limit: int = Query(10, ge=1, le=30),
         x_lemari_bot: str | None = Header(default=None), session: Session = Depends(get_session)):
    """Cari barang berdasarkan nama/jenis/warna/brand/tag."""
    tolak = _izin(x_lemari_bot)
    if tolak:
        return tolak
    baris = _baris(
        session,
        """
        select i.id, i.nama, i.status, coalesce(c.nama, '-') as kategori, coalesce(l.nama, '-') as lokasi,
               (select count(*) from wear_log w where w.item_id = i.id) as dipakai
          from items i
          left join categories c on c.id = i.kategori_id
          left join locations l on l.id = i.lokasi_id
         where i.nama ilike :pola
            or coalesce(i.jenis, '') ilike :pola
            or coalesce(i.warna_utama, '') ilike :pola
            or coalesce(i.brand, '') ilike :pola
            or exists (select 1 from item_tags it join tags t on t.id = it.tag_id
                        where it.item_id = i.id and t.nama ilike :pola)
         order by (i.nama ilike :awal) desc, i.nama
         limit :limit
        """,
        {"pola": f"%{q}%", "awal": f"{q}%", "limit": limit},
    )
    return {"ok": True, "kata": q, "jumlah": len(baris), "barang": baris}

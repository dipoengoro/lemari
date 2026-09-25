"""Halaman web Lemari (Fase 1): katalog, form item, foto, pengaturan taksonomi."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from . import ai, config, media
from .db import get_session
from .models import STATUS_ITEM, Category, Item, ItemPhoto, Location, Tag, WearLog

router = APIRouter()
templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))

PER_HALAMAN = 24


def _nama_dari_form(nama: str | None) -> str:
    return (nama or "").strip()[:140]


def _angka_dari_form(nilai: str | None) -> float | None:
    if not nilai:
        return None
    bersih = re.sub(r"[^0-9,.]", "", nilai).replace(".", "").replace(",", ".")
    try:
        return float(bersih)
    except ValueError:
        return None


def _tanggal_dari_form(nilai: str | None) -> date | None:
    if not nilai:
        return None
    try:
        return datetime.strptime(nilai, "%Y-%m-%d").date()
    except ValueError:
        return None


def _tag_ids(session: Session, teks: str | None) -> list[Tag]:
    """Ubah 'kerja, favorit' jadi objek Tag (bikin baru kalau belum ada)."""
    hasil: list[Tag] = []
    for nama in [t.strip() for t in (teks or "").split(",") if t.strip()]:
        nama = nama[:60]
        obj = session.scalar(select(Tag).where(func.lower(Tag.nama) == nama.lower()))
        if not obj:
            obj = Tag(nama=nama)
            session.add(obj)
            session.flush()
        hasil.append(obj)
    return hasil


def _filter_katalog(session: Session, q: str, kategori: str, lokasi: str, status: str, tag: str):
    stmt = select(Item).options(selectinload(Item.photos), selectinload(Item.kategori), selectinload(Item.lokasi))
    if q:
        pola = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Item.nama).like(pola),
                func.lower(func.coalesce(Item.brand, "")).like(pola),
                func.lower(func.coalesce(Item.warna_utama, "")).like(pola),
                func.lower(func.coalesce(Item.jenis, "")).like(pola),
                func.lower(func.coalesce(Item.okasi, "")).like(pola),
                func.lower(func.coalesce(Item.catatan, "")).like(pola),
            )
        )
    if kategori:
        stmt = stmt.where(Item.kategori_id == int(kategori))
    if lokasi:
        stmt = stmt.where(Item.lokasi_id == int(lokasi))
    if status:
        stmt = stmt.where(Item.status == status)
    if tag:
        stmt = stmt.where(Item.tags.any(func.lower(Tag.nama) == tag.lower()))
    return stmt


@router.get("/", response_class=HTMLResponse)
def katalog(
    request: Request,
    q: str = "",
    kategori: str = "",
    lokasi: str = "",
    status: str = "",
    tag: str = "",
    halaman: int = 1,
    session: Session = Depends(get_session),
):
    stmt = _filter_katalog(session, q, kategori, lokasi, status, tag)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    halaman = max(1, halaman)
    items = session.scalars(
        stmt.order_by(Item.updated_at.desc(), Item.id.desc())
        .offset((halaman - 1) * PER_HALAMAN)
        .limit(PER_HALAMAN)
    ).all()

    konteks = {
        "request": request,
        "user": request.state.user,
        "items": items,
        "total": total,
        "halaman": halaman,
        "per_halaman": PER_HALAMAN,
        "q": q,
        "f_kategori": kategori,
        "f_lokasi": lokasi,
        "f_status": status,
        "f_tag": tag,
        "kategoris": session.scalars(select(Category).order_by(Category.urutan, Category.nama)).all(),
        "lokasis": session.scalars(select(Location).order_by(Location.urutan, Location.nama)).all(),
        "tags": session.scalars(select(Tag).order_by(Tag.nama)).all(),
        "status_list": STATUS_ITEM,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "partials/katalog_isi.html", konteks)
    return templates.TemplateResponse(request, "katalog.html", konteks)


@router.get("/item/baru", response_class=HTMLResponse)
def form_baru(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "item_form.html",
        {
            "request": request,
            "item": None,
            "user": request.state.user,
            "kategoris": session.scalars(select(Category).order_by(Category.urutan, Category.nama)).all(),
            "lokasis": session.scalars(select(Location).order_by(Location.urutan, Location.nama)).all(),
            "status_list": STATUS_ITEM,
        },
    )


@router.post("/item")
async def simpan_baru(
    request: Request,
    nama: str = Form(...),
    kategori_id: str = Form(""),
    jenis: str = Form(""),
    warna_utama: str = Form(""),
    warna_sekunder: str = Form(""),
    bahan: str = Form(""),
    size: str = Form(""),
    brand: str = Form(""),
    pola: str = Form(""),
    okasi: str = Form(""),
    lokasi_id: str = Form(""),
    harga_beli: str = Form(""),
    tanggal_beli: str = Form(""),
    status: str = Form("bersih"),
    kondisi: str = Form(""),
    catatan: str = Form(""),
    tags: str = Form(""),
    foto: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
):
    item = Item(
        nama=_nama_dari_form(nama) or "Tanpa nama",
        kategori_id=int(kategori_id) if kategori_id else None,
        jenis=jenis.strip() or None,
        warna_utama=warna_utama.strip() or None,
        warna_sekunder=warna_sekunder.strip() or None,
        bahan=bahan.strip() or None,
        size=size.strip() or None,
        brand=brand.strip() or None,
        pola=pola.strip() or None,
        okasi=okasi.strip() or None,
        lokasi_id=int(lokasi_id) if lokasi_id else None,
        harga_beli=_angka_dari_form(harga_beli),
        tanggal_beli=_tanggal_dari_form(tanggal_beli),
        status=status if status in STATUS_ITEM else "bersih",
        kondisi=kondisi.strip() or None,
        catatan=catatan.strip() or None,
    )
    session.add(item)
    session.flush()
    item.tags = _tag_ids(session, tags)
    await _lampirkan_foto(session, item, foto)
    session.commit()
    return RedirectResponse(f"/item/{item.id}", status_code=303)


@router.get("/item/{item_id}", response_class=HTMLResponse)
def detail(request: Request, item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item tidak ditemukan")
    return templates.TemplateResponse(
        request,
        "item_detail.html",
        {
            "request": request,
            "item": item,
            "user": request.state.user,
            "stat": statistik_item(session, item.id),
            "pemakaian": sorted(item.pemakaian, key=lambda w: (w.tanggal, w.id), reverse=True)[:30],
        },
    )


@router.get("/item/{item_id}/edit", response_class=HTMLResponse)
def form_edit(request: Request, item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item tidak ditemukan")
    return templates.TemplateResponse(
        request,
        "item_form.html",
        {
            "request": request,
            "item": item,
            "user": request.state.user,
            "kategoris": session.scalars(select(Category).order_by(Category.urutan, Category.nama)).all(),
            "lokasis": session.scalars(select(Location).order_by(Location.urutan, Location.nama)).all(),
            "status_list": STATUS_ITEM,
        },
    )


@router.post("/item/{item_id}")
async def simpan_edit(
    request: Request,
    item_id: int,
    nama: str = Form(...),
    kategori_id: str = Form(""),
    jenis: str = Form(""),
    warna_utama: str = Form(""),
    warna_sekunder: str = Form(""),
    bahan: str = Form(""),
    size: str = Form(""),
    brand: str = Form(""),
    pola: str = Form(""),
    okasi: str = Form(""),
    lokasi_id: str = Form(""),
    harga_beli: str = Form(""),
    tanggal_beli: str = Form(""),
    status: str = Form("bersih"),
    kondisi: str = Form(""),
    catatan: str = Form(""),
    tags: str = Form(""),
    foto: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item tidak ditemukan")
    item.nama = _nama_dari_form(nama) or item.nama
    item.kategori_id = int(kategori_id) if kategori_id else None
    item.jenis = jenis.strip() or None
    item.warna_utama = warna_utama.strip() or None
    item.warna_sekunder = warna_sekunder.strip() or None
    item.bahan = bahan.strip() or None
    item.size = size.strip() or None
    item.brand = brand.strip() or None
    item.pola = pola.strip() or None
    item.okasi = okasi.strip() or None
    item.lokasi_id = int(lokasi_id) if lokasi_id else None
    item.harga_beli = _angka_dari_form(harga_beli)
    item.tanggal_beli = _tanggal_dari_form(tanggal_beli)
    item.status = status if status in STATUS_ITEM else item.status
    item.kondisi = kondisi.strip() or None
    item.catatan = catatan.strip() or None
    item.tags = _tag_ids(session, tags)
    await _lampirkan_foto(session, item, foto)
    session.commit()
    return RedirectResponse(f"/item/{item.id}", status_code=303)


@router.post("/item/{item_id}/hapus")
def hapus_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if item:
        session.delete(item)
        session.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/item/{item_id}/foto")
async def tambah_foto(
    item_id: int,
    foto: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item tidak ditemukan")
    await _lampirkan_foto(session, item, foto)
    session.commit()
    return RedirectResponse(f"/item/{item.id}", status_code=303)


@router.post("/foto/{photo_id}/utama")
def jadikan_utama(photo_id: int, session: Session = Depends(get_session)):
    foto = session.get(ItemPhoto, photo_id)
    if not foto:
        raise HTTPException(404, "Foto tidak ditemukan")
    for lain in foto.item.photos:
        lain.is_primary = lain.id == foto.id
    session.commit()
    return RedirectResponse(f"/item/{foto.item_id}", status_code=303)


@router.post("/foto/{photo_id}/hapus")
def hapus_foto(photo_id: int, session: Session = Depends(get_session)):
    foto = session.get(ItemPhoto, photo_id)
    if not foto:
        raise HTTPException(404, "Foto tidak ditemukan")
    item_id = foto.item_id
    session.delete(foto)
    session.commit()
    return RedirectResponse(f"/item/{item_id}", status_code=303)


@router.post("/items/bulk")
def aksi_massal(
    item_ids: list[str] = Form(default=[]),
    aksi_status: str = Form(""),
    aksi_lokasi: str = Form(""),
    aksi_tag: str = Form(""),
    session: Session = Depends(get_session),
):
    ids = [int(i) for i in item_ids if i.isdigit()]
    if ids:
        items = session.scalars(select(Item).where(Item.id.in_(ids))).all()
        for item in items:
            if aksi_status in STATUS_ITEM:
                item.status = aksi_status
            if aksi_lokasi:
                item.lokasi_id = int(aksi_lokasi)
            if aksi_tag:
                tambahan = _tag_ids(session, aksi_tag)
                ada = {t.nama.lower() for t in item.tags}
                item.tags.extend([t for t in tambahan if t.nama.lower() not in ada])
        session.commit()
    return RedirectResponse("/", status_code=303)


@router.get("/pengaturan", response_class=HTMLResponse)
def pengaturan(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "pengaturan.html",
        {
            "request": request,
            "user": request.state.user,
            "kategoris": session.scalars(select(Category).order_by(Category.grup, Category.urutan, Category.nama)).all(),
            "lokasis": session.scalars(select(Location).order_by(Location.urutan, Location.nama)).all(),
            "tags": session.scalars(select(Tag).order_by(Tag.nama)).all(),
            "jumlah_item": session.scalar(select(func.count()).select_from(Item)) or 0,
        },
    )


@router.post("/pengaturan/kategori")
def tambah_kategori(nama: str = Form(...), grup: str = Form("Lain-lain"), session: Session = Depends(get_session)):
    nama = nama.strip()[:80]
    if nama and not session.scalar(select(Category).where(func.lower(Category.nama) == nama.lower())):
        urutan = (session.scalar(select(func.max(Category.urutan))) or 0) + 1
        session.add(Category(nama=nama, grup=(grup.strip() or "Lain-lain")[:40], urutan=urutan))
        session.commit()
    return RedirectResponse("/pengaturan", status_code=303)


@router.post("/pengaturan/lokasi")
def tambah_lokasi(nama: str = Form(...), session: Session = Depends(get_session)):
    nama = nama.strip()[:80]
    if nama and not session.scalar(select(Location).where(func.lower(Location.nama) == nama.lower())):
        urutan = (session.scalar(select(func.max(Location.urutan))) or 0) + 1
        session.add(Location(nama=nama, urutan=urutan))
        session.commit()
    return RedirectResponse("/pengaturan", status_code=303)


@router.post("/pengaturan/hapus")
def hapus_taksonomi(jenis: str = Form(...), id_: int = Form(..., alias="id"), session: Session = Depends(get_session)):
    model = {"kategori": Category, "lokasi": Location, "tag": Tag}.get(jenis)
    if model:
        obj = session.get(model, id_)
        if obj and not getattr(obj, "is_default", False):
            session.delete(obj)
            session.commit()
    return RedirectResponse("/pengaturan", status_code=303)


def statistik_item(session: Session, item_id: int) -> dict:
    """Ambil angka pakai dari view v_cost_per_wear (sekali query, aman walau nol pemakaian)."""
    baris = session.execute(
        text(
            "select jumlah_pakai, terakhir_pakai, cost_per_wear, harga_beli "
            "from v_cost_per_wear where item_id = :i"
        ),
        {"i": item_id},
    ).fetchone()
    if not baris:
        return {"jumlah_pakai": 0, "terakhir_pakai": None, "cost_per_wear": None, "harga_beli": None}
    return {
        "jumlah_pakai": baris[0] or 0,
        "terakhir_pakai": baris[1],
        "cost_per_wear": float(baris[2]) if baris[2] is not None else None,
        "harga_beli": float(baris[3]) if baris[3] is not None else None,
    }


@router.get("/pakai", response_class=HTMLResponse)
def halaman_pakai(
    request: Request,
    q: str = "",
    tanggal: str = "",
    session: Session = Depends(get_session),
):
    """Pilih item yang dipakai (hanya yang siap dipakai: bersih / belum dicuci)."""
    stmt = (
        select(Item)
        .options(selectinload(Item.photos), selectinload(Item.kategori))
        .where(Item.status.in_(["bersih", "disimpan"]))
        .order_by(Item.updated_at.desc())
    )
    if q:
        pola = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Item.nama).like(pola), func.lower(func.coalesce(Item.brand, "")).like(pola))
        )
    items = session.scalars(stmt.limit(200)).all()
    hari = _tanggal_dari_form(tanggal) or date.today()
    dipakai_hari_ini = session.scalars(
        select(WearLog)
        .options(selectinload(WearLog.item))
        .where(WearLog.tanggal == hari)
        .order_by(WearLog.id.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "pakai.html",
        {
            "request": request,
            "user": request.state.user,
            "items": items,
            "q": q,
            "tanggal": hari.isoformat(),
            "sudah_dipakai": dipakai_hari_ini,
        },
    )


@router.post("/pakai")
def simpan_pakai(
    item_ids: list[str] = Form(default=[]),
    tanggal: str = Form(""),
    okasi: str = Form(""),
    cuaca: str = Form(""),
    catatan: str = Form(""),
    jadi_kotor: str = Form(""),
    session: Session = Depends(get_session),
):
    hari = _tanggal_dari_form(tanggal) or date.today()
    ids = [int(i) for i in item_ids if i.isdigit()]
    for item_id in ids:
        item = session.get(Item, item_id)
        if not item:
            continue
        session.add(
            WearLog(
                tanggal=hari,
                item_id=item.id,
                okasi=okasi.strip() or item.okasi,
                cuaca=cuaca.strip() or None,
                catatan=catatan.strip() or None,
            )
        )
        if jadi_kotor:
            item.status = "kotor"
    session.commit()
    return RedirectResponse(f"/pakai?tanggal={hari.isoformat()}", status_code=303)


@router.post("/pakai/{wear_id}/hapus")
def hapus_pakai(wear_id: int, session: Session = Depends(get_session)):
    baris = session.get(WearLog, wear_id)
    tujuan = "/riwayat"
    if baris:
        if baris.item_id:
            tujuan = f"/item/{baris.item_id}"
        session.delete(baris)
        session.commit()
    return RedirectResponse(tujuan, status_code=303)


@router.get("/riwayat", response_class=HTMLResponse)
def riwayat(request: Request, hari: int = 60, session: Session = Depends(get_session)):
    batas = date.today().toordinal() - hari
    baris = session.scalars(
        select(WearLog)
        .options(selectinload(WearLog.item))
        .where(WearLog.tanggal >= date.fromordinal(batas))
        .order_by(WearLog.tanggal.desc(), WearLog.id.desc())
    ).all()
    per_hari: dict[date, list[WearLog]] = {}
    for b in baris:
        per_hari.setdefault(b.tanggal, []).append(b)
    return templates.TemplateResponse(
        request,
        "riwayat.html",
        {"request": request, "user": request.state.user, "per_hari": per_hari, "hari": hari},
    )


@router.post("/api/tebak")
async def api_tebak(foto: UploadFile = File(...), session: Session = Depends(get_session)):
    """Usulan atribut dari foto (dipakai tombol 'isi otomatis' di form). Tidak pernah menyimpan item."""
    data = await foto.read()
    if not data:
        return {"ok": False, "pesan": "foto kosong"}
    daftar = session.scalars(select(Category.nama).order_by(Category.urutan)).all()
    try:
        saran = ai.tebak_atribut(data, list(daftar), mime=foto.content_type or "image/jpeg")
    except ai.AiGagal as exc:
        return {"ok": False, "pesan": str(exc)}
    saran["kategori_id"] = None
    if saran.get("kategori"):
        obj = session.scalar(select(Category).where(Category.nama == saran["kategori"]))
        saran["kategori_id"] = obj.id if obj else None
    return {"ok": True, "saran": saran}


@router.get("/media/{jalur:path}")
def ambil_media(jalur: str):
    """Sajikan foto dari folder uploads (tetap di balik SSO karena lewat app)."""
    target = (config.UPLOAD_DIR / jalur).resolve()
    if not str(target).startswith(str(config.UPLOAD_DIR.resolve())) or not target.is_file():
        raise HTTPException(404, "Tidak ada")
    return FileResponse(target, media_type="image/webp")


async def _lampirkan_foto(session: Session, item: Item, berkas: list[UploadFile]) -> None:
    urutan = max([p.urutan for p in item.photos], default=-1)
    baru = False
    for unggahan in berkas or []:
        if not unggahan or not unggahan.filename:
            continue
        data = await unggahan.read()
        if not data:
            continue
        try:
            info = media.simpan_foto(data)
        except Exception:  # noqa: BLE001 — file bukan gambar / rusak
            continue
        urutan += 1
        foto = ItemPhoto(
            item_id=item.id,
            path_relatif=info["path_relatif"],
            thumb_relatif=info["thumb_relatif"],
            lebar=info["lebar"],
            tinggi=info["tinggi"],
            sha256=info["sha256"],
            urutan=urutan,
        )
        session.add(foto)
        session.flush()
        if not baru and not any(p.is_primary for p in item.photos):
            foto.is_primary = True
        baru = True

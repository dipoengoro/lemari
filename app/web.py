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
from .models import (
    STATUS_ITEM,
    Category,
    Item,
    ItemPhoto,
    Loan,
    Location,
    Outfit,
    OutfitItem,
    Tag,
    WashBatch,
    WashItem,
    WearLog,
    WishlistItem,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))
templates.env.globals["version"] = config.VERSION  # dipakai footer di semua halaman

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
def form_baru(
    request: Request,
    nama: str = "",
    kategori_id: str = "",
    harga_beli: str = "",
    jenis: str = "",
    catatan: str = "",
    session: Session = Depends(get_session),
):
    """Prefill dari query (dipakai tombol "+ ke katalog" di wishlist)."""
    praf = {"nama": nama, "kategori_id": kategori_id, "harga_beli": harga_beli, "jenis": jenis, "catatan": catatan}
    return templates.TemplateResponse(
        request,
        "item_form.html",
        {
            "request": request,
            "item": None,
            "user": request.state.user,
            "praf": praf,
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
            "cuci_berjalan": next((wi for wi in item.riwayat_cuci if not wi.batch.selesai), None),
            "riwayat_cuci": item.riwayat_cuci[:10],
            "pinjaman_aktif": next((p for p in item.pinjaman if p.aktif), None),
            "riwayat_pinjam": item.pinjaman[:10],
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
            "praf": {},
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


# ---------- Fase 3: cuci sendiri & laundry ----------

JALUR_CUCI = ("sendiri", "laundry")
STATUS_SELESAI_CUCI = {"sendiri": "dicuci", "laundry": "laundry"}


def _batch_berjalan(session: Session) -> list[WashBatch]:
    return list(
        session.scalars(
            select(WashBatch)
            .options(selectinload(WashBatch.isi).selectinload(WashItem.item))
            .where(WashBatch.selesai.is_(False))
            .order_by(WashBatch.tanggal_mulai, WashBatch.id)
        ).all()
    )


@router.get("/cuci", response_class=HTMLResponse)
def halaman_cuci(request: Request, session: Session = Depends(get_session)):
    berjalan = _batch_berjalan(session)
    selesai = session.scalars(
        select(WashBatch)
        .options(selectinload(WashBatch.isi).selectinload(WashItem.item))
        .where(WashBatch.selesai.is_(True))
        .order_by(WashBatch.tanggal_selesai.desc().nullslast(), WashBatch.id.desc())
        .limit(15)
    ).all()
    rekap = session.execute(
        text("select bulan, jumlah_batch, jumlah_item, total_biaya, biaya_per_item from v_laundry_bulanan limit 6")
    ).fetchall()

    # barang yang statusnya di cuci/laundry tapi tidak terhubung batch berjalan (data nyangkut)
    nyangkut = session.scalars(
        select(Item)
        .options(selectinload(Item.photos))
        .where(Item.status.in_(tuple(STATUS_SELESAI_CUCI.values())))
        .where(
            ~Item.id.in_(
                select(WashItem.item_id)
                .join(WashBatch, WashBatch.id == WashItem.batch_id)
                .where(WashBatch.selesai.is_(False))
            )
        )
        .order_by(Item.updated_at)
    ).all()

    return templates.TemplateResponse(
        request,
        "cuci.html",
        {
            "request": request,
            "user": request.state.user,
            "berjalan": berjalan,
            "selesai": selesai,
            "rekap": rekap,
            "nyangkut": nyangkut,
            "hari_ini": date.today(),
        },
    )


@router.get("/cuci/baru", response_class=HTMLResponse)
def form_cuci(
    request: Request,
    item_id: str = "",
    jalur: str = "sendiri",
    semua: str = "",
    session: Session = Depends(get_session),
):
    """Pilih jalur + barang yang mau dicuci. Default hanya barang berstatus kotor."""
    status_ambil = ["kotor"] if not semua else ["kotor", "bersih", "disimpan"]
    items = session.scalars(
        select(Item)
        .options(selectinload(Item.photos), selectinload(Item.kategori))
        .where(Item.status.in_(status_ambil))
        .order_by(Item.updated_at.desc())
        .limit(300)
    ).all()
    terpilih = {int(x) for x in item_id.replace(" ", "").split(",") if x.isdigit()}
    return templates.TemplateResponse(
        request,
        "cuci_form.html",
        {
            "request": request,
            "user": request.state.user,
            "items": items,
            "terpilih": terpilih,
            "jalur": jalur if jalur in JALUR_CUCI else "sendiri",
            "semua": bool(semua),
            "hari_ini": date.today(),
        },
    )


@router.post("/cuci/baru")
def simpan_cuci(
    jalur: str = Form("sendiri"),
    item_ids: list[str] = Form(default=[]),
    tanggal_mulai: str = Form(""),
    estimasi_selesai: str = Form(""),
    nama_laundry: str = Form(""),
    layanan: str = Form(""),
    no_nota: str = Form(""),
    biaya: str = Form(""),
    catatan_kondisi: str = Form(""),
    catatan: str = Form(""),
    session: Session = Depends(get_session),
):
    jalur = jalur if jalur in JALUR_CUCI else "sendiri"
    ids = [int(i) for i in item_ids if i.isdigit()]
    if not ids:
        return RedirectResponse("/cuci/baru?kosong=1", status_code=303)

    batch = WashBatch(
        jalur=jalur,
        nama_laundry=nama_laundry.strip() or None,
        layanan=layanan.strip() or None,
        no_nota=no_nota.strip() or None,
        tanggal_mulai=_tanggal_dari_form(tanggal_mulai) or date.today(),
        estimasi_selesai=_tanggal_dari_form(estimasi_selesai),
        biaya=_angka_dari_form(biaya),
        catatan_kondisi=catatan_kondisi.strip() or None,
        catatan=catatan.strip() or None,
        selesai=False,
    )
    session.add(batch)
    session.flush()

    status_baru = STATUS_SELESAI_CUCI[jalur]
    for item_id in ids:
        item = session.get(Item, item_id)
        if not item:
            continue
        session.add(
            WashItem(batch_id=batch.id, item_id=item.id, status_sebelum=item.status or "kotor")
        )
        item.status = status_baru
    session.commit()
    return RedirectResponse("/cuci", status_code=303)


@router.get("/cuci/{batch_id}/tambah", response_class=HTMLResponse)
def form_tambah_ke_batch(batch_id: int, request: Request, q: str = "", session: Session = Depends(get_session)):
    """Halaman pemilih barang untuk ditambahkan ke batch yang sedang jalan."""
    batch = session.scalars(
        select(WashBatch).options(selectinload(WashBatch.isi)).where(WashBatch.id == batch_id)
    ).first()
    if not batch or batch.selesai:
        raise HTTPException(404, "Batch tidak ditemukan atau sudah selesai")
    sudah = {wi.item_id for wi in batch.isi}
    stmt = (
        select(Item)
        .options(selectinload(Item.photos))
        .where(Item.status.in_(("kotor", "bersih", "disimpan")))
        .order_by(Item.updated_at.desc())
        .limit(300)
    )
    if q:
        stmt = stmt.where(func.lower(Item.nama).like(f"%{q.lower()}%"))
    items = [i for i in session.scalars(stmt).all() if i.id not in sudah]
    return templates.TemplateResponse(
        request,
        "cuci_tambah.html",
        {"request": request, "user": request.state.user, "batch": batch, "items": items, "q": q},
    )


@router.post("/cuci/{batch_id}/item/tambah")
def tambah_item_cuci(
    batch_id: int,
    item_ids: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
):
    batch = session.get(WashBatch, batch_id)
    if not batch or batch.selesai:
        raise HTTPException(404, "Batch tidak ditemukan atau sudah selesai")
    sudah = {wi.item_id for wi in batch.isi}
    for mentah in item_ids:
        if not mentah.isdigit():
            continue
        item = session.get(Item, int(mentah))
        if not item or item.id in sudah:
            continue
        session.add(
            WashItem(batch_id=batch.id, item_id=item.id, status_sebelum=item.status or "kotor")
        )
        item.status = STATUS_SELESAI_CUCI.get(batch.jalur, "dicuci")
    session.commit()
    return RedirectResponse("/cuci", status_code=303)


@router.post("/cuci/{batch_id}/item/{wash_item_id}/hapus")
def hapus_item_cuci(batch_id: int, wash_item_id: int, session: Session = Depends(get_session)):
    baris = session.get(WashItem, wash_item_id)
    if baris and baris.batch_id == batch_id:
        item = session.get(Item, baris.item_id)
        if item and baris.status_sebelum:
            item.status = baris.status_sebelum
        session.delete(baris)
        session.commit()
    return RedirectResponse("/cuci", status_code=303)


@router.post("/cuci/{batch_id}/selesai")
def selesai_cuci(
    batch_id: int,
    tanggal_selesai: str = Form(""),
    biaya: str = Form(""),
    catatan_kondisi: str = Form(""),
    kembali_bersih: str = Form("1"),
    session: Session = Depends(get_session),
):
    batch = session.get(WashBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch tidak ditemukan")
    batch.selesai = True
    batch.tanggal_selesai = _tanggal_dari_form(tanggal_selesai) or date.today()
    nilai_biaya = _angka_dari_form(biaya)
    if nilai_biaya is not None:
        batch.biaya = nilai_biaya
    if catatan_kondisi.strip():
        batch.catatan_kondisi = catatan_kondisi.strip()
    if kembali_bersih:
        for wi in batch.isi:
            item = session.get(Item, wi.item_id)
            if item:
                item.status = "bersih"
    session.commit()
    return RedirectResponse("/cuci", status_code=303)


@router.post("/cuci/{batch_id}/batal")
def batal_cuci(batch_id: int, session: Session = Depends(get_session)):
    batch = session.get(WashBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch tidak ditemukan")
    for wi in batch.isi:
        item = session.get(Item, wi.item_id)
        if item and wi.status_sebelum:
            item.status = wi.status_sebelum
    session.delete(batch)
    session.commit()
    return RedirectResponse("/cuci", status_code=303)


# ---------- Fase 4: outfit, wishlist, pinjam-meminjam ----------

ARAH_PINJAM = ("keluar", "masuk")
PRIORITAS_WISHLIST = {1: "pengen banget", 2: "tertarik", 3: "cuma lihat"}


def _item_untuk_pilih(session: Session, limit: int = 300) -> list[Item]:
    return list(
        session.scalars(
            select(Item)
            .options(selectinload(Item.photos), selectinload(Item.kategori))
            .order_by(Item.updated_at.desc())
            .limit(limit)
        ).all()
    )


@router.get("/outfit", response_class=HTMLResponse)
def halaman_outfit(request: Request, session: Session = Depends(get_session)):
    outfits = session.scalars(
        select(Outfit)
        .options(selectinload(Outfit.isi).selectinload(OutfitItem.item).selectinload(Item.photos))
        .order_by(Outfit.updated_at.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "outfit.html",
        {"request": request, "user": request.state.user, "outfits": outfits, "hari_ini": date.today()},
    )


@router.get("/outfit/baru", response_class=HTMLResponse)
def form_outfit(request: Request, item_id: str = "", session: Session = Depends(get_session)):
    terpilih = {int(x) for x in item_id.replace(" ", "").split(",") if x.isdigit()}
    return templates.TemplateResponse(
        request,
        "outfit_form.html",
        {
            "request": request,
            "user": request.state.user,
            "outfit": None,
            "items": _item_untuk_pilih(session),
            "terpilih": terpilih,
        },
    )


@router.get("/outfit/{outfit_id}/edit", response_class=HTMLResponse)
def form_outfit_edit(outfit_id: int, request: Request, session: Session = Depends(get_session)):
    outfit = session.scalars(
        select(Outfit)
        .options(selectinload(Outfit.isi).selectinload(OutfitItem.item).selectinload(Item.photos))
        .where(Outfit.id == outfit_id)
    ).first()
    if not outfit:
        raise HTTPException(404, "Outfit tidak ditemukan")
    terpilih = {bagian.item_id for bagian in outfit.isi}
    items = _item_untuk_pilih(session)
    # barang yang sudah ada di outfit harus tetap muncul walau di luar 300 terbaru
    ada = {i.id for i in items}
    tambahan = [bagian.item for bagian in outfit.isi if bagian.item_id not in ada]
    return templates.TemplateResponse(
        request,
        "outfit_form.html",
        {
            "request": request,
            "user": request.state.user,
            "outfit": outfit,
            "items": tambahan + items,
            "terpilih": terpilih,
        },
    )


@router.post("/outfit")
def simpan_outfit(
    nama: str = Form(""),
    okasi: str = Form(""),
    catatan: str = Form(""),
    item_ids: list[str] = Form(default=[]),
    outfit_id: str = Form(""),
    session: Session = Depends(get_session),
):
    nama_bersih = _nama_dari_form(nama)
    if outfit_id.isdigit():
        outfit = session.get(Outfit, int(outfit_id))
        if not outfit:
            raise HTTPException(404, "Outfit tidak ditemukan")
        outfit.nama = nama_bersih or outfit.nama
        outfit.okasi = okasi.strip() or None
        outfit.catatan = catatan.strip() or None
        for bagian in list(outfit.isi):
            session.delete(bagian)
        session.flush()
    else:
        outfit = Outfit(nama=nama_bersih or "Outfit tanpa nama", okasi=okasi.strip() or None,
                        catatan=catatan.strip() or None)
        session.add(outfit)
        session.flush()

    for urutan, mentah in enumerate(item_ids):
        if not mentah.isdigit():
            continue
        if not session.get(Item, int(mentah)):
            continue
        session.add(OutfitItem(outfit_id=outfit.id, item_id=int(mentah), urutan=urutan))
    session.commit()
    return RedirectResponse("/outfit", status_code=303)


@router.post("/outfit/{outfit_id}/pakai")
def pakai_outfit(
    outfit_id: int,
    tanggal: str = Form(""),
    jadi_kotor: str = Form(""),
    session: Session = Depends(get_session),
):
    """Catat pemakaian: tiap barang di outfit dapat baris wear_log sendiri."""
    outfit = session.scalars(select(Outfit).options(selectinload(Outfit.isi)).where(Outfit.id == outfit_id)).first()
    if not outfit:
        raise HTTPException(404, "Outfit tidak ditemukan")
    hari = _tanggal_dari_form(tanggal) or date.today()
    for bagian in outfit.isi:
        item = session.get(Item, bagian.item_id)
        if not item:
            continue
        session.add(WearLog(tanggal=hari, item_id=item.id, okasi=outfit.okasi, catatan=f"outfit {outfit.nama}"))
        if jadi_kotor:
            item.status = "kotor"
    session.commit()
    return RedirectResponse(f"/pakai?tanggal={hari.isoformat()}", status_code=303)


@router.post("/outfit/{outfit_id}/hapus")
def hapus_outfit(outfit_id: int, session: Session = Depends(get_session)):
    outfit = session.get(Outfit, outfit_id)
    if outfit:
        session.delete(outfit)
        session.commit()
    return RedirectResponse("/outfit", status_code=303)


@router.get("/wishlist", response_class=HTMLResponse)
def halaman_wishlist(request: Request, session: Session = Depends(get_session)):
    ide = session.scalars(
        select(WishlistItem)
        .options(selectinload(WishlistItem.kategori))
        .where(WishlistItem.status == "ide")
        .order_by(WishlistItem.prioritas, WishlistItem.created_at.desc())
    ).all()
    selesai = session.scalars(
        select(WishlistItem)
        .options(selectinload(WishlistItem.kategori))
        .where(WishlistItem.status != "ide")
        .order_by(WishlistItem.tanggal_dibeli.desc().nullslast(), WishlistItem.id.desc())
        .limit(20)
    ).all()
    total = sum(float(x.perkiraan_harga) for x in ide if x.perkiraan_harga)
    return templates.TemplateResponse(
        request,
        "wishlist.html",
        {
            "request": request,
            "user": request.state.user,
            "ide": ide,
            "selesai": selesai,
            "kategoris": session.scalars(select(Category).order_by(Category.urutan)).all(),
            "total_perkiraan": total,
            "prioritas_label": PRIORITAS_WISHLIST,
        },
    )


@router.post("/wishlist")
def simpan_wishlist(
    nama: str = Form(""),
    kategori_id: str = Form(""),
    perkiraan_harga: str = Form(""),
    link: str = Form(""),
    prioritas: str = Form("2"),
    catatan: str = Form(""),
    session: Session = Depends(get_session),
):
    item = WishlistItem(
        nama=_nama_dari_form(nama) or "Tanpa nama",
        kategori_id=int(kategori_id) if kategori_id.isdigit() else None,
        perkiraan_harga=_angka_dari_form(perkiraan_harga),
        link=link.strip() or None,
        prioritas=int(prioritas) if prioritas.isdigit() and int(prioritas) in PRIORITAS_WISHLIST else 2,
        catatan=catatan.strip() or None,
    )
    session.add(item)
    session.commit()
    return RedirectResponse("/wishlist", status_code=303)


@router.post("/wishlist/{wish_id}/status")
def ubah_status_wishlist(wish_id: int, status: str = Form("dibeli"), session: Session = Depends(get_session)):
    baris = session.get(WishlistItem, wish_id)
    if baris:
        baris.status = status if status in ("ide", "dibeli", "batal") else "ide"
        baris.tanggal_dibeli = date.today() if baris.status == "dibeli" else None
        session.commit()
    return RedirectResponse("/wishlist", status_code=303)


@router.post("/wishlist/{wish_id}/hapus")
def hapus_wishlist(wish_id: int, session: Session = Depends(get_session)):
    baris = session.get(WishlistItem, wish_id)
    if baris:
        session.delete(baris)
        session.commit()
    return RedirectResponse("/wishlist", status_code=303)


@router.get("/pinjam", response_class=HTMLResponse)
def halaman_pinjam(request: Request, session: Session = Depends(get_session)):
    pinjaman = session.scalars(
        select(Loan).options(selectinload(Loan.item).selectinload(Item.photos)).order_by(Loan.id.desc()).limit(200)
    ).all()
    aktif = [p for p in pinjaman if p.aktif]
    selesai = [p for p in pinjaman if not p.aktif][:20]
    return templates.TemplateResponse(
        request,
        "pinjam.html",
        {
            "request": request,
            "user": request.state.user,
            "keluar": [p for p in aktif if p.arah == "keluar"],
            "masuk": [p for p in aktif if p.arah == "masuk"],
            "selesai": selesai,
            "hari_ini": date.today(),
        },
    )


@router.get("/pinjam/baru", response_class=HTMLResponse)
def form_pinjam(request: Request, item_id: str = "", arah: str = "keluar", session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "pinjam_form.html",
        {
            "request": request,
            "user": request.state.user,
            "items": _item_untuk_pilih(session),
            "terpilih": int(item_id) if item_id.isdigit() else None,
            "arah": arah if arah in ARAH_PINJAM else "keluar",
            "hari_ini": date.today(),
        },
    )


@router.post("/pinjam")
def simpan_pinjam(
    arah: str = Form("keluar"),
    nama_pihak: str = Form(""),
    kontak: str = Form(""),
    item_id: str = Form(""),
    tanggal_pinjam: str = Form(""),
    jatuh_tempo: str = Form(""),
    catatan: str = Form(""),
    session: Session = Depends(get_session),
):
    arah = arah if arah in ARAH_PINJAM else "keluar"
    if not item_id.isdigit() or not session.get(Item, int(item_id)):
        return RedirectResponse("/pinjam/baru?kosong=1", status_code=303)
    item = session.get(Item, int(item_id))
    pinjaman = Loan(
        arah=arah,
        nama_pihak=_nama_dari_form(nama_pihak) or ("Tanpa nama" if arah == "keluar" else "Diri sendiri"),
        kontak=kontak.strip() or None,
        item_id=item.id,
        status_sebelum=item.status or "bersih",
        tanggal_pinjam=_tanggal_dari_form(tanggal_pinjam) or date.today(),
        jatuh_tempo=_tanggal_dari_form(jatuh_tempo),
        catatan=catatan.strip() or None,
    )
    session.add(pinjaman)
    item.status = "dipinjamkan"
    session.commit()
    return RedirectResponse("/pinjam", status_code=303)


@router.post("/pinjam/{loan_id}/kembali")
def kembali_pinjam(loan_id: int, tanggal_kembali: str = Form(""), session: Session = Depends(get_session)):
    pinjaman = session.get(Loan, loan_id)
    if not pinjaman:
        raise HTTPException(404, "Catatan pinjaman tidak ditemukan")
    pinjaman.tanggal_kembali = _tanggal_dari_form(tanggal_kembali) or date.today()
    item = session.get(Item, pinjaman.item_id)
    if item:
        item.status = pinjaman.status_sebelum or "bersih"
    session.commit()
    return RedirectResponse("/pinjam", status_code=303)


@router.post("/pinjam/{loan_id}/hapus")
def hapus_pinjam(loan_id: int, session: Session = Depends(get_session)):
    pinjaman = session.get(Loan, loan_id)
    if pinjaman:
        if pinjaman.aktif:
            item = session.get(Item, pinjaman.item_id)
            if item and pinjaman.status_sebelum:
                item.status = pinjaman.status_sebelum
        session.delete(pinjaman)
        session.commit()
    return RedirectResponse("/pinjam", status_code=303)


# ---------- Fase 5: statistik ----------


def _baris(session: Session, kueri: str, param: dict | None = None) -> list:
    return list(session.execute(text(kueri), param or {}).fetchall())


def _persen(daftar: list, ambil_idx: int = 1) -> list[tuple]:
    """Ubah daftar baris jadi (baris, persen 0-100) untuk lebar bar di template."""
    if not daftar:
        return []
    nilai_maks = max((float(b[ambil_idx] or 0) for b in daftar), default=0) or 1
    return [(b, round(float(b[ambil_idx] or 0) / nilai_maks * 100)) for b in daftar]


@router.get("/statistik", response_class=HTMLResponse)
def halaman_statistik(request: Request, session: Session = Depends(get_session)):
    ringkas = _baris(
        session,
        """
        select (select count(*) from items)                                        as jumlah_item,
               (select coalesce(sum(harga_beli), 0) from items)                     as nilai,
               (select count(*) from items where harga_beli is not null)            as ada_harga,
               (select count(*) from item_photos)                                   as jumlah_foto,
               (select count(*) from wear_log)                                      as total_pakai,
               (select count(*) from wear_log where tanggal >= current_date - 30)   as pakai_30,
               (select count(*) from outfits)                                       as jumlah_outfit,
               (select coalesce(sum(perkiraan_harga), 0) from wishlist where status = 'ide') as nilai_wishlist,
               (select count(*) from wash_batches where selesai = false)             as cuci_berjalan,
               (select coalesce(sum(biaya), 0) from wash_batches
                 where jalur = 'laundry' and selesai = true
                   and to_char(tanggal_mulai, 'YYYY-MM') = to_char(current_date, 'YYYY-MM')) as laundry_bulan_ini
        """,
    )[0]

    per_status = _persen(_baris(session, "select status, count(*) from items group by status order by 2 desc"))
    per_kategori = _persen(
        _baris(
            session,
            """
            select coalesce(c.nama, '(tanpa kategori)') as nama, count(*) as jumlah
              from items i left join categories c on c.id = i.kategori_id
             group by 1 order by 2 desc limit 12
            """,
        )
    )
    per_lokasi = _persen(
        _baris(
            session,
            """
            select coalesce(l.nama, '(belum ditentukan)') as nama, count(*) as jumlah
              from items i left join locations l on l.id = i.lokasi_id
             group by 1 order by 2 desc limit 12
            """,
        )
    )
    cpw_mahal = _baris(
        session,
        """
        select nama, jumlah_pakai, harga_beli, cost_per_wear
          from v_cost_per_wear
         where jumlah_pakai > 0 and cost_per_wear is not null
         order by cost_per_wear desc limit 8
        """,
    )
    cpw_murah = _baris(
        session,
        """
        select nama, jumlah_pakai, harga_beli, cost_per_wear
          from v_cost_per_wear
         where jumlah_pakai > 0 and cost_per_wear is not null
         order by cost_per_wear asc limit 8
        """,
    )
    sering_dipakai = _persen(
        _baris(
            session,
            """
            select i.nama, count(*) as kali
              from wear_log w join items i on i.id = w.item_id
             group by 1 order by 2 desc limit 10
            """,
        )
    )
    nganggur = _baris(
        session,
        """
        select i.nama, i.status,
               (select max(w.tanggal) from wear_log w where w.item_id = i.id)          as terakhir,
               (select count(*) from wear_log w where w.item_id = i.id)                as kali,
               coalesce(i.tanggal_beli, i.created_at::date)                            as masuk
          from items i
         where not exists (select 1 from wear_log w
                            where w.item_id = i.id and w.tanggal >= current_date - 90)
         order by terakhir nulls first, masuk
         limit 15
        """,
    )
    tren_belanja = _persen(
        _baris(
            session,
            """
            select to_char(date_trunc('month', coalesce(tanggal_beli, created_at::date)), 'YYYY-MM') as bulan,
                   count(*) as jumlah,
                   coalesce(sum(harga_beli), 0) as nilai
              from items
             where coalesce(tanggal_beli, created_at::date) >= (date_trunc('month', current_date) - interval '11 months')
             group by 1 order by 1
            """,
        ),
        ambil_idx=1,
    )
    laundry = _baris(
        session,
        "select bulan, jumlah_batch, jumlah_item, total_biaya, biaya_per_item from v_laundry_bulanan limit 6",
    )

    return templates.TemplateResponse(
        request,
        "statistik.html",
        {
            "request": request,
            "user": request.state.user,
            "ringkas": ringkas,
            "per_status": per_status,
            "per_kategori": per_kategori,
            "per_lokasi": per_lokasi,
            "cpw_mahal": cpw_mahal,
            "cpw_murah": cpw_murah,
            "sering_dipakai": sering_dipakai,
            "nganggur": nganggur,
            "tren_belanja": tren_belanja,
            "laundry": laundry,
            "hari_ini": date.today(),
        },
    )


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

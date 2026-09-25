"""Model SQLAlchemy untuk Lemari.

Fase 1 mengisi bagian katalog: kategori, lokasi, item, foto, tag.
Tabel fase berikutnya (wear_log, wash_*, outfits, loans, wishlist) menyusul di migrasi terpisah.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# status yang dikenal (dipakai di filter & badge)
STATUS_ITEM = ["bersih", "kotor", "dicuci", "laundry", "dipinjamkan", "disimpan"]

item_tags = Table(
    "item_tags",
    Base.metadata,
    Column("item_id", ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(80), unique=True)
    grup: Mapped[str] = mapped_column(String(40), default="Lain-lain")
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[list["Item"]] = relationship(back_populates="kategori")

    def __str__(self) -> str:  # pragma: no cover - bantu template
        return self.nama


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(80), unique=True)
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[list["Item"]] = relationship(back_populates="lokasi")

    def __str__(self) -> str:  # pragma: no cover
        return self.nama


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(60), unique=True)

    items: Mapped[list["Item"]] = relationship(secondary=item_tags, back_populates="tags")

    def __str__(self) -> str:  # pragma: no cover
        return self.nama


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(140))
    kategori_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    jenis: Mapped[str | None] = mapped_column(String(60))
    warna_utama: Mapped[str | None] = mapped_column(String(40))
    warna_sekunder: Mapped[str | None] = mapped_column(String(160))
    bahan: Mapped[str | None] = mapped_column(String(80))
    size: Mapped[str | None] = mapped_column(String(40))
    brand: Mapped[str | None] = mapped_column(String(80))
    pola: Mapped[str | None] = mapped_column(String(60))
    okasi: Mapped[str | None] = mapped_column(String(60))
    lokasi_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    harga_beli: Mapped[float | None] = mapped_column(Numeric(12, 2))
    tanggal_beli: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="bersih")
    kondisi: Mapped[str | None] = mapped_column(String(40))
    catatan: Mapped[str | None] = mapped_column(Text)
    ai_tagged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    kategori: Mapped[Category | None] = relationship(back_populates="items")
    lokasi: Mapped[Location | None] = relationship(back_populates="items")
    photos: Mapped[list["ItemPhoto"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="ItemPhoto.urutan, ItemPhoto.id"
    )
    tags: Mapped[list[Tag]] = relationship(secondary=item_tags, back_populates="items")
    riwayat_cuci: Mapped[list["WashItem"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="WashItem.id.desc()"
    )
    pemakaian: Mapped[list["WearLog"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="WearLog.tanggal.desc()"
    )
    outfit_parts: Mapped[list["OutfitItem"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    pinjaman: Mapped[list["Loan"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="Loan.id.desc()"
    )

    __table_args__ = (Index("ix_items_status_kategori", "status", "kategori_id"),)

    @property
    def foto_utama(self) -> "ItemPhoto | None":
        for p in self.photos:
            if p.is_primary:
                return p
        return self.photos[0] if self.photos else None


class WearLog(Base):
    """Satu baris = satu item dipakai pada satu tanggal (pakai outfit menulis baris per item)."""

    __tablename__ = "wear_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    tanggal: Mapped[date] = mapped_column(Date)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    outfit_id: Mapped[int | None] = mapped_column(Integer)
    okasi: Mapped[str | None] = mapped_column(String(60))
    cuaca: Mapped[str | None] = mapped_column(String(40))
    catatan: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped[Item | None] = relationship(back_populates="pemakaian")

    __table_args__ = (
        Index("ix_wear_log_item_tanggal", "item_id", "tanggal"),
        Index("ix_wear_log_tanggal", "tanggal"),
    )


class WashBatch(Base):
    """Satu batch cuci sendiri atau satu setoran laundry."""

    __tablename__ = "wash_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    jalur: Mapped[str] = mapped_column(String(20), default="sendiri")  # sendiri | laundry
    nama_laundry: Mapped[str | None] = mapped_column(String(80))
    layanan: Mapped[str | None] = mapped_column(String(60))
    no_nota: Mapped[str | None] = mapped_column(String(60))
    tanggal_mulai: Mapped[date] = mapped_column(Date)
    estimasi_selesai: Mapped[date | None] = mapped_column(Date)
    tanggal_selesai: Mapped[date | None] = mapped_column(Date)
    biaya: Mapped[float | None] = mapped_column(Numeric(12, 2))
    catatan_kondisi: Mapped[str | None] = mapped_column(Text)
    catatan: Mapped[str | None] = mapped_column(Text)
    selesai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    isi: Mapped[list["WashItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="WashItem.id"
    )

    __table_args__ = (Index("ix_wash_batches_selesai_mulai", "selesai", "tanggal_mulai"),)

    @property
    def jumlah_item(self) -> int:
        return len(self.isi)

    @property
    def biaya_per_item(self) -> float | None:
        if self.biaya and self.jumlah_item:
            return float(self.biaya) / self.jumlah_item
        return None

    @property
    def lewat_estimasi(self) -> bool:
        """Laundry yang seharusnya sudah diambil tapi belum ditandai selesai."""
        if self.selesai or not self.estimasi_selesai:
            return False
        return self.estimasi_selesai < date.today()


class WashItem(Base):
    """Satu barang di dalam satu batch cuci."""

    __tablename__ = "wash_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("wash_batches.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    status_sebelum: Mapped[str | None] = mapped_column(String(20))
    catatan: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    batch: Mapped[WashBatch] = relationship(back_populates="isi")
    item: Mapped["Item"] = relationship(back_populates="riwayat_cuci")

    __table_args__ = (
        UniqueConstraint("batch_id", "item_id", name="uq_wash_items_batch_item"),
        Index("ix_wash_items_batch", "batch_id"),
        Index("ix_wash_items_item", "item_id"),
    )


class Outfit(Base):
    """Set pakaian yang sering dipakai bareng."""

    __tablename__ = "outfits"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(80))
    okasi: Mapped[str | None] = mapped_column(String(60))
    catatan: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    isi: Mapped[list["OutfitItem"]] = relationship(
        back_populates="outfit", cascade="all, delete-orphan", order_by="OutfitItem.urutan, OutfitItem.id"
    )

    @property
    def jumlah_item(self) -> int:
        return len(self.isi)

    @property
    def foto_utama(self) -> ItemPhoto | None:
        """Foto barang pertama yang punya foto — buat thumbnail kartu outfit."""
        for bagian in self.isi:
            if bagian.item and bagian.item.photos:
                return bagian.item.photos[0]
        return None


class OutfitItem(Base):
    __tablename__ = "outfit_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    outfit_id: Mapped[int] = mapped_column(ForeignKey("outfits.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    outfit: Mapped[Outfit] = relationship(back_populates="isi")
    item: Mapped["Item"] = relationship(back_populates="outfit_parts")

    __table_args__ = (
        UniqueConstraint("outfit_id", "item_id", name="uq_outfit_items"),
        Index("ix_outfit_items_outfit", "outfit_id"),
    )


class WishlistItem(Base):
    """Rencana beli — belum tentu jadi item."""

    __tablename__ = "wishlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(120))
    kategori_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    perkiraan_harga: Mapped[float | None] = mapped_column(Numeric(12, 2))
    link: Mapped[str | None] = mapped_column(Text)
    prioritas: Mapped[int] = mapped_column(Integer, default=2)
    catatan: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ide")  # ide | dibeli | batal
    tanggal_dibeli: Mapped[date | None] = mapped_column(Date)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    kategori: Mapped["Category | None"] = relationship()
    item: Mapped["Item | None"] = relationship()

    __table_args__ = (Index("ix_wishlist_status_prioritas", "status", "prioritas"),)


class Loan(Base):
    """Pinjam-meminjam dua arah: keluar (dipinjamkan) atau masuk (ade yang meminjam)."""

    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    arah: Mapped[str] = mapped_column(String(10), default="keluar")
    nama_pihak: Mapped[str] = mapped_column(String(80))
    kontak: Mapped[str | None] = mapped_column(String(80))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    status_sebelum: Mapped[str | None] = mapped_column(String(20))
    tanggal_pinjam: Mapped[date] = mapped_column(Date)
    jatuh_tempo: Mapped[date | None] = mapped_column(Date)
    tanggal_kembali: Mapped[date | None] = mapped_column(Date)
    catatan: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped["Item"] = relationship(back_populates="pinjaman")

    __table_args__ = (
        Index("ix_loans_aktif", "tanggal_kembali", "jatuh_tempo"),
        Index("ix_loans_item", "item_id"),
    )

    @property
    def aktif(self) -> bool:
        return self.tanggal_kembali is None

    @property
    def lewat_tempo(self) -> bool:
        return self.aktif and self.jatuh_tempo is not None and self.jatuh_tempo < date.today()

    @property
    def lewat_hari(self) -> int:
        if not self.lewat_tempo or not self.jatuh_tempo:
            return 0
        return (date.today() - self.jatuh_tempo).days


class ItemPhoto(Base):
    __tablename__ = "item_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    path_relatif: Mapped[str] = mapped_column(String(200))
    thumb_relatif: Mapped[str] = mapped_column(String(200))
    lebar: Mapped[int] = mapped_column(Integer, default=0)
    tinggi: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped[Item] = relationship(back_populates="photos")

    __table_args__ = (Index("ix_item_photos_item", "item_id"),)

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
    pemakaian: Mapped[list["WearLog"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="WearLog.tanggal.desc()"
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

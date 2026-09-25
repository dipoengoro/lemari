"""Skema awal Lemari: katalog (kategori, lokasi, item, foto, tag) + seed taksonomi.

Revision ID: 0001_katalog
Revises:
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_katalog"
down_revision = None
branch_labels = None
depends_on = None

KATEGORI_DEFAULT = [
    ("Atasan", "Pakaian"),
    ("Bawahan", "Pakaian"),
    ("Dress & One-piece", "Pakaian"),
    ("Outer", "Pakaian"),
    ("Setelan", "Pakaian"),
    ("Dalaman", "Pakaian"),
    ("Olahraga", "Pakaian"),
    ("Sepatu", "Kaki"),
    ("Sandal", "Kaki"),
    ("Kaos kaki", "Kaki"),
    ("Tas", "Bawa"),
    ("Dompet", "Bawa"),
    ("Koper", "Bawa"),
    ("Sabuk", "Bawa"),
    ("Topi", "Bawa"),
    ("Syal", "Bawa"),
    ("Jam", "Aksesoris"),
    ("Perhiasan", "Aksesoris"),
    ("Kacamata", "Aksesoris"),
    ("Parfum", "Wewangian & perawatan"),
    ("Deodoran", "Wewangian & perawatan"),
    ("Produk rambut", "Wewangian & perawatan"),
    ("Lain-lain", "Lain-lain"),
]

LOKASI_DEFAULT = [
    "Lemari utama",
    "Lemari kedua",
    "Gantungan pintu",
    "Rak sepatu",
    "Kotak simpanan",
    "Tas travel",
    "Di laundry",
    "Di tempat orang (dipinjamkan)",
    "Belum dirapikan",
]


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(80), nullable=False, unique=True),
        sa.Column("grup", sa.String(40), nullable=False, server_default="Lain-lain"),
        sa.Column("urutan", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(80), nullable=False, unique=True),
        sa.Column("urutan", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(60), nullable=False, unique=True),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(140), nullable=False),
        sa.Column("kategori_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("jenis", sa.String(60)),
        sa.Column("warna_utama", sa.String(40)),
        sa.Column("warna_sekunder", sa.String(160)),
        sa.Column("bahan", sa.String(80)),
        sa.Column("size", sa.String(40)),
        sa.Column("brand", sa.String(80)),
        sa.Column("pola", sa.String(60)),
        sa.Column("okasi", sa.String(60)),
        sa.Column("lokasi_id", sa.Integer, sa.ForeignKey("locations.id", ondelete="SET NULL")),
        sa.Column("harga_beli", sa.Numeric(12, 2)),
        sa.Column("tanggal_beli", sa.Date),
        sa.Column("status", sa.String(20), nullable=False, server_default="bersih"),
        sa.Column("kondisi", sa.String(40)),
        sa.Column("catatan", sa.Text),
        sa.Column("ai_tagged", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_items_status_kategori", "items", ["status", "kategori_id"])

    op.create_table(
        "item_photos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path_relatif", sa.String(200), nullable=False),
        sa.Column("thumb_relatif", sa.String(200), nullable=False),
        sa.Column("lebar", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tinggi", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("urutan", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_item_photos_item", "item_photos", ["item_id"])

    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Integer, sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )

    kategori_tbl = sa.table(
        "categories",
        sa.column("nama", sa.String),
        sa.column("grup", sa.String),
        sa.column("urutan", sa.Integer),
        sa.column("is_default", sa.Boolean),
    )
    lokasi_tbl = sa.table(
        "locations",
        sa.column("nama", sa.String),
        sa.column("urutan", sa.Integer),
        sa.column("is_default", sa.Boolean),
    )
    op.bulk_insert(
        kategori_tbl,
        [{"nama": n, "grup": g, "urutan": i, "is_default": True} for i, (n, g) in enumerate(KATEGORI_DEFAULT)],
    )
    op.bulk_insert(
        lokasi_tbl,
        [{"nama": n, "urutan": i, "is_default": True} for i, n in enumerate(LOKASI_DEFAULT)],
    )


def downgrade() -> None:
    op.drop_table("item_tags")
    op.drop_index("ix_item_photos_item", table_name="item_photos")
    op.drop_table("item_photos")
    op.drop_index("ix_items_status_kategori", table_name="items")
    op.drop_table("items")
    op.drop_table("tags")
    op.drop_table("locations")
    op.drop_table("categories")

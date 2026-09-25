"""Fase 4: outfit, wishlist, pinjam-meminjam dua arah.

Revision ID: 0004_outfit_pinjam
Revises: 0003_cuci
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_outfit_pinjam"
down_revision = "0003_cuci"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outfits",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(80), nullable=False),
        sa.Column("okasi", sa.String(60)),
        sa.Column("catatan", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "outfit_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("outfit_id", sa.Integer, sa.ForeignKey("outfits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("urutan", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("outfit_id", "item_id", name="uq_outfit_items"),
    )
    op.create_index("ix_outfit_items_outfit", "outfit_items", ["outfit_id"])

    op.create_table(
        "wishlist",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(120), nullable=False),
        sa.Column("kategori_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("perkiraan_harga", sa.Numeric(12, 2)),
        sa.Column("link", sa.Text),
        sa.Column("prioritas", sa.Integer, server_default="2", nullable=False),
        sa.Column("catatan", sa.Text),
        sa.Column("status", sa.String(20), server_default="ide", nullable=False),  # ide | dibeli | batal
        sa.Column("tanggal_dibeli", sa.Date),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_wishlist_status_prioritas", "wishlist", ["status", "prioritas"])

    op.create_table(
        "loans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("arah", sa.String(10), nullable=False),  # keluar = dipinjamkan, masuk = ade yang pinjam
        sa.Column("nama_pihak", sa.String(80), nullable=False),
        sa.Column("kontak", sa.String(80)),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status_sebelum", sa.String(20)),
        sa.Column("tanggal_pinjam", sa.Date, nullable=False),
        sa.Column("jatuh_tempo", sa.Date),
        sa.Column("tanggal_kembali", sa.Date),
        sa.Column("catatan", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_loans_aktif", "loans", ["tanggal_kembali", "jatuh_tempo"])
    op.create_index("ix_loans_item", "loans", ["item_id"])

    op.execute(
        """
        create view v_pinjaman_aktif as
        select l.id, l.arah, l.nama_pihak, l.kontak, l.tanggal_pinjam, l.jatuh_tempo,
               l.item_id, i.nama as item_nama, i.status as status_item,
               case when l.jatuh_tempo is not null and l.jatuh_tempo < current_date
                    then current_date - l.jatuh_tempo
               end as lewat_hari
          from loans l
          join items i on i.id = l.item_id
         where l.tanggal_kembali is null
         order by l.jatuh_tempo nulls last, l.tanggal_pinjam
        """
    )


def downgrade() -> None:
    op.execute("drop view if exists v_pinjaman_aktif")
    op.drop_index("ix_loans_item", table_name="loans")
    op.drop_index("ix_loans_aktif", table_name="loans")
    op.drop_table("loans")
    op.drop_index("ix_wishlist_status_prioritas", table_name="wishlist")
    op.drop_table("wishlist")
    op.drop_index("ix_outfit_items_outfit", table_name="outfit_items")
    op.drop_table("outfit_items")
    op.drop_table("outfits")

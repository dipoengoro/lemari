"""Fase 3: batch cuci sendiri / laundry.

Revision ID: 0003_cuci
Revises: 0002_pemakaian
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_cuci"
down_revision = "0002_pemakaian"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wash_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("jalur", sa.String(20), nullable=False),  # sendiri | laundry
        sa.Column("nama_laundry", sa.String(80)),
        sa.Column("layanan", sa.String(60)),  # cuci kering, setrika, express, dll
        sa.Column("no_nota", sa.String(60)),
        sa.Column("tanggal_mulai", sa.Date, nullable=False),
        sa.Column("estimasi_selesai", sa.Date),
        sa.Column("tanggal_selesai", sa.Date),
        sa.Column("biaya", sa.Numeric(12, 2)),
        sa.Column("catatan_kondisi", sa.Text),
        sa.Column("catatan", sa.Text),
        sa.Column("selesai", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "wash_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("wash_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status_sebelum", sa.String(20)),  # dipulihkan kalau batch dibatalkan
        sa.Column("catatan", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("batch_id", "item_id", name="uq_wash_items_batch_item"),
    )
    op.create_index("ix_wash_items_batch", "wash_items", ["batch_id"])
    op.create_index("ix_wash_items_item", "wash_items", ["item_id"])
    op.create_index("ix_wash_batches_selesai_mulai", "wash_batches", ["selesai", "tanggal_mulai"])

    op.execute(
        """
        create view v_laundry_bulanan as
        with per_batch as (
            select b.id,
                   to_char(b.tanggal_mulai, 'YYYY-MM') as bulan,
                   coalesce(b.biaya, 0)                as biaya,
                   (select count(*) from wash_items wi where wi.batch_id = b.id) as jumlah_item
              from wash_batches b
             where b.jalur = 'laundry'
        )
        select bulan,
               count(*)                                                  as jumlah_batch,
               sum(jumlah_item)                                          as jumlah_item,
               sum(biaya)                                                as total_biaya,
               case when sum(jumlah_item) > 0
                    then round(sum(biaya) / sum(jumlah_item), 2)
                    else 0
               end                                                       as biaya_per_item
          from per_batch
         group by bulan
         order by bulan desc
        """
    )


def downgrade() -> None:
    op.execute("drop view if exists v_laundry_bulanan")
    op.drop_index("ix_wash_batches_selesai_mulai", table_name="wash_batches")
    op.drop_index("ix_wash_items_item", table_name="wash_items")
    op.drop_index("ix_wash_items_batch", table_name="wash_items")
    op.drop_table("wash_items")
    op.drop_table("wash_batches")

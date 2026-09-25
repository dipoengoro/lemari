"""Fase 2: catatan pemakaian (wear_log) + view cost per wear.

Revision ID: 0002_pemakaian
Revises: 0001_katalog
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_pemakaian"
down_revision = "0001_katalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wear_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tanggal", sa.Date, nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=True),
        # outfit_id menyusul di Fase 4 (tabel `outfits` belum ada) — sengaja tanpa FK dulu
        sa.Column("outfit_id", sa.Integer, nullable=True),
        sa.Column("okasi", sa.String(60)),
        sa.Column("cuaca", sa.String(40)),
        sa.Column("catatan", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_wear_log_item_tanggal", "wear_log", ["item_id", "tanggal"])
    op.create_index("ix_wear_log_tanggal", "wear_log", ["tanggal"])
    op.create_index("ix_wear_log_outfit", "wear_log", ["outfit_id"])

    op.execute(
        """
        create view v_cost_per_wear as
        select i.id                                             as item_id,
               i.nama                                           as nama,
               i.harga_beli                                     as harga_beli,
               count(w.id)                                      as jumlah_pakai,
               max(w.tanggal)                                   as terakhir_pakai,
               case when count(w.id) > 0 and i.harga_beli is not null
                    then round(i.harga_beli / count(w.id), 2)
               end                                              as cost_per_wear
          from items i
          left join wear_log w on w.item_id = i.id
         group by i.id
        """
    )


def downgrade() -> None:
    op.execute("drop view if exists v_cost_per_wear")
    op.drop_index("ix_wear_log_outfit", table_name="wear_log")
    op.drop_index("ix_wear_log_tanggal", table_name="wear_log")
    op.drop_index("ix_wear_log_item_tanggal", table_name="wear_log")
    op.drop_table("wear_log")

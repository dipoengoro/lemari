"""Lapisan database — satu tempat untuk engine, session, dan Base model."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config

engine = create_engine(
    config.sqlalchemy_dsn(),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def sehat() -> tuple[str, str]:
    """Cek koneksi paling dasar: database + user yang sedang dipakai."""
    with engine.connect() as conn:
        row = conn.execute(text("select current_database(), current_user")).fetchone()
    return row[0], row[1]

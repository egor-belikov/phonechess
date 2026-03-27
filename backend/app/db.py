"""
SQLAlchemy engine/session bootstrap.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_config


class Base(DeclarativeBase):
    pass


cfg = get_config()
engine = create_engine(cfg.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


"""Database bootstrap helpers shared by all services."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from finpay.common.config import settings


# Single SQLAlchemy engine per process.
engine = create_engine(settings.postgres_dsn, pool_pre_ping=True)
# `expire_on_commit=False` keeps ORM objects readable after commit in handlers.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""

    pass

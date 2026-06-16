"""SQLAlchemy engine + session. SQLite locally, Postgres (Supabase) in cloud."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import cfg

connect_args = {"check_same_thread": False} if cfg.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(cfg.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
Base = declarative_base()


def init_db():
    from . import models  # noqa: F401  (register models)
    Base.metadata.create_all(engine)


def session():
    return SessionLocal()

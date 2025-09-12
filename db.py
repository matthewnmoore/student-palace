# db.py — SQLAlchemy engine/session/base for Postgres
from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 1) Read DATABASE_URL from the environment (Render → Environment)
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL is not set")

# Some libraries give postgres:// — normalize to postgresql://
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

# 2) Create the engine (connection pool). pool_pre_ping avoids stale connections.
engine = create_engine(
    DB_URL,
    pool_pre_ping=True,
    echo=False,         # set True temporarily if you want SQL logs
    future=True,
)

# 3) Session factory (get a new session per request/task)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# 4) Base class for your ORM models to inherit from
Base = declarative_base()

# 5) Helper to use in view functions:
#    with get_db_session() as db: ...
from contextlib import contextmanager

@contextmanager
def get_db_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except:  # noqa
        db.rollback()
        raise
    finally:
        db.close()

"""DB 연결/세션."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401 - 테이블 등록

DATA_DIR = Path(os.environ.get("TENNISVISION_DATA", Path(__file__).resolve().parents[1] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_URL = os.environ.get("TENNISVISION_DB", f"sqlite:///{(DATA_DIR / 'tennisvision.db').as_posix()}")

engine = create_engine(
    DB_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI 의존성."""
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """백그라운드 작업용."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


UPLOAD_DIR = DATA_DIR / "uploads"
ANALYSIS_DIR = DATA_DIR / "analyses"
CLIP_DIR = DATA_DIR / "clips"
for _d in (UPLOAD_DIR, ANALYSIS_DIR, CLIP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

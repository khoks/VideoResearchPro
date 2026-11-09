import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# Ensure data directory exists
db_path = settings.DATABASE_URL.replace("sqlite:///", "")
os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def insert_if_absent(db: Session, model: Any, rows: list[dict[str, Any]], conflict: list[str]) -> int:
    """Insert ``rows``, leaving alone any row the unique key ``conflict`` already
    holds, and return how many went in. The database decides row by row, so two
    writers that both read "not stored yet" cannot fail on the constraint, as a
    check followed by an insert can. Does not commit."""
    if not rows:
        return 0
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    # The table, not the class: the ORM's bulk insert reports no rowcount.
    stmt = insert(model.__table__).on_conflict_do_nothing(index_elements=conflict)
    count = db.execute(stmt, rows).rowcount
    return count if count >= 0 else len(rows)  # a driver that cannot say

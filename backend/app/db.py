from collections.abc import Iterator

from sqlalchemy import DateTime, MetaData, create_engine
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    # MySQL/MariaDB close idle connections (wait_timeout), so check before use instead of failing with "server has gone away"
    pool_pre_ping=True,
    pool_recycle=3600,
)
# Timestamps keep microseconds everywhere. MySQL's plain DATETIME drops them, and MySQL 8 rounds (sometimes up into the
# next second), so something scheduled for "now" would land in the future and not be due yet.
TZDateTime = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    # Named constraints: PostgreSQL needs names to create/drop the users <-> clients foreign-key cycle,
    # and migrations need stable names to alter constraints later.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

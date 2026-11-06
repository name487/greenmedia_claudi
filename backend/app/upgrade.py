"""Automatic, additive schema upgrades for databases created by an older version of the app.

`create_all` makes missing *tables* but never adds *columns* to existing ones, so an older
greenmedia.db fails with "no such column". On startup we add any missing columns (with their
defaults) instead of asking people to delete their data. Only additive changes are handled;
anything destructive belongs in a real migration tool (Alembic)."""

import logging

from sqlalchemy import JSON, Text, inspect, text
from sqlalchemy.engine import Engine

from .db import Base

log = logging.getLogger("greenmedia.upgrade")


def _default_sql(col, dialect) -> str:
    d = col.default
    if d is None or not getattr(d, "is_scalar", False):
        return ""
    v = d.arg
    if isinstance(v, bool):
        sql = "TRUE" if v else "FALSE"
    elif isinstance(v, (int, float)):
        sql = str(v)
    elif isinstance(v, str):
        sql = "'" + v.replace("'", "''") + "'"
    else:
        return ""
    if dialect.name in ("mysql", "mariadb") and isinstance(col.type, (Text, JSON)):
        sql = f"({sql})"  # MySQL 8 only accepts a TEXT/JSON default as an expression
    return f" DEFAULT {sql}"


def add_missing_columns(engine: Engine) -> list[str]:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    added: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new tables are created by create_all
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}{_default_sql(col, engine.dialect)}'
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
        if "gmb_accounts.connection_id" in added:
            # Upgrading from before the Google integration: every stored review is demo data, and demo
            # reviews now use the "demo_" prefix so linking a real location can remove them safely.
            # (CONCAT on MySQL, where || means OR; "!" as the LIKE escape works on every database)
            joined = ("CONCAT('demo_', SUBSTR(external_review_id, 3))" if engine.dialect.name in ("mysql", "mariadb")
                      else "'demo_' || SUBSTR(external_review_id, 3)")
            conn.execute(text(f"UPDATE gmb_reviews SET external_review_id = {joined} WHERE external_review_id LIKE 'g!_%' ESCAPE '!'"))
        # Approval columns: items already approved/scheduled/published under the previous rules keep their approval.
        if "gmb_reviews.approved_at" in added:
            conn.execute(text("UPDATE gmb_reviews SET approved_at = COALESCE(published_at, created_at) WHERE reply_status IN ('approved', 'published', 'failed')"))
        if "content_items.approved_at" in added:
            conn.execute(text("UPDATE content_items SET approved_at = COALESCE(updated_at, created_at) WHERE status IN ('scheduled', 'publishing', 'published', 'failed')"))
        if "content_variants.status" in added:
            # Variants that already went out (they have a post id) are published, not pending.
            conn.execute(text("UPDATE content_variants SET status = 'published' WHERE external_post_id IS NOT NULL AND external_post_id <> ''"))
    if engine.dialect.name in ("mysql", "mariadb"):
        added += _mysql_microsecond_timestamps(engine, insp, existing_tables)
    if added:
        log.warning("Upgraded database schema, added columns: %s", ", ".join(added))
    return added


def _mysql_microsecond_timestamps(engine: Engine, insp, existing_tables: set[str]) -> list[str]:
    """MySQL tables made before timestamps kept microseconds have DATETIME columns (whole seconds): widen them to
    DATETIME(6), keeping NULL/NOT NULL as it is."""
    changed: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"]: c for c in insp.get_columns(table.name)}
            for col in table.columns:
                c = have.get(col.name)
                if c is None or type(c["type"]).__name__ != "DATETIME" or getattr(c["type"], "fsp", None):
                    continue
                conn.execute(text(f"ALTER TABLE {table.name} MODIFY COLUMN {col.name} DATETIME(6) {'NULL' if c['nullable'] else 'NOT NULL'}"))
                changed.append(f"{table.name}.{col.name} (microseconds)")
    return changed

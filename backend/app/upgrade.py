"""Automatic, additive schema upgrades for databases created by an older version of the app.

`create_all` makes missing *tables* but never adds *columns* to existing ones, so an older
greenmedia.db fails with "no such column". On startup we add any missing columns (with their
defaults) instead of asking people to delete their data. Only additive changes are handled;
anything destructive belongs in a real migration tool (Alembic)."""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import Base

log = logging.getLogger("greenmedia.upgrade")


def _default_sql(col) -> str:
    d = col.default
    if d is None or not getattr(d, "is_scalar", False):
        return ""
    v = d.arg
    if isinstance(v, bool):
        return f" DEFAULT {'TRUE' if v else 'FALSE'}"
    if isinstance(v, (int, float)):
        return f" DEFAULT {v}"
    if isinstance(v, str):
        return " DEFAULT '" + v.replace("'", "''") + "'"
    return ""


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
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}{_default_sql(col)}'
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
        if "gmb_accounts.connection_id" in added:
            # Upgrading from before the Google integration: every stored review is demo data, and demo
            # reviews now use the "demo_" prefix so linking a real location can remove them safely.
            conn.execute(text("UPDATE gmb_reviews SET external_review_id = 'demo_' || substr(external_review_id, 3) "
                              "WHERE external_review_id LIKE 'g\\_%' ESCAPE '\\'"))
        # Approval columns: items already approved/scheduled/published under the previous rules keep their approval.
        if "gmb_reviews.approved_at" in added:
            conn.execute(text("UPDATE gmb_reviews SET approved_at = COALESCE(published_at, created_at) WHERE reply_status IN ('approved', 'published', 'failed')"))
        if "content_items.approved_at" in added:
            conn.execute(text("UPDATE content_items SET approved_at = COALESCE(updated_at, created_at) WHERE status IN ('scheduled', 'publishing', 'published', 'failed')"))
        if "content_variants.status" in added:
            # Variants that already went out (they have a post id) are published, not pending.
            conn.execute(text("UPDATE content_variants SET status = 'published' WHERE external_post_id IS NOT NULL AND external_post_id <> ''"))
    if added:
        log.warning("Upgraded database schema, added columns: %s", ", ".join(added))
    return added

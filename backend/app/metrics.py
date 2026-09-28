from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai import pct
from .models import METRIC_FIELDS, MetricDaily


def totals(db: Session, client_ids: list[int], start: date, end: date) -> dict:
    cols = [func.coalesce(func.sum(getattr(MetricDaily, f)), 0) for f in METRIC_FIELDS]
    row = db.execute(select(*cols).where(MetricDaily.client_id.in_(client_ids), MetricDaily.date.between(start, end))).one()
    return {f: int(v) for f, v in zip(METRIC_FIELDS, row)}


def series(db: Session, client_ids: list[int], start: date, end: date) -> list[dict]:
    cols = [func.sum(getattr(MetricDaily, f)).label(f) for f in METRIC_FIELDS]
    rows = db.execute(
        select(MetricDaily.date, *cols).where(MetricDaily.client_id.in_(client_ids), MetricDaily.date.between(start, end)).group_by(MetricDaily.date).order_by(MetricDaily.date)
    ).all()
    return [{"date": r.date.isoformat(), **{f: int(getattr(r, f)) for f in METRIC_FIELDS}} for r in rows]


def periods(days: int, today: date | None = None) -> tuple[tuple[date, date], tuple[date, date]]:
    """(current, previous) windows of `days` days ending today."""
    end = today or date.today()
    start = end - timedelta(days=days - 1)
    return (start, end), (start - timedelta(days=days), start - timedelta(days=1))


def compare(cur: dict, prev: dict) -> dict:
    return {f: {"current": cur[f], "previous": prev[f], "change_pct": pct(cur[f], prev[f])} for f in METRIC_FIELDS}

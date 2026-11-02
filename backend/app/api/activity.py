"""Local, best-effort research activity aggregation for the library heatmap."""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Paper, ResearchActivity
from ..schemas import ActivityCreate, ActivityDayRead, ActivityRead

router = APIRouter()
_KINDS = ("reading", "notes", "language", "search", "imports")


def _paper_ids(row: ResearchActivity) -> list[str]:
    try:
        values = json.loads(row.paper_ids_json or "[]")
    except (TypeError, ValueError):
        values = []
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def _day_read(day: date, row: ResearchActivity | None) -> ActivityDayRead:
    values = {kind: int(getattr(row, kind, 0) or 0) for kind in _KINDS}
    return ActivityDayRead(
        date=day,
        **values,
        total=sum(values.values()),
        paper_ids=_paper_ids(row) if row else [],
    )


@router.post("/activity", response_model=ActivityDayRead, status_code=201)
def record_activity(payload: ActivityCreate, session: Session = Depends(get_db)) -> ActivityDayRead:
    if payload.paper_id is not None and session.get(Paper, payload.paper_id) is None:
        raise HTTPException(status_code=404, detail="未找到这篇论文")

    today = date.today()
    row = session.get(ResearchActivity, today)
    if row is None:
        row = ResearchActivity(day=today, paper_ids_json="[]")
        session.add(row)
        session.flush()

    setattr(row, payload.kind, int(getattr(row, payload.kind, 0) or 0) + 1)
    if payload.paper_id:
        paper_ids = _paper_ids(row)
        if payload.paper_id not in paper_ids:
            paper_ids.append(payload.paper_id)
        row.paper_ids_json = json.dumps(paper_ids, ensure_ascii=False)
    session.commit()
    session.refresh(row)
    return _day_read(today, row)


@router.get("/activity", response_model=ActivityRead)
def get_activity(
    days: int = Query(365, ge=1, le=730),
    session: Session = Depends(get_db),
) -> ActivityRead:
    today = date.today()
    first_day = today - timedelta(days=days - 1)
    thirty_day_start = today - timedelta(days=29)
    lookup_start = min(first_day, thirty_day_start)
    rows = session.scalars(
        select(ResearchActivity).where(
            ResearchActivity.day >= lookup_start,
            ResearchActivity.day <= today,
        )
    ).all()
    by_day = {row.day: row for row in rows}
    entries = [_day_read(first_day + timedelta(days=index), by_day.get(first_day + timedelta(days=index))) for index in range(days)]

    active_days_30 = sum(
        _day_read(day, by_day.get(day)).total > 0
        for day in (thirty_day_start + timedelta(days=index) for index in range(30))
    )
    streak = 0
    cursor = today
    while True:
        row = by_day.get(cursor)
        if _day_read(cursor, row).total <= 0:
            break
        streak += 1
        cursor -= timedelta(days=1)

    return ActivityRead(
        days=entries,
        total=sum(entry.total for entry in entries),
        active_days_30=active_days_30,
        streak=streak,
    )

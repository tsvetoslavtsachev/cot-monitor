# -*- coding: utf-8 -*-
"""release_status.py: още ли го няма отчетът на CFTC за тази седмица? (ИЛЮ3 Ч2)

COT отчетите са за вторник (reference date) и CFTC ги пуска в петък (+3 дни; при празник по-късно).
Очакваният отчет към дадена дата е най-новият вторник T, за който T + 4 дни <= днес, тоест петъкът
вече е минал (в събота мониторът очаква вторника преди 4 дни). Ако последният наличен отчет е по-стар
от очаквания, статусът е "pending": отчетът за <очаквания вторник> още го няма. Старият не се
показва като свеж. ASCII-safe, без мрежа.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

RELEASE_LAG_DAYS = 4  # вторник + 4 = събота: петъчното пускане вече трябва да е станало


def expected_cot_date(today: date) -> date:
    d = today - timedelta(days=RELEASE_LAG_DAYS)
    while d.weekday() != 1:  # 1 = вторник
        d -= timedelta(days=1)
    return d


def release_status(latest_cot_date: str | None, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    expected = expected_cot_date(today)
    out = {"release_status": "current", "expected_cot_date": expected.isoformat(),
           "latest_cot_date": latest_cot_date, "pending_reason": None}
    try:
        latest = date.fromisoformat(str(latest_cot_date)[:10])
    except (TypeError, ValueError):
        out["release_status"] = "pending"
        out["pending_reason"] = f"липсва валидна дата на последния отчет; очакван е отчетът за {expected.isoformat()}"
        return out
    if latest < expected:
        out["release_status"] = "pending"
        out["pending_reason"] = (f"отчетът за {expected.isoformat()} още го няма "
                                 f"(последен наличен: {latest.isoformat()})")
    return out

#!/usr/bin/env python3
"""Freshness guard for the COT dashboard (cot-monitor).

Fails RED when the newest COT report date across data/markets/*.json is stale --
i.e. a whole weekly reporting cycle was missed and the dashboard would otherwise
republish frozen positioning under a green run.

Why this guard exists
---------------------
The dashboard sources COT report dates from the data-core base (written Sat 07:30
UTC by collectors/cot.yml). But the prices (Yahoo) and manifest.generated_at move
on EVERY run, so `git diff` always shows a change and a commit always lands: a
frozen COT frontier looks alive. Nothing else here checks the report date itself.
This script closes that gap deterministically (no network): it reads the COT
frontier and refuses to pass when it has fallen more than THRESHOLD_DAYS behind
today.

The 11-day threshold
--------------------
COT rows are dated Tuesday (the report reference date). The CFTC publishes them
Friday (+3d). A healthy Saturday collector run therefore sees a frontier <= ~4d
old. A holiday that slips publication to the following Monday adds <= ~3d more.
Anything beyond 11 days means a full reporting cycle was skipped, not merely a
late week. (Tsachev's rule: a Friday publication stays valid until the next
Friday.) So THRESHOLD_DAYS = 11: <= 11 is a normal/holiday-shifted lag; > 11 is a
missed cycle -> exit 1.

Usage
-----
    python scripts/check_freshness.py [markets_dir]

markets_dir defaults to <repo>/data/markets. Passing an explicit dir lets a test
point at mocked fixtures. ASCII-only output (Windows cp1252 console safe).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

THRESHOLD_DAYS = 11
DEFAULT_MARKETS_DIR = Path(__file__).resolve().parents[1] / "data" / "markets"


def last_date(payload: dict) -> str | None:
    """The market file's newest COT report date (YYYY-MM-DD), or None.

    Prefers metadata.history_last_date (written as cot[-1].date by fetch_cot); if
    that is missing/blank it derives the max straight from the cot array, so the
    guard never trusts a stale metadata stamp over the real rows.
    """
    meta = payload.get("metadata") or {}
    stamped = meta.get("history_last_date")
    if stamped:
        return str(stamped)[:10]
    dates = [str(r.get("date") or "")[:10] for r in payload.get("cot", []) if r.get("date")]
    return max(dates) if dates else None


def main(argv: list[str]) -> int:
    markets_dir = Path(argv[1]) if len(argv) > 1 else DEFAULT_MARKETS_DIR
    files = sorted(markets_dir.glob("*.json"))
    if not files:
        print(f"FAIL: no market files found under {markets_dir}", file=sys.stderr)
        return 1

    newest_date: str | None = None
    newest_market: str | None = None
    parsed = 0
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # unreadable/corrupt file -> fail loud, do not skip
            print(f"FAIL: could not read {f.name}: {exc}", file=sys.stderr)
            return 1
        last = last_date(payload)
        if not last:
            continue
        parsed += 1
        if newest_date is None or last > newest_date:
            newest_date = last
            newest_market = f.stem

    if newest_date is None:
        print(f"FAIL: {len(files)} market files but none carried a COT date",
              file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc).date()
    try:
        last_dt = date.fromisoformat(newest_date)
    except ValueError:
        print(f"FAIL: unparseable newest COT date {newest_date!r} "
              f"(market '{newest_market}')", file=sys.stderr)
        return 1

    age = (today - last_dt).days
    if age > THRESHOLD_DAYS:
        print(f"FAIL: COT data is STALE. Newest report date {newest_date} "
              f"(market '{newest_market}') is {age} days old as of {today} "
              f"(threshold {THRESHOLD_DAYS} days). A weekly reporting cycle was "
              f"missed -- the dashboard would republish frozen positioning. "
              f"Expected a report date within {THRESHOLD_DAYS} days of today.",
              file=sys.stderr)
        return 1

    print(f"OK: COT data fresh. Newest report date {newest_date} "
          f"(market '{newest_market}') is {age} days old as of {today} "
          f"(<= {THRESHOLD_DAYS} days), across {parsed} markets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

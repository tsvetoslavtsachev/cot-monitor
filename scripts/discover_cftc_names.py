#!/usr/bin/env python3
"""One-time diagnostic: find current CFTC market names for affected markets.

Run locally (not inside GitHub Actions) to discover which market names
the CFTC currently uses for the TFF COMBINED contracts post-2022.

Usage:
    python scripts/discover_cftc_names.py

Output shows every unique market_and_exchange_names string that the CFTC API
returns, sorted by most-recent-date descending, so COMBINED contracts appear
at the top.  Use these names to update query_name in fetch_cot.py.
"""

from __future__ import annotations

import json
import requests

BASE_TFF = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
BASE_DISAGG = "https://publicreporting.cftc.gov/resource/kh3c-gbw2.json"
HEADERS = {"User-Agent": "cot-cta-dashboard/1.0"}
TIMEOUT = 30

# (key_label, search_term, endpoint) — endpoint matches the report_family used in fetch_cot.py
SEARCHES = [
    # ── Original markets (kept for regression checks) ─────────────────────
    ("sp500",                  "S&P 500",         BASE_TFF),
    ("nasdaq",                 "NASDAQ",          BASE_TFF),
    ("us10y - try 10-YEAR",    "10-YEAR",         BASE_TFF),
    ("us10y - try T-NOTE",     "T-NOTE",          BASE_TFF),
    ("us10y - try CBOT NOTE",  "BOARD OF TRADE",  BASE_TFF),
    ("dxy - try U.S. DOLLAR",  "U.S. DOLLAR",     BASE_TFF),
    ("dxy - try ICE DOLLAR",   "ICE FUTURES",     BASE_TFF),
    ("dxy - try USDX",         "USDX",            BASE_TFF),
    ("gbpfx",                  "BRITISH POUND",   BASE_TFF),
    ("vix",                    "VIX",             BASE_TFF),
    ("eurfx",                  "EURO FX",         BASE_TFF),
    # ── Rates curve (TFF) ─────────────────────────────────────────────────
    ("us2y",                   "UST 2Y NOTE",     BASE_TFF),
    ("us5y",                   "UST 5Y NOTE",     BASE_TFF),
    ("us30y",                  "UST BOND",        BASE_TFF),
    ("usultra10y",             "ULTRA UST 10Y",   BASE_TFF),
    # ── G10 FX (TFF) ──────────────────────────────────────────────────────
    ("jpy",                    "JAPANESE YEN",    BASE_TFF),
    ("chf",                    "SWISS FRANC",     BASE_TFF),
    ("cad",                    "CANADIAN DOLLAR", BASE_TFF),
    ("aud",                    "AUSTRALIAN DOLLAR", BASE_TFF),
    # ── Equities (TFF) ────────────────────────────────────────────────────
    ("russell",                "RUSSELL",         BASE_TFF),
    # ── Metals (Disagg) ───────────────────────────────────────────────────
    ("silver",                 "SILVER",          BASE_DISAGG),
    ("copper",                 "COPPER",          BASE_DISAGG),
    ("platinum",               "PLATINUM",        BASE_DISAGG),
    ("palladium",              "PALLADIUM",       BASE_DISAGG),
    # ── Energy (Disagg) ───────────────────────────────────────────────────
    ("natgas - HENRY HUB",     "HENRY HUB",       BASE_DISAGG),
    ("brent",                  "BRENT LAST DAY",  BASE_DISAGG),
    ("rbob",                   "GASOLINE RBOB",   BASE_DISAGG),
    ("heatingoil - NY HARBOR", "NY HARBOR ULSD",  BASE_DISAGG),
    # ── Grains (Disagg) ───────────────────────────────────────────────────
    ("soybeans",               "SOYBEANS",        BASE_DISAGG),
    ("wheat",                  "WHEAT-SRW",       BASE_DISAGG),
    ("soyoil",                 "SOYBEAN OIL",     BASE_DISAGG),
    ("soymeal",                "SOYBEAN MEAL",    BASE_DISAGG),
    # ── Softs (Disagg, ICE FUTURES U.S.) ──────────────────────────────────
    ("coffee",                 "COFFEE C",        BASE_DISAGG),
    ("sugar",                  "SUGAR NO. 11",    BASE_DISAGG),
    ("cocoa",                  "COCOA",           BASE_DISAGG),
    ("cotton",                 "COTTON NO. 2",    BASE_DISAGG),
    # ── Livestock (Disagg) ────────────────────────────────────────────────
    ("cattle",                 "LIVE CATTLE",     BASE_DISAGG),
    ("hogs",                   "LEAN HOGS",       BASE_DISAGG),
]


def main() -> None:
    for key, search_term, endpoint in SEARCHES:
        params = {
            "$limit": 100,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$where": f"upper(market_and_exchange_names) like '%{search_term.upper()}%'",
        }
        try:
            rows = requests.get(endpoint, params=params, headers=HEADERS, timeout=TIMEOUT).json()
        except Exception as exc:
            print(f"\n=== {key} — ERROR: {exc}")
            continue

        # Group by name, track earliest and latest date
        name_ranges: dict[str, dict] = {}
        for r in rows:
            name = r.get("market_and_exchange_names", "")
            date_val = str(r.get("report_date_as_yyyy_mm_dd") or "")[:10]
            if name not in name_ranges:
                name_ranges[name] = {"first": date_val, "last": date_val, "count": 0}
            name_ranges[name]["count"] += 1
            if date_val > name_ranges[name]["last"]:
                name_ranges[name]["last"] = date_val
            if date_val < name_ranges[name]["first"]:
                name_ranges[name]["first"] = date_val

        print(f"\n{'='*70}")
        print(f"  {key}  (search: '{search_term}', {len(rows)} total rows from API)")
        print(f"{'='*70}")
        for name, info in sorted(name_ranges.items(), key=lambda x: x[1]["last"], reverse=True):
            flag = "  *** POST-2022 ***" if info["last"] >= "2023" else ""
            print(f"  {info['first']} → {info['last']}  ({info['count']} rows){flag}")
            print(f"    Name: {name}")


if __name__ == "__main__":
    main()

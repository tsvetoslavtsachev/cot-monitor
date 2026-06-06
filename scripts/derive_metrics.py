#!/usr/bin/env python3
"""Build derived files used by the dashboard.

Outputs:
- data/derived/watchlist.json
- data/derived/weekly_changes.json
- data/derived/narratives.json
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional

# Dollar-value of one index point (or one price unit) per contract.
# Formula: notional_usd = primary_net × DOLLAR_PER_POINT × price_on_cot_date
#
# Equity indices  — S&P 500 e-mini $50/pt, Nasdaq e-mini $20/pt, Russell 2000 e-mini $50/pt
# Rates           — ZT 2Y is $2K/pt ($200K face × 1%); all other rate contracts are
#                   $1K/pt ($100K face × 1%): ZF, ZN, TN, ZB
# Volatility      — VIX futures $1,000/pt
# FX              — price is exchange rate (USD per foreign), multiply by contract size
#                   EUR/FX: 125,000 EUR × rate = USD notional
#                   GBP/FX: 62,500 GBP × rate
#                   JPY (6J=F): 12,500,000 JPY × USD/JPY (CME quote convention)
#                   CHF (6S=F): 125,000 CHF × rate
#                   CAD (6C=F): 100,000 CAD × rate
#                   AUD (6A=F): 100,000 AUD × rate
#                   DXY:    $1,000 per index point
# Commodities (Yahoo unit handling):
#   Metals          — Gold 100 oz × $/oz; Silver 5,000 oz × $/oz;
#                     Copper 25,000 lb × $/lb (HG=F is in $/lb, NOT ¢/lb);
#                     Platinum 50 oz × $/oz; Palladium 100 oz × $/oz
#   Energy          — WTI 1,000 bbl × $/bbl; Brent 1,000 bbl × $/bbl;
#                     Natgas 10,000 MMBtu × $/MMBtu;
#                     RBOB / Heating Oil 42,000 gal × $/gal
#   Grains          — Corn / Soybeans / Wheat: 5,000 bu × ¢/bu → multiplier=50
#                     Soy Oil: 60,000 lb × ¢/lb → multiplier=600
#                     Soy Meal: 100 short tons × $/ton → multiplier=100
#   Softs (¢/lb except Cocoa which is $/ton)
#                   — Coffee 37,500 lb × ¢/lb → 375; Sugar 112,000 lb × ¢/lb → 1120;
#                     Cocoa 10 metric tons × $/ton → 10; Cotton 50,000 lb × ¢/lb → 500
#   Livestock (¢/lb)
#                   — Cattle / Hogs 40,000 lb × ¢/lb → 400
DOLLAR_PER_POINT: Dict[str, float] = {
    # Equities
    "sp500":      50.0,
    "nasdaq":     20.0,
    "russell":    50.0,
    # Rates
    "us2y":       2_000.0,
    "us5y":       1_000.0,
    "us10y":      1_000.0,
    "usultra10y": 1_000.0,
    "us30y":      1_000.0,
    # Volatility
    "vix":        1_000.0,
    # FX
    "eurfx":      125_000.0,
    "gbpfx":      62_500.0,
    "jpy":        12_500_000.0,
    "chf":        125_000.0,
    "cad":        100_000.0,
    "aud":        100_000.0,
    "dxy":        1_000.0,
    # Crypto
    "bitcoin":    5.0,
    # Metals
    "gold":       100.0,
    "silver":     5_000.0,
    "copper":     25_000.0,
    "platinum":   50.0,
    "palladium":  100.0,
    # Energy
    "wti":        1_000.0,
    "brent":      1_000.0,
    "natgas":     10_000.0,
    "rbob":       42_000.0,
    "heatingoil": 42_000.0,
    # Grains
    "corn":       50.0,    # 5,000 bushels; Yahoo price in ¢/bushel → ÷100 baked into 50
    "soybeans":   50.0,
    "wheat":      50.0,
    "soyoil":     600.0,   # 60,000 lb in ¢/lb
    "soymeal":    100.0,   # 100 short tons in $/ton
    # Softs
    "coffee":     375.0,
    "sugar":      1_120.0,
    "cocoa":      10.0,
    "cotton":     500.0,
    # Livestock
    "cattle":     400.0,
    "hogs":       400.0,
}

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DERIVED_DIR = DATA_DIR / "derived"

# Minimum number of non-missing historical net observations required before a
# percentile / z-score is trustworthy. Below this a percentile collapses to a
# coarse 0/100 and a z-score to ~0 — both fake extremes. All live markets carry
# 150+ weeks, so this is a no-op on real data and only guards new contracts.
MIN_HISTORY_OBS = 8



def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))



def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")



def percentile(values: List[float], current: float) -> float:
    if not values:
        return 50.0
    below = sum(1 for v in values if v <= current)
    return round(100.0 * below / len(values), 2)



def zscore(values: List[float], current: float) -> float:
    if len(values) < 2:
        return 0.0
    mu = mean(values)
    sigma = pstdev(values)
    if sigma == 0:
        return 0.0
    return round((current - mu) / sigma, 4)



def sign(num: Optional[float]) -> int:
    if num is None:
        return 0
    if num > 0:
        return 1
    if num < 0:
        return -1
    return 0



def pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old in (None, 0):
        return None
    return ((new - old) / abs(old)) * 100.0


def get_price_on_date(
    prices: List[Dict[str, Any]],
    date_str: str,
    max_lookback_days: int = 5,
) -> Optional[float]:
    """Return the closing price for *date_str* (YYYY-MM-DD or ISO datetime).

    With daily price data we match the exact COT report date (Tuesday).
    If that day has no price (public holiday, etc.) we fall back up to
    *max_lookback_days* earlier trading days.  Returns None when no match
    is found (price history doesn't reach that far back).
    """
    target = datetime.strptime(date_str[:10], "%Y-%m-%d")
    by_date: Dict[str, float] = {}
    for p in prices:
        try:
            dt = datetime.utcfromtimestamp(p["timestamp"])
            by_date[dt.strftime("%Y-%m-%d")] = p["close"]
        except (KeyError, TypeError, OSError):
            continue
    for lag in range(max_lookback_days + 1):
        key = (target - timedelta(days=lag)).strftime("%Y-%m-%d")
        if key in by_date:
            return by_date[key]
    return None



def score_market(latest: Dict[str, Any], previous_4w: Optional[Dict[str, Any]]) -> Optional[float]:
    # Core positioning (percentile + z = 50% of the score) is unknown when the
    # latest net is missing. Return None instead of fabricating a rank from a
    # neutral 50/0 — a phantom rank can push a no-data market up the watchlist.
    primary_pct = latest.get("primary_percentile")
    primary_z = latest.get("primary_zscore")
    if primary_pct is None or primary_z is None:
        return None
    pct_extreme = abs(primary_pct - 50.0) / 50.0
    z_extreme = min(abs(primary_z), 3.0) / 3.0

    delta_4w = latest.get("primary_delta_4w") or 0.0
    oi = latest.get("open_interest")
    if oi is not None and oi > 0:
        momentum_4w = min(abs(delta_4w) / oi * 10.0, 1.0)
        oi_change = latest.get("oi_delta_4w") or 0.0
        oi_confirmation = min(abs(oi_change) / oi * 10.0, 1.0)
    else:
        # Missing/zero OI is unknown, NOT a denominator of 1.0 — that would clamp
        # momentum to its max (1.0) and fabricate a confirmation. Drop both.
        momentum_4w = 0.0
        oi_confirmation = 0.0

    divergence_score = 1.0 if sign(latest.get("primary_net")) != sign(latest.get("secondary_net")) else 0.0

    price_4w = latest.get("price_change_4w_pct") or 0.0
    price_position_dislocation = 1.0 if sign(price_4w) != sign(delta_4w) and abs(price_4w) > 1.0 else 0.0

    score = (
        0.30 * pct_extreme
        + 0.20 * z_extreme
        + 0.15 * momentum_4w
        + 0.15 * divergence_score
        + 0.10 * oi_confirmation
        + 0.10 * price_position_dislocation
    )
    return round(score * 100.0, 2)



def compute_streak(cot: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect consecutive-week directional streak in primary_net positioning.

    Returns:
        streak_weeks: int — count of consecutive weeks with same-sign weekly delta
        streak_direction: 'building_long' | 'building_short' | 'unwinding_long' |
                          'unwinding_short' | 'flat' | 'n/a'
        streak_total_change: float — cumulative net contracts moved over the streak
    """
    if len(cot) < 2:
        return {"streak_weeks": 0, "streak_direction": "n/a", "streak_total_change": 0.0}

    # Build weekly deltas walking from latest backwards
    deltas: List[float] = []
    for i in range(len(cot) - 1, 0, -1):
        cur = cot[i].get("primary_net")
        prv = cot[i - 1].get("primary_net")
        if cur is None or prv is None:
            break
        deltas.append(float(cur) - float(prv))

    if not deltas:
        return {"streak_weeks": 0, "streak_direction": "n/a", "streak_total_change": 0.0}

    latest_sign = 1 if deltas[0] > 0 else -1 if deltas[0] < 0 else 0
    if latest_sign == 0:
        return {"streak_weeks": 0, "streak_direction": "flat", "streak_total_change": 0.0}

    streak = 1
    cumulative = deltas[0]
    for d in deltas[1:]:
        s = 1 if d > 0 else -1 if d < 0 else 0
        if s == latest_sign:
            streak += 1
            cumulative += d
        else:
            break

    cur_net = float(cot[-1].get("primary_net") or 0.0)
    if latest_sign > 0:
        direction = "building_long" if cur_net >= 0 else "unwinding_short"
    else:
        direction = "building_short" if cur_net <= 0 else "unwinding_long"

    return {
        "streak_weeks": streak,
        "streak_direction": direction,
        "streak_total_change": round(cumulative, 0),
    }


def detect_crossings(cot: List[Dict[str, Any]], current_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect week-over-week regime/threshold crossings — 'what changed this week'.

    Returns structured events (type + payload) so the frontend can format them in BG.
    Event types:
        sign_flip:        net position direction flipped (long ↔ short)
        percentile_cross: crossed a key threshold (10, 90) up or down
        regime_change:    regime classification differs from previous week
        streak_start:     streak just hit ≥3 weeks (was <3 last week)
    """
    events: List[Dict[str, Any]] = []
    if len(cot) < 2:
        return events
    if cot[-1].get("primary_net") is None:
        # Latest net missing → any crossing would be measured against a fake 0.
        return events

    cur = cot[-1]
    prev = cot[-2]
    cur_net = cur.get("primary_net") or 0.0
    prev_net = prev.get("primary_net") or 0.0

    # 1. Sign flip (long ↔ short)
    if cur_net * prev_net < 0:
        events.append({
            "type": "sign_flip",
            "from": "long" if prev_net > 0 else "short",
            "to": "long" if cur_net > 0 else "short",
            "from_value": round(prev_net, 0),
            "to_value": round(cur_net, 0),
        })

    # 2. Percentile threshold crossings
    nets = [r.get("primary_net") for r in cot if r.get("primary_net") is not None]
    if len(nets) >= 2:
        cur_pct = percentile(nets, cur_net)
        prev_pct_val = percentile(nets[:-1], prev_net)
        for t in (10, 90):
            crossed_up = prev_pct_val < t and cur_pct >= t
            crossed_down = prev_pct_val > t and cur_pct <= t
            if crossed_up or crossed_down:
                events.append({
                    "type": "percentile_cross",
                    "threshold": t,
                    "direction": "up" if crossed_up else "down",
                    "from_pct": round(prev_pct_val, 1),
                    "to_pct": round(cur_pct, 1),
                })

    # 3. Regime change — recompute previous week's regime synthetically
    if len(nets) >= 2:
        prev_synthetic = dict(prev)
        prev_synthetic["primary_percentile"] = percentile(nets[:-1], prev_net)
        prev_synthetic["primary_delta_4w"] = (
            (prev_net - (cot[-6].get("primary_net") or 0.0)) if len(cot) >= 6 else 0.0
        )
        # No 4w price for prev week — neutral default; affects only Contrarian classifications
        prev_synthetic["price_change_4w_pct"] = 0.0
        prev_regime = regime_label(prev_synthetic)
        cur_regime = current_summary.get("regime")
        if prev_regime and cur_regime and prev_regime != cur_regime:
            events.append({
                "type": "regime_change",
                "from": prev_regime,
                "to": cur_regime,
            })

    # 4. Streak just hit 3 weeks this week
    streak_weeks = current_summary.get("streak_weeks") or 0
    if streak_weeks == 3:
        events.append({
            "type": "streak_start",
            "direction": current_summary.get("streak_direction"),
            "weeks": streak_weeks,
        })

    return events


def regime_label(row: Dict[str, Any]) -> str:
    pct = row.get("primary_percentile")
    if pct is None:
        # No trustworthy percentile (missing net / too little history) → don't
        # default to "Neutral", which would read as a real, calm signal.
        return "Insufficient Data"
    price = row.get("price_change_4w_pct") or 0.0
    delta = row.get("primary_delta_4w") or 0.0
    primary_sign = sign(row.get("primary_net"))
    secondary_sign = sign(row.get("secondary_net"))

    if primary_sign != 0 and secondary_sign != 0 and primary_sign != secondary_sign:
        return "Divergence"
    if pct >= 85 and delta > 0:
        return "Crowded Long"
    if pct <= 15 and delta < 0:
        return "Crowded Short"
    if pct <= 15 and price > 0:
        return "Contrarian Long"
    if pct >= 85 and price < 0:
        return "Contrarian Short"
    return "Neutral / Transition"



def build_market_summary(market_meta: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    cot = payload.get("cot", [])
    if not cot:
        raise ValueError("No COT rows found")

    nets = [r.get("primary_net") for r in cot if r.get("primary_net") is not None]
    latest = dict(cot[-1])
    previous_4w = cot[-5] if len(cot) >= 5 else None

    # --- Positioning percentile / z-score, with explicit missing-data handling ---
    # A missing latest net is UNKNOWN, not zero: ranking a fabricated 0 against
    # real history manufactures a false extreme (e.g. S&P leveraged net is
    # chronically negative, so 0 ranks ~100th pct → phantom "Crowded Long").
    data_quality: List[str] = []
    latest_net = latest.get("primary_net")
    if latest_net is None:
        latest["primary_percentile"] = None
        latest["primary_zscore"] = None
        data_quality.append("missing_primary_net")
    elif len(nets) < MIN_HISTORY_OBS:
        latest["primary_percentile"] = None
        latest["primary_zscore"] = None
        data_quality.append(f"insufficient_history:{len(nets)}")
    elif pstdev(nets) == 0:
        # Flat history: every observation identical → percentile collapses to a
        # degenerate 0/100 and z to 0. Neither is a real extreme.
        latest["primary_percentile"] = None
        latest["primary_zscore"] = None
        data_quality.append("zero_dispersion")
    else:
        latest["primary_percentile"] = percentile(nets, latest_net)
        latest["primary_zscore"] = zscore(nets, latest_net)

    if latest.get("open_interest") is None:
        data_quality.append("missing_open_interest")

    if previous_4w:
        latest["primary_delta_4w"] = safe_sub(latest.get("primary_net"), previous_4w.get("primary_net"))
        latest["oi_delta_4w"] = safe_sub(latest.get("open_interest"), previous_4w.get("open_interest"))
    else:
        latest["primary_delta_4w"] = 0.0
        latest["oi_delta_4w"] = 0.0

    # --- Price alignment: match exact COT report date using daily price series ---
    prices = payload.get("prices", [])
    cot_date = latest.get("date", "")
    cot_date_4w = previous_4w.get("date", "") if previous_4w else ""

    latest_close = get_price_on_date(prices, cot_date) if cot_date else None
    prior_close = get_price_on_date(prices, cot_date_4w) if cot_date_4w else None

    latest["price_change_4w_pct"] = (
        round(pct_change(latest_close, prior_close) or 0.0, 2)
        if (latest_close is not None and prior_close is not None)
        else None
    )

    # --- Dollar-value of net positioning (notional USD, in billions for readability) ---
    market_key = market_meta["key"]
    multiplier = DOLLAR_PER_POINT.get(market_key)
    primary_net = latest.get("primary_net")
    if multiplier is not None and primary_net is not None and latest_close is not None:
        notional = primary_net * multiplier * latest_close
        latest["notional_usd"] = round(notional, 0)           # exact dollars
        latest["notional_usd_bn"] = round(notional / 1e9, 2)  # billions (for display)
    else:
        latest["notional_usd"] = None
        latest["notional_usd_bn"] = None

    streak_info = compute_streak(cot)
    latest.update(streak_info)

    latest["regime"] = regime_label(latest)
    latest["crossings"] = detect_crossings(cot, latest)
    latest["watchlist_score"] = score_market(latest, previous_4w)
    latest["market_key"] = market_meta["key"]
    latest["market_title"] = market_meta["title"]
    latest["subtitle"] = market_meta.get("subtitle")
    latest["price_label"] = market_meta.get("price_label")
    latest["takeaway"] = build_takeaway(latest)
    latest["changes"] = build_changes(latest, previous_4w)
    latest["narrative"] = build_narrative(latest)
    latest["data_quality"] = data_quality
    return latest



def safe_sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b



def build_takeaway(row: Dict[str, Any]) -> str:
    regime = row.get("regime")
    if regime == "Insufficient Data":
        return "Latest-week positioning data is missing — no regime read this week."
    pct = row.get("primary_percentile", 50.0)
    delta = row.get("primary_delta_4w") or 0.0
    if regime == "Divergence":
        return "Fast money and slower cohorts are pulling in different directions."
    if regime == "Crowded Long":
        return f"Positioning remains stretched on the long side ({pct:.0f}th percentile)."
    if regime == "Crowded Short":
        return f"Short crowding remains heavy ({pct:.0f}th percentile from the bottom)."
    if regime == "Contrarian Long":
        return "Bearish positioning is no longer fully confirmed by price action."
    if regime == "Contrarian Short":
        return "Bullish positioning looks vulnerable to an unwind."
    if delta > 0:
        return "Positioning is improving but not yet in an extreme regime."
    return "Positioning is easing without a clear high-conviction signal."



def build_changes(latest: Dict[str, Any], previous_4w: Optional[Dict[str, Any]]) -> List[str]:
    if latest.get("regime") == "Insufficient Data":
        return ["Latest-week positioning data is missing; percentile, z-score and regime were not computed."]
    changes: List[str] = []
    delta = latest.get("primary_delta_4w") or 0.0
    pct = latest.get("primary_percentile", 50.0)
    price = latest.get("price_change_4w_pct")
    regime = latest.get("regime")

    direction = "added to longs" if delta > 0 else "added to shorts" if delta < 0 else "held positioning broadly steady"
    changes.append(f"Primary cohort {direction} over the last 4 weeks.")
    changes.append(f"Primary positioning sits near the {pct:.0f}th percentile of the selected history.")
    if sign(latest.get("primary_net")) != sign(latest.get("secondary_net")):
        changes.append("Primary and secondary cohorts remain in divergence.")
    if price is not None:
        price_dir = "rose" if price > 0 else "fell" if price < 0 else "was flat"
        changes.append(f"Price {price_dir} {abs(price):.2f}% over the same 4-week window.")
    changes.append(f"Current regime: {regime}.")
    return changes[:5]



def build_narrative(row: Dict[str, Any]) -> str:
    market = row.get("market_title")
    regime = row.get("regime")
    if regime == "Insufficient Data":
        return (f"{market}: latest-week positioning data is missing, so percentile, "
                f"z-score and regime could not be computed this week.")
    pct = row.get("primary_percentile", 50.0)
    delta = row.get("primary_delta_4w") or 0.0
    delta_word = "rose" if delta > 0 else "fell" if delta < 0 else "was broadly unchanged"
    delta_abs = abs(delta)
    price = row.get("price_change_4w_pct")
    sec_relation = "diverging from" if sign(row.get("primary_net")) != sign(row.get("secondary_net")) else "confirmed by"
    price_phrase = "Price context is unavailable."
    if price is not None:
        direction = "up" if price > 0 else "down" if price < 0 else "flat"
        price_phrase = f"Price is {direction} {abs(price):.2f}% over the same 4-week window."
    return (
        f"{market} remains in a {regime} setup. Primary positioning is at the {pct:.0f}th percentile over the recent history. "
        f"Over the last 4 weeks, net positioning {delta_word} by {delta_abs:,.0f} contracts and is currently {sec_relation} the secondary cohort. "
        f"{price_phrase}"
    )



def main() -> None:
    manifest = read_json(DATA_DIR / "manifest.json")
    watchlist = []
    weekly_changes = []
    narratives = []

    for market in manifest.get("markets", []):
        payload = read_json(DATA_DIR / market["file"])
        summary = build_market_summary(market, payload)
        history_weeks = len(payload.get("cot", []))
        history_first_date = payload.get("metadata", {}).get("history_first_date")
        watchlist.append(
            {
                "market": summary["market_key"],
                "title": summary["market_title"],
                "subtitle": summary.get("subtitle"),
                "date": summary.get("date"),
                "score": summary.get("watchlist_score"),
                "regime": summary.get("regime"),
                "history_weeks": history_weeks,
                "history_first_date": history_first_date,
                "primary_percentile": summary.get("primary_percentile"),
                "primary_zscore": summary.get("primary_zscore"),
                "primary_net": summary.get("primary_net"),
                "primary_delta_4w": summary.get("primary_delta_4w"),
                "secondary_net": summary.get("secondary_net"),
                "price_change_4w_pct": summary.get("price_change_4w_pct"),
                "notional_usd_bn": summary.get("notional_usd_bn"),  # net positioning in $B
                "streak_weeks": summary.get("streak_weeks"),
                "streak_direction": summary.get("streak_direction"),
                "streak_total_change": summary.get("streak_total_change"),
                "crossings": summary.get("crossings", []),
                "takeaway": summary.get("takeaway"),
                "data_quality": summary.get("data_quality", []),
            }
        )
        weekly_changes.append(
            {
                "market": summary["market_key"],
                "title": summary["market_title"],
                "date": summary.get("date"),
                "changes": summary.get("changes"),
            }
        )
        narratives.append(
            {
                "market": summary["market_key"],
                "title": summary["market_title"],
                "date": summary.get("date"),
                "narrative": summary.get("narrative"),
            }
        )

    watchlist.sort(key=lambda x: x.get("score") or 0.0, reverse=True)
    for index, row in enumerate(watchlist, start=1):
        row["rank"] = index

    write_json(DERIVED_DIR / "watchlist.json", watchlist)
    write_json(DERIVED_DIR / "weekly_changes.json", weekly_changes)
    write_json(DERIVED_DIR / "narratives.json", narratives)
    print("✓ Derived files written")


if __name__ == "__main__":
    main()

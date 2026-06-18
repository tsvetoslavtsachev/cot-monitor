#!/usr/bin/env python3
"""CTA trend-following replication model (TSMOM ensemble).

Estimates directional CTA positioning and price trigger levels for each market
using a standard Time-Series Momentum (TSMOM) approach.

Signal logic
------------
For each lookback window L ∈ {16, 32, 52} weeks:

    return_L     = cumulative price return over the last L weeks
    vol_weekly   = realized std of weekly returns over the last 12 weeks
    vol_L        = vol_weekly × sqrt(L)           (expected vol over horizon L)
    raw_signal_L = return_L / vol_L               (Sharpe-ratio-like, dimensionless)
    signal_L     = clip(raw_signal_L, -1.0, 1.0)

Ensemble signal = simple average of the three lookback signals.

Estimated dollar position = ensemble_signal × AUM_SCALAR[market]

Trigger levels
--------------
signal_L flips sign when return_L = 0, i.e. when current_price = price_L_weeks_ago.
Each trigger is therefore the price from L weeks ago.  If current price is above
the trigger → that lookback is long; below → short.

AUM scalars
-----------
Rough estimates of CTA / trend-following capacity in each market, calibrated so
that signal = ±1 maps to a maximum plausible dollar position.  These are
approximate; GS Prime Brokerage proprietary data would give exact numbers.
For reference, GS reported ~$30B CTA short in S&P 500 at the April 2026 peak.

Outputs
-------
data/cta_model/{market_key}.json  — one file per market
data/cta_model/summary.json       — all markets in one flat list
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from math import sqrt, floor, log10
from pathlib import Path
from statistics import pstdev
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MARKETS_DIR = DATA_DIR / "markets"
CTA_DIR = DATA_DIR / "cta_model"

LOOKBACKS = [16, 32, 52]          # weeks
VOL_WINDOW = 12                    # weeks for realized vol estimate
SIGNAL_CAP = 1.0

# Estimated maximum CTA / trend-following dollar exposure per market (USD).
# When |signal| = 1.0 the model outputs this as the estimated position.
# Sources: GS Prime Brokerage research, academic TSMOM papers, AQR estimates.
# *** These are intentionally conservative central estimates, not upper bounds. ***
CTA_AUM_SCALAR: Dict[str, float] = {
    # Equities
    "sp500":      35_000_000_000,   # ~$35B; GS cited ~$30B at peak short in Apr 2026
    "nasdaq":     15_000_000_000,   # ~$15B; smaller than S&P 500 (lower liquidity)
    "russell":     5_000_000_000,   # ~$5B; small-cap exposure smaller than mega-cap
    # Rates (largest CTA bucket; trend-followers run massive duration positions)
    "us2y":       30_000_000_000,
    "us5y":       40_000_000_000,
    "us10y":      50_000_000_000,
    "usultra10y": 10_000_000_000,
    "us30y":      25_000_000_000,
    # Volatility
    "vix":         1_500_000_000,   # CTAs are structurally short vol premia
    # FX
    "eurfx":       5_000_000_000,
    "gbpfx":       3_000_000_000,
    "jpy":         8_000_000_000,   # JPY is a major CTA carry/macro market
    "chf":         2_000_000_000,
    "cad":         3_000_000_000,
    "aud":         3_000_000_000,
    "dxy":         4_000_000_000,
    # Crypto
    "bitcoin":     3_000_000_000,   # growing but still small vs traditional assets
    # Metals
    "gold":       12_000_000_000,   # gold is a major CTA allocation
    "silver":      3_000_000_000,
    "copper":      5_000_000_000,
    "platinum":    1_000_000_000,
    "palladium":     500_000_000,
    # Energy
    "wti":         8_000_000_000,
    "brent":       5_000_000_000,
    "natgas":      4_000_000_000,
    "rbob":        2_000_000_000,
    "heatingoil":  2_000_000_000,
    # Grains
    "corn":        2_000_000_000,
    "soybeans":    4_000_000_000,
    "wheat":       2_000_000_000,
    "soyoil":      1_000_000_000,
    "soymeal":     1_000_000_000,
    # Softs
    "coffee":      1_000_000_000,
    "sugar":       1_000_000_000,
    "cocoa":         500_000_000,
    "cotton":        500_000_000,
    # Livestock
    "cattle":      1_000_000_000,
    "hogs":          500_000_000,
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def price_decimals(value: float) -> int:
    """Decimal places that preserve a price's signal at its magnitude.

    Normal-scale prices (|value| >= 0.1) keep the historical 2-decimal
    convention, so every market except the sub-0.1 ones stays byte-identical.
    Sub-0.1 prices — notably JPY/USD (~0.0063) — collapse to a single "0.01"
    under 2-decimal rounding, erasing the entire trigger structure; for them we
    scale precision to retain ~4 significant figures.
    """
    a = abs(value)
    if a >= 0.1 or a == 0:
        return 2
    return 3 - floor(log10(a))


def round_price(value: Optional[float]) -> Optional[float]:
    """Round a price to magnitude-appropriate precision (see price_decimals)."""
    if value is None:
        return None
    return round(value, price_decimals(value))


def format_flip_level(value: float) -> str:
    """Format a trigger level for the flip_note text.

    Whole-number formatting is kept for |value| >= 1 (unchanged for the major FX
    crosses and every dollar-priced market); sub-1 levels get enough decimals to
    stay meaningful — JPY would otherwise read "above 0".
    """
    if abs(value) >= 1:
        return f"{value:.0f}"
    return f"{value:.{price_decimals(value)}f}"


def build_weekly_series(
    prices: List[Dict[str, Any]],
    cot_dates: List[str],
) -> List[Tuple[str, float]]:
    """Build a weekly price series aligned to COT report dates (Tuesdays).

    For each COT date we look up the matching close from the price data,
    falling back up to 5 calendar days earlier for holidays.  This keeps
    the price series consistent with the COT positioning data.

    Returns list of (date_str, close) tuples, sorted ascending (oldest first).
    """
    # Build a calendar-day lookup: "YYYY-MM-DD" → close
    by_date: Dict[str, float] = {}
    for p in prices:
        try:
            dt = datetime.utcfromtimestamp(p["timestamp"])
            by_date[dt.strftime("%Y-%m-%d")] = p["close"]
        except (KeyError, TypeError, OSError):
            continue

    series: List[Tuple[str, float]] = []
    for date_str in cot_dates:
        target = datetime.strptime(date_str[:10], "%Y-%m-%d")
        close: Optional[float] = None
        for lag in range(6):
            key = (target - __import__("datetime").timedelta(days=lag)).strftime("%Y-%m-%d")
            if key in by_date:
                close = by_date[key]
                break
        if close is not None:
            series.append((date_str[:10], close))

    return sorted(series, key=lambda x: x[0])


def weekly_returns(series: List[Tuple[str, float]]) -> List[float]:
    """Compute week-over-week simple returns from a price series (ascending)."""
    rets: List[float] = []
    for i in range(1, len(series)):
        prev = series[i - 1][1]
        curr = series[i][1]
        if prev > 0:
            rets.append(curr / prev - 1.0)
    return rets  # ascending (index 0 = oldest)


def compute_signal(
    returns: List[float],  # ascending, all available weekly returns
    lookback_weeks: int,
    vol_window: int = VOL_WINDOW,
) -> Optional[Dict[str, Any]]:
    """Compute TSMOM signal for a given lookback window.

    Returns None when there is insufficient data.
    """
    needed = lookback_weeks + vol_window
    if len(returns) < needed:
        return None

    # Most-recent L returns (most recent = last element in ascending list)
    lookback_rets = returns[-lookback_weeks:]
    vol_rets = returns[-vol_window:]

    # Cumulative return over the lookback window
    cum_return = 1.0
    for r in lookback_rets:
        cum_return *= (1.0 + r)
    cum_return -= 1.0

    # Realized weekly vol → annualized → scaled to horizon L
    vol_weekly = pstdev(vol_rets) if len(vol_rets) >= 2 else 0.0
    vol_annual = vol_weekly * sqrt(52)
    vol_horizon = vol_weekly * sqrt(lookback_weeks)   # expected vol over horizon

    raw = (cum_return / vol_horizon) if vol_horizon > 0 else 0.0
    signal = max(-SIGNAL_CAP, min(SIGNAL_CAP, raw))

    return {
        "lookback_weeks": lookback_weeks,
        "cumulative_return_pct": round(cum_return * 100, 2),
        "vol_annual_pct": round(vol_annual * 100, 2),
        "raw_signal": round(raw, 4),
        "signal": round(signal, 4),
    }


def trigger_price(
    weekly_series: List[Tuple[str, float]],
    lookback_weeks: int,
) -> Optional[float]:
    """Return the price from *lookback_weeks* ago — the level at which
    the momentum signal for that lookback would flip sign.

    If current price > trigger → signal is long (return > 0).
    If current price < trigger → signal is short (return < 0).
    """
    if len(weekly_series) < lookback_weeks + 1:
        return None
    # weekly_series is ascending; the price L weeks ago is at index -(L+1)
    # (index -1 is current, so index -(L+1) is L weeks back)
    return weekly_series[-(lookback_weeks + 1)][1]


# ── Main model ────────────────────────────────────────────────────────────────

def run_market(market_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build the CTA model output for a single market."""
    cot_rows = payload.get("cot", [])
    prices = payload.get("prices", [])
    meta = payload.get("metadata", {})

    if not cot_rows or not prices:
        raise ValueError("Missing COT or price data")

    cot_dates = [r["date"] for r in cot_rows if r.get("date")]
    weekly_series = build_weekly_series(prices, cot_dates)

    if len(weekly_series) < LOOKBACKS[-1] + VOL_WINDOW + 1:
        raise ValueError(
            f"Insufficient price history: need {LOOKBACKS[-1]+VOL_WINDOW+1} weeks, "
            f"have {len(weekly_series)}"
        )

    rets = weekly_returns(weekly_series)
    current_price = weekly_series[-1][1]
    current_date = weekly_series[-1][0]
    aum_scalar = CTA_AUM_SCALAR.get(market_key, 0.0)

    # Compute signals for each lookback
    signals: Dict[str, Any] = {}
    valid_signals: List[float] = []

    for L in LOOKBACKS:
        sig = compute_signal(rets, L)
        trig = trigger_price(weekly_series, L)
        if sig is None:
            continue
        key = f"{L}w"
        direction = "long" if sig["signal"] > 0 else "short" if sig["signal"] < 0 else "flat"
        flip_direction = "rises above" if sig["signal"] < 0 else "falls below"
        signals[key] = {
            **sig,
            "trigger_price": round_price(trig) if trig is not None else None,
            "trigger_date": weekly_series[-(L + 1)][0] if len(weekly_series) >= L + 1 else None,
            "current_vs_trigger": (
                # round the gap to the price's own scale, not the gap's — keeps
                # normal-scale markets at 2 decimals while resolving JPY's gap.
                round(current_price - trig, price_decimals(current_price))
                if trig is not None else None
            ),
            "direction": direction,
            "flip_note": (
                f"Signal flips when price {flip_direction} {format_flip_level(trig)}"
                if trig is not None else None
            ),
        }
        valid_signals.append(sig["signal"])

    ensemble = round(sum(valid_signals) / len(valid_signals), 4) if valid_signals else None
    estimated_position = (
        round(ensemble * aum_scalar, 0) if ensemble is not None else None
    )
    estimated_position_bn = (
        round(estimated_position / 1e9, 2) if estimated_position is not None else None
    )

    # Ensemble direction summary
    if ensemble is not None:
        if ensemble > 0.33:
            ensemble_direction = "net long"
        elif ensemble < -0.33:
            ensemble_direction = "net short"
        else:
            ensemble_direction = "mixed / transitioning"
    else:
        ensemble_direction = "unavailable"

    # CFTC Leveraged Money notional for cross-reference
    latest_cot = cot_rows[-1] if cot_rows else {}
    cftc_primary_net = latest_cot.get("primary_net")

    return {
        "market": market_key,
        "title": meta.get("title", market_key),
        "price_label": meta.get("price_label", ""),
        "cot_date": latest_cot.get("date", "")[:10],
        "model_date": current_date,
        "current_price": round_price(current_price),
        "signals": signals,
        "ensemble_signal": ensemble,
        "ensemble_direction": ensemble_direction,
        "estimated_position_bn": estimated_position_bn,
        "aum_scalar_bn": round(aum_scalar / 1e9, 1),
        "cftc_primary_net_contracts": cftc_primary_net,
        "methodology_note": (
            "TSMOM ensemble of 16/32/52-week lookbacks, vol-normalized (12-week realized vol). "
            "Signal capped at ±1.0. AUM scalar is an estimate — proprietary prime brokerage "
            "data (GS, UBS) would give exact CTA-only figures. "
            "CFTC Leveraged Money is broader than CTA-only and includes hedge funds."
        ),
    }


def main() -> None:
    CTA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = read_json(DATA_DIR / "manifest.json")

    summary: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    for market in manifest.get("markets", []):
        key = market["key"]
        try:
            payload = read_json(DATA_DIR / market["file"])
            result = run_market(key, payload)
            write_json(CTA_DIR / f"{key}.json", result)
            summary.append(result)

            sig_str = " | ".join(
                f"{lw}: {result['signals'][lw]['signal']:+.2f} ({result['signals'][lw]['direction']})"
                for lw in [f"{L}w" for L in LOOKBACKS]
                if lw in result["signals"]
            )
            pos = result.get("estimated_position_bn")
            pos_str = f"  est. ${pos:+.1f}B" if pos is not None else ""
            print(f"✓ {key:<12} ensemble={result['ensemble_signal']:+.3f} ({result['ensemble_direction']}){pos_str}")
            print(f"  signals: {sig_str}")
        except Exception as exc:
            failures.append({"key": key, "error": str(exc)})
            print(f"✗ {key}: {exc}")

    # Write summary
    write_json(
        CTA_DIR / "summary.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "markets": summary,
            "failures": failures,
        },
    )
    print(f"\n✓ CTA model complete — {len(summary)} markets, {len(failures)} failures")


if __name__ == "__main__":
    main()

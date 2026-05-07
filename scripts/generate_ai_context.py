#!/usr/bin/env python3
"""Generate data/ai_context.json — a single flat file optimised for AI analysis.

Purpose
-------
When an AI assistant (e.g. Claude in Cowork) needs to analyse the current
positioning snapshot, it reads this one file instead of traversing all
individual market files.  The file aggregates:

  - CFTC COT positioning (CFTC Leveraged Money / Managed Money)
  - Dollar-value notional estimates
  - CTA TSMOM replication model signals and trigger levels
  - 4-week deltas, percentiles, z-scores, regime labels
  - Narrative takeaways per market
  - Global watchlist ranking

Design principles
-----------------
* Flat where possible — avoid deep nesting so the AI can scan quickly.
* Human-readable labels alongside numeric codes.
* Explicit units in field names (e.g. _bn = billions USD, _pct = percent).
* Methodology notes embedded so the AI knows what it cannot see
  (e.g. GS Prime Brokerage data, equity shorts outside futures, OTC swaps).
* One entry per market; sorted by watchlist score (most actionable first).

Output
------
data/ai_context.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DERIVED_DIR = DATA_DIR / "derived"
CTA_DIR = DATA_DIR / "cta_model"


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_market_entry(
    wl_row: Dict[str, Any],
    cta_row: Optional[Dict[str, Any]],
    narrative_row: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge watchlist + CTA model + narrative into one flat dict per market."""

    market = wl_row["market"]

    # ── CFTC COT fields ──────────────────────────────────────────────────────
    entry: Dict[str, Any] = {
        "market": market,
        "title": wl_row.get("title", market),
        "subtitle": wl_row.get("subtitle", ""),
        "cot_date": (wl_row.get("date") or "")[:10],
        # Positioning
        "cftc_primary_net_contracts": wl_row.get("primary_net"),
        "cftc_primary_net_bn": wl_row.get("notional_usd_bn"),          # $B, net notional
        "cftc_primary_delta_4w_contracts": wl_row.get("primary_delta_4w"),
        "cftc_secondary_net_contracts": wl_row.get("secondary_net"),
        # Metrics
        "percentile": wl_row.get("primary_percentile"),                 # 0–100
        "zscore": wl_row.get("primary_zscore"),
        "regime": wl_row.get("regime"),
        "watchlist_score": wl_row.get("score"),
        "watchlist_rank": wl_row.get("rank"),
        # Price context
        "price_change_4w_pct": wl_row.get("price_change_4w_pct"),
        # Narrative
        "takeaway": wl_row.get("takeaway"),
        "narrative": narrative_row.get("narrative") if narrative_row else None,
    }

    # ── CTA model fields (optional — may be absent for some markets) ─────────
    if cta_row:
        signals = cta_row.get("signals", {})

        def sig_summary(key: str) -> Optional[Dict[str, Any]]:
            s = signals.get(key)
            if s is None:
                return None
            return {
                "signal": s.get("signal"),
                "direction": s.get("direction"),
                "trigger_price": s.get("trigger_price"),
                "trigger_date": s.get("trigger_date"),
                "price_vs_trigger": s.get("current_vs_trigger"),
                "flip_note": s.get("flip_note"),
            }

        entry.update({
            "cta_current_price": cta_row.get("current_price"),
            "cta_ensemble_signal": cta_row.get("ensemble_signal"),      # –1 to +1
            "cta_ensemble_direction": cta_row.get("ensemble_direction"),
            "cta_estimated_position_bn": cta_row.get("estimated_position_bn"),
            "cta_aum_scalar_bn": cta_row.get("aum_scalar_bn"),
            "cta_signal_16w": sig_summary("16w"),
            "cta_signal_32w": sig_summary("32w"),
            "cta_signal_52w": sig_summary("52w"),
            # Key divergence metric: model says X, CFTC shows Y
            # Positive = model more bullish than CFTC → potential covering rally
            # Negative = model more bearish → potential new shorts building
            "cta_vs_cftc_gap": (
                _safe_sub(
                    cta_row.get("estimated_position_bn"),
                    wl_row.get("notional_usd_bn"),
                )
            ),
        })
    else:
        entry.update({
            "cta_current_price": None,
            "cta_ensemble_signal": None,
            "cta_ensemble_direction": None,
            "cta_estimated_position_bn": None,
            "cta_aum_scalar_bn": None,
            "cta_signal_16w": None,
            "cta_signal_32w": None,
            "cta_signal_52w": None,
            "cta_vs_cftc_gap": None,
        })

    return entry


def _safe_sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round(a - b, 2)


def main() -> None:
    watchlist = read_json(DERIVED_DIR / "watchlist.json") or []
    narratives = read_json(DERIVED_DIR / "narratives.json") or []
    cta_summary = read_json(CTA_DIR / "summary.json") or {}
    manifest = read_json(DATA_DIR / "manifest.json") or {}

    # Build lookup dicts
    narrative_by_market = {r["market"]: r for r in narratives}
    cta_by_market = {r["market"]: r for r in cta_summary.get("markets", [])}

    # Build per-market entries (watchlist is already sorted by score, rank assigned)
    markets_out: List[Dict[str, Any]] = []
    for wl_row in watchlist:
        mkt = wl_row["market"]
        entry = build_market_entry(
            wl_row,
            cta_by_market.get(mkt),
            narrative_by_market.get(mkt),
        )
        markets_out.append(entry)

    # Global summary stats
    cot_dates = [m.get("cot_date") for m in markets_out if m.get("cot_date")]
    latest_cot = max(cot_dates) if cot_dates else None

    crowded_longs = [m["title"] for m in markets_out if m.get("regime") == "Crowded Long"]
    crowded_shorts = [m["title"] for m in markets_out if m.get("regime") == "Crowded Short"]
    divergences = [m["title"] for m in markets_out if m.get("regime") == "Divergence"]

    # Markets where CTA model disagrees strongly with CFTC positioning
    big_gaps = []
    for m in markets_out:
        gap = m.get("cta_vs_cftc_gap")
        if gap is not None and abs(gap) > 5:  # >$5B divergence is notable
            big_gaps.append({
                "market": m["market"],
                "title": m["title"],
                "gap_bn": gap,
                "interpretation": (
                    "Model more bullish than CFTC — short-covering likely in progress"
                    if gap > 0 else
                    "Model more bearish than CFTC — new shorts may be building"
                ),
            })

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "latest_cot_date": latest_cot,
        "data_sources": {
            "cftc_cot": "CFTC Commitments of Traders (public, ~3 business day lag)",
            "prices": "Yahoo Finance (daily closes, aligned to COT report Tuesdays)",
            "cta_model": (
                "TSMOM replication: 16/32/52-week ensemble, vol-normalized. "
                "AUM scalars are estimates. GS/UBS Prime Brokerage has exact CTA-only data."
            ),
        },
        "what_this_dashboard_cannot_see": [
            "Equity shorts via stock borrowing (not captured in CFTC futures data)",
            "OTC equity swaps and total return swaps (off-exchange)",
            "Single-stock short interest (separate FINRA short interest data)",
            "ETF short positions (stock lending market, not CME futures)",
            "Real-time intra-week positioning changes (CFTC lag ~3 business days)",
            "Geographic rotation within equities (US vs Europe/Asia — Eurex/OSE not covered)",
            "GS/UBS Prime Brokerage net leverage ratios (proprietary, client-only)",
            "Dollar-amount CTA positions from GS CTA model (proprietary algorithm)",
        ],
        "global_snapshot": {
            "crowded_longs": crowded_longs,
            "crowded_shorts": crowded_shorts,
            "divergence_regimes": divergences,
            "cta_model_vs_cftc_gaps": big_gaps,
        },
        "markets": markets_out,
        "field_guide": {
            "cftc_primary_net_bn": "Net notional of CFTC Leveraged Money (TFF) or Managed Money (Disagg) in $B. Broader than CTA-only.",
            "cta_estimated_position_bn": "Model estimate of CTA-only trend-following position in $B. Based on AUM scalar × ensemble signal.",
            "cta_vs_cftc_gap": "Model position minus CFTC notional ($B). Positive = model more bullish than CFTC → short-covering pressure.",
            "cta_signal_Xw": "Signal for lookback X: range –1 (full short) to +1 (full long). trigger_price is the level where signal flips.",
            "percentile": "Current net positioning vs full history window (0=most short ever, 100=most long ever).",
            "zscore": "Standard deviations from mean positioning. |z|>2 = statistically extreme.",
            "regime": "Crowded Long/Short = extreme + momentum confirming. Divergence = fast money vs slow money opposing. Contrarian = extreme + price disagrees.",
        },
    }

    write_json(DATA_DIR / "ai_context.json", output)

    # Print summary
    print(f"✓ ai_context.json written — {len(markets_out)} markets, COT date: {latest_cot}")
    if crowded_longs:
        print(f"  Crowded Longs: {', '.join(crowded_longs)}")
    if crowded_shorts:
        print(f"  Crowded Shorts: {', '.join(crowded_shorts)}")
    if big_gaps:
        print(f"  Large CTA/CFTC gaps (>$5B): {', '.join(g['market'] for g in big_gaps)}")


if __name__ == "__main__":
    main()

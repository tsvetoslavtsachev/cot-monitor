"""Missing-data trap tests for derive_metrics.

These lock in the audit fix: a *missing* input must be flagged (None +
``data_quality``), never silently faked into a neutral 50 / z 0 or a false
0/100 extreme. Complete data must score exactly as before (regression).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import derive_metrics as dm  # noqa: E402


def wdate(i: int) -> str:
    """Weekly Tuesday-ish date string for row i."""
    return (date(2024, 1, 2) + timedelta(weeks=i)).isoformat()


def make_payload(nets, ois=None, secondary=None, prices=None):
    """Build a minimal market payload from a list of primary nets."""
    n = len(nets)
    if ois is None:
        ois = [100_000] * n
    if secondary is None:
        secondary = list(nets)  # same sign → not Divergence
    cot = []
    for i in range(n):
        cot.append(
            {
                "date": wdate(i),
                "primary_net": nets[i],
                "secondary_net": secondary[i],
                "open_interest": ois[i],
            }
        )
    return {"cot": cot, "prices": prices or []}


META = {"key": "test", "title": "Test Market"}


# ── Complete data: regression — behaves exactly as before ─────────────────────

def test_complete_data_scores_normally():
    nets = [float(x) for x in range(100, 100 + 20)]  # rising, dispersed
    summary = dm.build_market_summary(META, make_payload(nets))
    assert summary["primary_percentile"] is not None
    assert summary["primary_zscore"] is not None
    assert 0.0 <= summary["primary_percentile"] <= 100.0
    assert summary["regime"] != "Insufficient Data"
    assert summary["watchlist_score"] is not None
    assert summary["data_quality"] == []


# ── Trap A: missing latest net → flag, never a fabricated extreme ─────────────

def test_missing_latest_net_is_flagged_not_faked():
    # S&P-like: chronically negative net history; last week missing.
    nets = [-200_000.0 - i * 1000 for i in range(20)]
    nets[-1] = None  # latest week's cohort suppressed by CFTC
    summary = dm.build_market_summary(META, make_payload(nets))

    assert summary["primary_percentile"] is None  # NOT 50, NOT 100
    assert summary["primary_zscore"] is None
    assert summary["regime"] == "Insufficient Data"
    assert summary["watchlist_score"] is None  # no phantom rank
    assert "missing_primary_net" in summary["data_quality"]
    # The narrative/takeaway must not assert a fake reading.
    assert "missing" in summary["takeaway"].lower()


# ── Trap B: missing OI → drop momentum, never clamp it to max via oi=1.0 ──────

def test_missing_oi_drops_momentum_not_clamps_to_max():
    base = {
        "primary_percentile": 90.0,
        "primary_zscore": 2.0,
        "primary_delta_4w": 50_000.0,
        "oi_delta_4w": 50_000.0,
        "primary_net": 100_000,
        "secondary_net": 100_000,
        "price_change_4w_pct": 0.0,
    }
    s_with_oi = dm.score_market(dict(base, open_interest=2_000_000), None)
    s_missing = dm.score_market(dict(base, open_interest=None), None)
    # Real OI → small momentum (0.25). Missing OI → 0 (dropped). The OLD code
    # turned missing OI into oi=1.0 → momentum clamped to MAX (1.0), inflating
    # the score. Dropping must therefore score *lower*, not higher.
    assert s_missing < s_with_oi


def test_missing_oi_is_flagged():
    nets = [float(x) for x in range(100, 120)]
    ois = [100_000] * 19 + [None]  # latest OI missing
    summary = dm.build_market_summary(META, make_payload(nets, ois=ois))
    assert "missing_open_interest" in summary["data_quality"]
    assert summary["watchlist_score"] is not None  # still scores on positioning


# ── Trap C: too little / flat history → flag, no coarse 0/100 ─────────────────

def test_insufficient_history_is_flagged():
    nets = [float(x) for x in range(100, 106)]  # 6 obs < MIN_HISTORY_OBS (8)
    summary = dm.build_market_summary(META, make_payload(nets))
    assert summary["primary_percentile"] is None
    assert summary["primary_zscore"] is None
    assert any(d.startswith("insufficient_history") for d in summary["data_quality"])


def test_zero_dispersion_is_flagged():
    nets = [500.0] * 12  # identical every week → pstdev == 0
    summary = dm.build_market_summary(META, make_payload(nets))
    # Without the guard, percentile would be a fake 100 (all values <= current).
    assert summary["primary_percentile"] is None
    assert summary["primary_zscore"] is None
    assert "zero_dispersion" in summary["data_quality"]


# ── detect_crossings: no "what changed" claims when latest net is missing ─────

def test_crossings_empty_when_latest_net_missing():
    cot = [{"primary_net": 100.0 + i, "secondary_net": 100.0} for i in range(10)]
    cot[-1]["primary_net"] = None
    assert dm.detect_crossings(cot, {"regime": "Insufficient Data"}) == []


# ── Primitive guards: document existing safe behaviour ────────────────────────

def test_pct_change_reference_no_div_by_zero():
    assert dm.pct_change(10.0, 0) is None      # old == 0 → None, not inf/0
    assert dm.pct_change(10.0, None) is None
    assert dm.pct_change(None, 5.0) is None
    assert dm.pct_change(10.0, 5.0) == pytest.approx(100.0)


def test_percentile_empty_and_zscore_short():
    assert dm.percentile([], 5.0) == 50.0       # primitive default (now unreachable in pipeline)
    assert dm.zscore([5.0], 5.0) == 0.0

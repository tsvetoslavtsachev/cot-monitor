"""Gate for scripts/export_signal.py (signals-registry M2): one cot-cta object from ai_context.json,
never a silent fake, never a failed refresh."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import export_signal as ex  # noqa: E402


def market(key, title, regime, signal=0.7092, direction="net long"):
    return {"market": key, "title": title, "cot_date": "2026-09-15", "regime": regime,
            "cta_ensemble_signal": signal, "cta_ensemble_direction": direction,
            "percentile": 50.57, "zscore": -0.0787, "cftc_primary_net_contracts": -293143.0,
            "price_change_4w_pct": -1.62}


def make_ai(sp500=True, signal=0.7092):
    markets = [market("gold", "Gold", "Crowded Long")]
    if sp500:
        markets.append(market("sp500", "E-mini S&P 500", "Divergence", signal=signal))
    return {"generated_at": "2026-09-19T11:13:57.584342Z", "latest_cot_date": "2026-09-15",
            "global_snapshot": {"crowded_longs": ["Corn", "Sugar"], "crowded_shorts": ["UST 2Y Note"],
                                "divergence_regimes": ["Gold", "E-mini S&P 500"]},
            "markets": markets}


def test_build_signal_maps_sp500_regime_and_cta_signal():
    sig = ex.build_signal(make_ai())
    assert sig["module"] == "cot-cta" and sig["schema_version"] == "0.1"
    assert sig["state"] == "Divergence"
    assert sig["score"] == pytest.approx(0.7092) and sig["scale"] == [-1, 1]
    assert sig["as_of"] == "2026-09-15" and sig["generated_at"].endswith("Z")
    assert sig["crowded_longs"] == ["Corn", "Sugar"] and sig["divergence_count"] == 2
    assert "Divergence" in sig["notes"] and "+0,71" in sig["notes"] and len(sig["notes"]) <= 300


def test_missing_sp500_is_refused_not_faked():
    with pytest.raises(ValueError):
        ex.build_signal(make_ai(sp500=False))


def test_non_numeric_signal_becomes_null_not_zero():
    sig = ex.build_signal(make_ai(signal=None))
    assert sig["score"] is None
    assert "n/a" in sig["notes"]


def test_export_writes_signals_current_json(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ai_context.json").write_text(json.dumps(make_ai()), encoding="utf-8")
    target = ex.export(tmp_path)
    assert target == tmp_path / "signals" / "current.json"
    assert json.loads(target.read_text(encoding="utf-8"))["state"] == "Divergence"


def test_main_never_fails_the_refresh_unless_strict(tmp_path):
    assert ex.main(["--root", str(tmp_path)]) == 0
    assert ex.main(["--root", str(tmp_path), "--strict"]) == 1

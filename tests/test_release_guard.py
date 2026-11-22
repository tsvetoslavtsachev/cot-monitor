"""ИЛЮ3 Ч2: мутационен гейт: празен/подменен вход е червен, здрав е зелен, стар COT е „още го няма“."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import export_signal as ex  # noqa: E402
import fetch_cot as fc  # noqa: E402
import release_status as rs  # noqa: E402
from input_guard import InputError  # noqa: E402

SAT = date(2026, 11, 14)  # събота; очакваният отчет е вторник 10.11


def tff_row(d):
    return {"report_date_as_yyyy_mm_dd": d + "T00:00:00.000", "market_and_exchange_names": "E-MINI S&P 500 - CME",
            "open_interest_all": "100", "dealer_positions_long_all": "1", "dealer_positions_short_all": "2"}


class Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def run_main(tmp_path, monkeypatch):
    market = dict(next(m for m in fc.MARKETS if m["report_family"] == "tff"))
    monkeypatch.setattr(fc, "MARKETS", [market])
    monkeypatch.setattr(fc, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fc, "MARKETS_DIR", tmp_path / "markets")
    monkeypatch.setattr(fc, "DERIVED_DIR", tmp_path / "derived")
    monkeypatch.setattr(fc, "_cot_consumer", None)
    monkeypatch.setattr(fc, "fetch_price_series", lambda s: [])

    def _run(body):
        monkeypatch.setattr(fc.requests, "get", lambda *a, **k: Resp(body))
        return fc.main()
    return _run


def test_a_empty_response_is_red(run_main):
    assert run_main("[]") == 1
    assert run_main("") == 1


def test_b_html_instead_of_data_is_red(run_main):
    assert run_main("<!DOCTYPE html><html><body>Service unavailable</body></html>") == 1


def test_b2_missing_columns_is_red(run_main):
    assert run_main(json.dumps([{"foo": 1}])) == 1


def test_c_healthy_response_is_green(run_main):
    body = json.dumps([tff_row("2026-11-03"), tff_row("2026-10-27")])
    assert run_main(body) == 0


def test_d_old_cot_is_pending_not_fresh():
    st = rs.release_status("2026-11-03", SAT)
    assert st["release_status"] == "pending" and st["expected_cot_date"] == "2026-11-10"
    assert "2026-11-10" in st["pending_reason"] and "2026-11-03" in st["pending_reason"]


def test_d_expected_date_and_current():
    assert rs.expected_cot_date(SAT) == date(2026, 11, 10)
    assert rs.expected_cot_date(date(2026, 11, 13)) == date(2026, 11, 3)  # петък още не е „събота“
    assert rs.release_status("2026-11-10", SAT)["release_status"] == "current"
    assert rs.release_status(None, SAT)["release_status"] == "pending"


def test_d_signal_says_pending_with_last_available_date():
    from test_export_signal import make_ai
    ai = make_ai()
    ai["latest_cot_date"] = "2026-11-03"
    sig = ex.build_signal(ai, SAT)
    assert sig["release_status"] == "pending" and sig["expected_cot_date"] == "2026-11-10"
    assert sig["as_of"] == "2026-11-03" and "още го няма" in sig["pending_reason"]
    assert sig["notes"].startswith("Отчетът за 2026-11-10 още го няма") and len(sig["notes"]) <= 300
    ai["latest_cot_date"] = "2026-11-10"
    fresh = ex.build_signal(ai, SAT)
    assert fresh["release_status"] == "current" and fresh["pending_reason"] is None

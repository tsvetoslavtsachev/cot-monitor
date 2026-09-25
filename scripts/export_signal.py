# -*- coding: utf-8 -*-
"""export_signal.py: signals/current.json за signals-registry (M2, 25.09.2026).

Чете data/ai_context.json (вече построен от generate_ai_context.py) и пише signals/current.json:
един обект за модула cot-cta по схемата 0.1 на регистъра. state е regime етикетът на
E-mini S&P 500 (derive_metrics.regime_label), score е CTA ансамбловият сигнал за sp500
(scale [-1, 1]), as_of е latest_cot_date. Регистърът дърпа файла в събота; това repo не знае
нищо за него.

Правила: само чете; нищо не пресмята наново; при грешка печата ::warning:: и излиза с 0
(старият файл остава), с --strict грешката е изход 1.

Run:  python scripts/export_signal.py [--root PATH] [--out PATH] [--strict]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "0.1"
MARKET = "sp500"
SOURCE_URL = "https://tsvetoslavtsachev.github.io/cot-monitor/"


def build_signal(ai: dict) -> dict:
    markets = ai.get("markets") or []
    hits = [m for m in markets if m.get("market") == MARKET]
    if len(hits) != 1:
        raise ValueError(f"ai_context: очаквах точно един пазар {MARKET!r}, намерих {len(hits)}")
    m = hits[0]
    as_of = ai.get("latest_cot_date") or m.get("cot_date")
    if not isinstance(as_of, str):
        raise ValueError("ai_context: липсва latest_cot_date")
    generated_at = ai.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("ai_context: липсва generated_at")
    regime = m.get("regime")
    if not isinstance(regime, str) or not regime:
        raise ValueError(f"ai_context: {MARKET} няма regime етикет")
    signal = m.get("cta_ensemble_signal")
    score = float(signal) if isinstance(signal, (int, float)) and not isinstance(signal, bool) else None
    direction = m.get("cta_ensemble_direction") or "n/a"
    pct = m.get("percentile")
    snap = ai.get("global_snapshot") or {}
    score_txt = f"{score:+.2f}".replace(".", ",") if score is not None else "n/a"
    pct_txt = f"{pct:.0f}" if isinstance(pct, (int, float)) else "n/a"
    return {
        "module": "cot-cta",
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "generated_at": generated_at,
        "state": regime,
        "score": score,
        "scale": [-1, 1],
        "confidence": None,
        "falsified": False,
        "persistence": None,
        "notes": f"E-mini S&P 500: позициониране „{regime}“, CTA ансамбъл {score_txt} ({direction}), "
                 f"персентил на нетната позиция {pct_txt}; COT към {m.get('cot_date', as_of)}.",
        "source_url": SOURCE_URL,
        "market": MARKET,
        "title": m.get("title"),
        "cot_date": m.get("cot_date"),
        "cta_ensemble_direction": m.get("cta_ensemble_direction"),
        "percentile": pct,
        "zscore": m.get("zscore"),
        "cftc_primary_net_contracts": m.get("cftc_primary_net_contracts"),
        "price_change_4w_pct": m.get("price_change_4w_pct"),
        "crowded_longs": list(snap.get("crowded_longs") or []),
        "crowded_shorts": list(snap.get("crowded_shorts") or []),
        "divergence_count": len(snap.get("divergence_regimes") or []),
    }


def export(root: Path, out: Path | None = None) -> Path:
    ai = json.loads((root / "data" / "ai_context.json").read_text(encoding="utf-8"))
    signal = build_signal(ai)
    target = out or (root / "signals" / "current.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(signal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Пише signals/current.json за signals-registry от ai_context.json.")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    try:
        target = export(Path(args.root), Path(args.out) if args.out else None)
        sig = json.loads(target.read_text(encoding="utf-8"))
        print(f"export_signal: {target} (cot-cta={sig['state']}, score={sig['score']}, as_of {sig['as_of']})")
        return 0
    except Exception as exc:  # noqa: BLE001  (никога не събаряме седмичния refresh)
        print(f"::warning::export_signal пропусна записа: {type(exc).__name__}: {exc}")
        return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())

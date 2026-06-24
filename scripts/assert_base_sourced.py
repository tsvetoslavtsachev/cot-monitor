#!/usr/bin/env python3
"""CI guard (INIT-22 A1): fail RED if any market silently fell back to CFTC.

The S13c/A1 strangler sources every market's COT cohort rows FROM data-core (the
guarded base, splice-fixed). fetch_cot.py is base-first with a CFTC fallback that
fails CLOSED if the data-core/collectors wiring is unavailable — which keeps the
dashboard alive but would SILENTLY republish the spliced (audit-bug) percentiles.

This guard makes that failure LOUD: when DATACORE_PAT is set (base sourcing is
intended), every market in the manifest must carry cot_source == "data-core".
If any shows "cftc", the build fails so the splice can never quietly return on a
green run. Run only when DATACORE_PAT is set (the workflow gates it); with the
secret absent the CFTC fallback is legitimate and this guard is skipped.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "data" / "manifest.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    markets = manifest.get("markets", [])
    if not markets:
        print("assert_base_sourced: no markets in manifest", file=sys.stderr)
        return 1

    offenders = []
    for m in markets:
        key = m["key"]
        payload_path = MANIFEST.parent / m["file"]
        src = json.loads(payload_path.read_text(encoding="utf-8"))["metadata"].get("cot_source")
        if src != "data-core":
            offenders.append(f"{key} (cot_source={src!r})")

    total = len(markets)
    if offenders:
        print(f"FAIL: {len(offenders)}/{total} markets did NOT source from data-core "
              f"(DATACORE_PAT is set, so base sourcing was expected):", file=sys.stderr)
        for o in offenders:
            print(f"  - {o}", file=sys.stderr)
        print("The strangler silently reverted to the CFTC fallback (spliced "
              "percentiles). Check the data-core/collectors checkout + PYTHONPATH.",
              file=sys.stderr)
        return 1

    print(f"OK: all {total} markets sourced from data-core (cot_source=data-core).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

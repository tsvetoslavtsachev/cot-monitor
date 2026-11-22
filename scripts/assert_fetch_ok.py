# -*- coding: utf-8 -*-
"""assert_fetch_ok.py: алармата СЛЕД комита (ИЛЮ3 Ч2). Червено, ако има повреден пазар или нула здрави.
Липсващ маркер също е червено (fetch_cot не е стигнал до края). ASCII-safe изход."""
import json
import sys
from pathlib import Path

MARKER = Path(__file__).resolve().parents[1] / ".fetch_status.json"


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else MARKER
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL: no fetch marker ({exc})", file=sys.stderr)
        return 1
    if m.get("healthy", 0) == 0 or m.get("failed"):
        print(f"FAIL: healthy={m.get('healthy')} failed={m.get('failed')}", file=sys.stderr)
        return 1
    print(f"OK: all {m['healthy']} markets healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

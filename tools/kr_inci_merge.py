#!/usr/bin/env python3
"""Merge two independent Korean -> INCI readings into data/regulatory/kr_inci_map.json.

  agree (same INCI after case/space folding, both 'high')  -> accepted
  agree but either reader 'low'                             -> accepted, confidence low
  disagree                                                  -> left out (listed for review)
  either says 'not an ingredient'                           -> recorded as null

Usage: python3 tools/kr_inci_merge.py A.json B.json [A2.json B2.json ...]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/regulatory/kr_inci_map.json"


def fold(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    files = sys.argv[1:]
    pairs = list(zip(files[0::2], files[1::2]))
    merged, review = {}, {}
    for fa, fb in pairs:
        A, B = json.load(open(fa)), json.load(open(fb))
        for ko in sorted(set(A) | set(B)):
            a, b = A.get(ko) or {}, B.get(ko) or {}
            ia, ib = a.get("inci"), b.get("inci")
            if ia is None and ib is None and (a or b):
                merged[ko] = {"inci": None, "confidence": "high", "note": "not an ingredient"}
            elif ia and ib and fold(ia) == fold(ib):
                conf = "high" if a.get("confidence") == b.get("confidence") == "high" else "low"
                merged[ko] = {"inci": ia, "confidence": conf, "note": a.get("note") or b.get("note") or ""}
            else:
                review[ko] = {"A": ia, "B": ib}
    old = json.loads(OUT.read_text()) if OUT.exists() else {"map": {}, "review": {}}
    old["map"].update(merged)
    old["review"] = {k: v for k, v in {**old.get("review", {}), **review}.items() if k not in old["map"]}
    old["note"] = ("Korean label names (KCIA standard names) -> INCI, two independent readings that agree; "
                   "'review' holds the disagreements, not used")
    OUT.write_text(json.dumps(old, ensure_ascii=False, indent=1, sort_keys=True))
    print(f"accepted {len(merged)} (low confidence {sum(1 for v in merged.values() if v['confidence'] == 'low')}), "
          f"disagree {len(review)} -> {OUT}")


if __name__ == "__main__":
    main()

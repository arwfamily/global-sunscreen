"""
rescope_ca.py — re-apply the corrected scope rule to data already collected.

Scope is a judgement about records we already hold, not something the API
tells us, so a wrong rule can be undone without asking Health Canada for
anything again. The 2026-08-21 run stored 2,309 "sunscreens" because the
old SUNSCREEN_RE matched a bare "sunburn" — zinc ointments, calamine,
anti-itch creams and one fibre laxative all qualified. This re-runs the
corrected rule over data/canonical/ca_ingredients.jsonl.

Nothing is deleted. Records that no longer qualify move to
data/canonical/ca_excluded.jsonl with the reason, so the count of what we
looked at and rejected stays visible — an empty bucket and an unexamined
bucket must never look the same.

Offline. Run once after updating adapters/ca_lnhpd.py:
    python rescope_ca.py
"""

import json
import shutil
import sys
from collections import Counter
from pathlib import Path

from adapters.ca_lnhpd import scope_of, MINERAL_UV

ROOT = Path(__file__).parent
CANON = ROOT / "data" / "canonical" / "ca_ingredients.jsonl"
EXCL = ROOT / "data" / "canonical" / "ca_excluded.jsonl"


def actives_of(rec):
    return {str(a.get("name") or "").strip().lower()
            for a in (rec.get("actives") or [])}


def main():
    if not CANON.exists():
        sys.exit(f"[!] {CANON} not found — nothing to rescope")

    records = [json.loads(l) for l in CANON.open() if l.strip()]
    print(f"[*] loaded {len(records)} records")

    backup = CANON.with_suffix(".jsonl.pre-rescope")
    shutil.copy2(CANON, backup)
    print(f"[*] backup written to {backup.name}")

    kept, dropped, why = [], [], Counter()
    for rec in records:
        names = actives_of(rec)
        scope = scope_of(rec.get("purposes") or [], rec.get("product_name"),
                         rec.get("dosage_form"), names)
        if scope == "sunscreen":
            rec["scope"] = "sunscreen"
            # uv_filters / mineral_only were written under the old rule; the
            # actives have not changed, but recompute so the two agree.
            rec["uv_filters"] = sorted(names & MINERAL_UV) or sorted(names)
            rec["mineral_only"] = bool(names) and names <= MINERAL_UV
            kept.append(rec)
        else:
            reason = ("no mineral UV filter among actives"
                      if not (names & MINERAL_UV)
                      else "no sun-protection claim in purpose or name")
            why[reason] += 1
            dropped.append({"id": rec.get("id"),
                            "product_name": rec.get("product_name"),
                            "actives": [a.get("name") for a in (rec.get("actives") or [])],
                            "purposes": rec.get("purposes"),
                            "excluded_reason": reason,
                            "excluded_by": "rescope_ca.py 2026-08-21"})

    with CANON.open("w") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with EXCL.open("w") as f:
        for rec in dropped:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[*] sunscreens kept : {len(kept)}")
    print(f"[*] moved to ca_excluded.jsonl : {len(dropped)}")
    for reason, n in why.most_common():
        print(f"      {n:5d}  {reason}")

    mineral = sum(1 for r in kept if r.get("mineral_only"))
    baby = sum(1 for r in kept if r.get("baby"))
    znonly = sum(1 for r in kept
                 if [a.get("name") for a in r.get("actives") or []] == ["Zinc oxide"])
    print(f"[*] of those kept: mineral-only {mineral}, zinc-only {znonly}, "
          f"baby-flagged {baby}")
    print(f"[*] NOTE: baby flags are only recomputed by a fresh collector run "
          f"(they depend on the populations table); this script does not "
          f"invent them.")


if __name__ == "__main__":
    main()

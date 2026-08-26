#!/usr/bin/env python3
"""
parse_au_actives.py — give every Australian active a percent, not just zinc.

WHY
  au_sunscreens.json carries actives_raw straight from the ARTG export:
      "zinc oxide 250.0mg/g"
      "octyl methoxycinnamate 75.0mg/mL; zinc oxide 70.0mg/mL; oxybenzone 30.0mg/mL"
  The unit is right there in the string, but only zinc_percent was ever derived
  and only on 143 of 502 records. Every chemical filter concentration was sitting
  unparsed in a text field.

  Without percent_ww the Australian half of the corpus cannot enter the
  cross-border legality check, so this is the same defect the US parser had —
  the number existed, nobody read the unit.

UNITS FOUND (surveyed across all 502 records, not assumed)
  mg/g    496 tokens   -> percent w/w   = value / 10
  mg/mL     2 tokens   -> percent w/v   = value / 10, flagged separately
  separator is a SEMICOLON, not a comma

REFUSALS
  Anything that does not match a known "<name> <number><unit>" shape is left as
  percent_ww = None with the reason recorded. A guessed concentration would make
  a product look compliant in a jurisdiction where it is not.
"""

import argparse
import json
import re
import sys
from collections import Counter

TOKEN = re.compile(
    r"^(?P<name>.+?)\s+(?P<val>[\d.]+)\s*"
    r"(?P<unit>microgram/g|mcg/g|ug/g|microgram/mL|mg/g|mg/mL|g/g|g/mL|%)$",
    re.IGNORECASE)

# ARTG writes concentration per gram or per millilitre. w/w and w/v are not the
# same measurement, so the basis travels with the number and never gets averaged
# together with it.
CONVERT = {
    # bemotrizinol is registered at microgram/g on some ARTG entries
    # (900 microgram/g = 0.09 %), which the first pass could not read at all
    "MICROGRAM/G": (lambda v: v / 10000.0, "w/w"),
    "MCG/G": (lambda v: v / 10000.0, "w/w"),
    "UG/G": (lambda v: v / 10000.0, "w/w"),
    "MICROGRAM/ML": (lambda v: v / 10000.0, "w/v"),
    "MG/G": (lambda v: v / 10.0, "w/w"),
    "G/G": (lambda v: v * 100.0, "w/w"),
    "%": (lambda v: v, "percent_literal"),
    "MG/ML": (lambda v: v / 10.0, "w/v"),
    "G/ML": (lambda v: v * 100.0, "w/v"),
}

MINERAL = ("ZINC OXIDE", "TITANIUM DIOXIDE")


def parse_actives(raw):
    """actives_raw -> list of {name, percent_ww, basis} + a parse report."""
    out, problems = [], []
    if not raw or not str(raw).strip():
        return out, ["empty"]
    # one row in the export is a leftover of the search UI, not a product
    if "Applied filters" in str(raw) or "SearchValues" in str(raw):
        return out, ["export_header_artifact"]
    # semicolon first (the real separator), comma only as a fallback
    parts = [t for t in re.split(r"\s*;\s*", str(raw)) if t.strip()]
    if len(parts) == 1 and "," in parts[0]:
        parts = [t for t in re.split(r",\s*(?=[A-Za-z])", parts[0]) if t.strip()]
    for tok in parts:
        tok = tok.strip().rstrip(".")
        m = TOKEN.match(tok)
        if not m:
            problems.append(f"unparsed:{tok[:60]}")
            out.append({"name": tok.upper(), "percent_ww": None,
                        "percent_basis": "unparsed", "raw": tok})
            continue
        name = re.sub(r"\s+", " ", m.group("name")).strip().upper()
        try:
            val = float(m.group("val"))
        except ValueError:
            problems.append(f"bad_number:{tok[:60]}")
            out.append({"name": name, "percent_ww": None,
                        "percent_basis": "bad_number", "raw": tok})
            continue
        fn, basis = CONVERT[m.group("unit").upper()]
        pct = fn(val)
        if pct > 100:
            problems.append(f"over_100:{name}={round(pct, 2)}")
            out.append({"name": name, "percent_ww": None,
                        "percent_basis": f"rejected_over_100:{round(pct, 2)}",
                        "raw": tok})
            continue
        out.append({"name": name, "percent_ww": round(pct, 4),
                    "percent_basis": basis, "raw": tok})
    return out, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--infile", default="data/canonical/au_sunscreens.json")
    ap.add_argument("--outfile", default=None, help="defaults to in-place")
    args = ap.parse_args()
    out_path = args.outfile or args.infile

    doc = json.load(open(args.infile, encoding="utf-8"))
    prods = doc["products"]

    stats = Counter()
    basis_count = Counter()
    zinc_check = {"agree": 0, "differ": [], "newly_filled": 0}

    for p in prods:
        actives, problems = parse_actives(p.get("actives_raw"))
        p["actives"] = actives
        p["n_actives"] = len(actives)
        p["actives_parse_problems"] = problems or None
        stats["with_actives"] += 1 if actives else 0
        for a in actives:
            basis_count[a["percent_basis"]] += 1

        resolved = [a for a in actives if a["percent_ww"] is not None]
        p["all_actives_resolved"] = bool(actives) and len(resolved) == len(actives)

        # zinc: cross-check the newly parsed value against the hand-collected one
        zn = next((a["percent_ww"] for a in resolved
                   if "ZINC OXIDE" in a["name"]), None)
        old = p.get("zinc_percent")
        if zn is not None:
            if old is None:
                zinc_check["newly_filled"] += 1
            elif abs(float(old) - zn) > 0.05:
                zinc_check["differ"].append((p.get("id"), old, zn))
            else:
                zinc_check["agree"] += 1
            p["zinc_percent"] = zn
            p["zinc_percent_source"] = "parsed_from_actives_raw"

        # mineral_only recomputed from the parsed names rather than trusted
        names = {a["name"] for a in actives}
        if names:
            p["mineral_only_parsed"] = all(
                any(mm in n for mm in MINERAL) for n in names)

    doc["schema_version"] = "2.2"
    doc.setdefault("notes", []).append(
        "v2.2: every active parsed from actives_raw with its unit. ARTG states "
        "mg/g (w/w) and occasionally mg/mL (w/v); the basis travels with each "
        "number and the two are never mixed. Unparseable tokens keep "
        "percent_ww = null rather than a guess.")
    json.dump(doc, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"products            : {len(prods)}")
    print(f"with parsed actives : {stats['with_actives']}")
    print(f"fully resolved      : {sum(1 for p in prods if p.get('all_actives_resolved'))}")
    print(f"basis breakdown     : {dict(basis_count)}")
    print(f"\nzinc cross-check vs the hand-collected column:")
    print(f"  agree        : {zinc_check['agree']}")
    print(f"  newly filled : {zinc_check['newly_filled']}")
    print(f"  DISAGREE     : {len(zinc_check['differ'])}")
    for i, o, n in zinc_check["differ"][:10]:
        print(f"     {i}: hand={o} parsed={n}")
    if zinc_check["differ"]:
        print("  ^ investigate before publishing: the hand column and the ARTG "
              "string disagree, and only one can be right.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

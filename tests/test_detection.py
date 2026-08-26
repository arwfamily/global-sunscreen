"""
tests/test_detection.py — what must and must not count as a reformulation.

Every test here is a false positive or false negative we would otherwise
ship. Run before pushing a change to core/ or an adapter:

    python tests/test_detection.py

A monitor that cries wolf is worse than no monitor: once a weekly report is
full of registry typos and date bumps, nobody reads the one line that says a
baby sunscreen quietly dropped its zinc.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fingerprint import fingerprint, classify          # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name)


def rec(jur="AU", actives=(), inactives=(), **kw):
    r = {"id": f"{jur}:TEST", "jurisdiction": jur,
         "actives": [{"name": n, "quantity": q, "unit": u}
                     for n, q, u in actives],
         "inactives": list(inactives)}
    r.update(kw)
    return r


def events(old, new):
    """Classify old -> new the way detect_reformulations.py does."""
    return classify(
        {k: old.get(k) for k in ("product_name", "company", "dosage_form",
                                 "spf_label", "status_active", "revised_date",
                                 "licence_date")},
        fingerprint(old), new, fingerprint(new))


def kinds(evs):
    return sorted(e["change"] for e in evs)


print("\n-- must NOT fire ------------------------------------------------")

# Australia prints excipients alphabetically. Re-exporting the same product
# in a different order is not a formulation change.
a = rec("AU", [("zinc oxide", 200, "mg/g")], ["glycerol", "beeswax", "silica"])
b = rec("AU", [("zinc oxide", 200, "mg/g")], ["silica", "glycerol", "beeswax"])
check("AU: excipient reorder is not a reformulation", events(a, b) == [])

# The same molecule under two register spellings.
a = rec("US", [("zinc oxide", 20, "%")], ["glycerol", "disodium edetate",
                                          "dl-alpha-tocopheryl acetate"])
b = rec("US", [("zinc oxide", 20, "%")], ["glycerin", "edetate disodium",
                                          "tocopheryl acetate"])
check("US: pharmacopoeial -> INCI renaming is not a reformulation",
      events(a, b) == [])

# mg/g and % are the same number on two scales.
a = rec("AU", [("zinc oxide", 250, "mg/g")], ["silica"])
b = rec("AU", [("zinc oxide", 25.0, "%")], ["silica"])
check("AU: mg/g vs % is not a concentration change", events(a, b) == [])

# Registers pad numbers differently between exports.
a = rec("CA", [("Zinc oxide", 20, "%")], ["Water"])
b = rec("CA", [("Zinc oxide", 20.0, "percent")], ["water"])
check("CA: 20 vs 20.0 vs case is not a change", events(a, b) == [])

print("\n-- must fire, as a REFORMULATION --------------------------------")

a = rec("AU", [("zinc oxide", 200, "mg/g")], ["silica"])
b = rec("AU", [("zinc oxide", 150, "mg/g")], ["silica"])
evs = events(a, b)
check("AU: zinc 20% -> 15% is a reformulation",
      kinds(evs) == ["reformulated"]
      and evs[0]["changes"]["active_concentration_changed"][0]["to"] == 15.0)

a = rec("US", [("zinc oxide", 20, "%")], ["water", "glycerin"])
b = rec("US", [("zinc oxide", 20, "%"), ("titanium dioxide", 4, "%")],
        ["water", "glycerin"])
evs = events(a, b)
check("US: a filter appears is a reformulation (highest severity)",
      kinds(evs) == ["reformulated"] and evs[0]["severity"] >= 5)

a = rec("CA", [("Zinc oxide", 20, "%")], ["Water", "Glycerin"])
b = rec("CA", [("Zinc oxide", 20, "%")], ["Water", "Glycerin", "Phenoxyethanol"])
evs = events(a, b)
check("CA: an excipient appears is a reformulation",
      kinds(evs) == ["reformulated"]
      and evs[0]["changes"]["inactive_added"] == ["phenoxyethanol"])

# Korea publishes no concentrations, but the order IS the concentration
# ranking, so a reorder is the only concentration signal Korea gives.
a = rec("KR", [], ["water", "zinc oxide", "glycerin"])
b = rec("KR", [], ["water", "glycerin", "zinc oxide"])
evs = events(a, b)
check("KR: ingredient order moved is a reformulation",
      kinds(evs) == ["reformulated"]
      and evs[0]["changes"]["inactive_reordered"])

print("\n-- must fire, but NOT as a reformulation ------------------------")

# Our own coverage improving. This is the one that would inflate every
# statistic if it were miscounted.
a = rec("AU", [("zinc oxide", 200, "mg/g")], [])
b = rec("AU", [("zinc oxide", 200, "mg/g")], ["silica", "glycerol"])
evs = events(a, b)
check("AU: first excipient list arriving is coverage, not reformulation",
      kinds(evs) == ["coverage_gain"])

# A register bumping a date, a sponsor renaming itself, a label revision.
a = rec("CA", [("Zinc oxide", 20, "%")], ["Water"],
        revised_date="2024-01-01", company="Old Co", product_name="X")
b = rec("CA", [("Zinc oxide", 20, "%")], ["Water"],
        revised_date="2026-08-01", company="New Co", product_name="X")
evs = events(a, b)
check("CA: revised_date + sponsor change is metadata, not reformulation",
      kinds(evs) == ["metadata"]
      and set(evs[0]["fields"]) == {"revised_date", "company"})

# Losing data we used to hold is a pipeline alarm, never a market event.
a = rec("AU", [("zinc oxide", 200, "mg/g")], ["silica", "glycerol"])
b = rec("AU", [("zinc oxide", 200, "mg/g")], [])
check("AU: an excipient list disappearing is a coverage LOSS",
      kinds(events(a, b)) == ["coverage_loss"])

# A hand-transcribed list changing needs a human before it is published.
a = rec("AU", [("zinc oxide", 200, "mg/g")], ["silica"],
        excipient_source="curated_json")
b = rec("AU", [("zinc oxide", 200, "mg/g")], ["silica", "glycerol"],
        excipient_source="curated_json")
evs = events(a, b)
check("AU: a change to a hand-transcribed list is flagged for review",
      evs and evs[0].get("needs_confirmation") is True)

# The register itself saying "no excipient list published" is a fact about
# the register, not a gap we should keep chasing.
a = rec("AU", [("zinc oxide", 200, "mg/g")], [],
        data_status="excipients_unavailable_on_artg")
check("AU: 'register publishes none' is distinguishable from 'not collected'",
      fingerprint(a)["coverage"] == "actives_only_confirmed"
      and fingerprint(rec("AU", [("zinc oxide", 200, "mg/g")], []))["coverage"]
      == "actives_only")

print("\n-- UNII identity (US corpus carries FDA substance codes) --------")

# FDA re-typing a name is not a reformulation when the UNII is unchanged.
a = {"id": "US:T", "jurisdiction": "US",
     "actives": [{"name": ".ALPHA.-TOCOPHEROL ACETATE", "unii": "WR1WPI7EW8",
                  "quantity": 5, "unit": "%"}],
     "inactives": ["WATER", "GLYCERIN"],
     "inactive_uniis": ["059QF0KO0R", "PDC6A3C0OX"]}
b = dict(a, actives=[{"name": "ALPHA-TOCOPHEROL ACETATE", "unii": "WR1WPI7EW8",
                      "quantity": 5.0, "unit": "%"}],
         inactives=["Water", "Glycerol"])
check("US: same UNII under a different name is not a reformulation",
      events(a, b) == [])

# A different substance is caught even when the printed name is unchanged.
c = dict(a, inactive_uniis=["059QF0KO0R", "8OMU3Q1M6Y"])
check("US: a different UNII under the same name IS a reformulation",
      kinds(events(a, c)) == ["reformulated"])

# Half-coded lists must degrade one ingredient at a time, not fail.
d = dict(a, inactive_uniis=["059QF0KO0R"])
e = dict(a, inactive_uniis=["059QF0KO0R"], inactives=["WATER", "GLYCEROL"])
check("US: a missing UNII falls back to the name without firing",
      events(d, e) == [])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed: " + ", ".join(FAIL))
    sys.exit(1)

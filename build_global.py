"""
build_global.py — one file to query, one vocabulary, one set of caveats.

Each collector writes its own canonical file in its own register's terms.
This merges them into:

    data/canonical/global_sunscreens.jsonl   every product, normalised names
    data/canonical/global_summary.json       counts, coverage, ingredient index

Two things it adds that no single-country file can have:

  1. A shared ingredient vocabulary. GLYCEROL (AU), Glycerin (CA/US) and
     글리세린 (KR) become one row. Without this, every cross-country count is
     wrong in the same direction — it undercounts what countries share.

  2. Shared-formulation clusters. Products whose full excipient set is
     identical are grouped, and the cluster is marked cross_company when the
     members belong to different companies. This is the measurement behind
     "Same Formula, Different Label": in Australia, 22% of sunscreens share
     a formulation with a product from another company.

Every record keeps its jurisdiction's own resolution flags, so a downstream
count can never silently mix a register that publishes concentrations with
one that does not.

Run:  python build_global.py
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from core.fingerprint import fingerprint, profile_for, remember_labels
from core.normalize import normalize_list, normalize_name

ROOT = Path(__file__).parent
CANON = ROOT / "data" / "canonical"
OUT = CANON / "global_sunscreens.jsonl"
SUMMARY = CANON / "global_summary.json"

# What each register actually publishes. Printed with every summary so a
# number is never read as if it meant the same thing in four countries.
PUBLISHES = {
    "US": "full inactive list in formulation order, every ingredient with a "
          "UNII; active strengths are filed WITHOUT their unit upstream, so "
          "percent_w_w is null and percent_estimate carries an assumption "
          "(see docs/upstream_unit_patch.md)",
    "CA": "actives with exact %, inactive names only (mineral filters only — "
          "chemical-filter sunscreens are DIN/DPD and not in LNHPD)",
    "AU": "actives with mg/g, excipients alphabetical (hand-read from PDFs)",
    "KR": "no concentrations; full list in legally-mandated descending order",
}


def load(jur):
    p = CANON / f"{jur.lower()}_ingredients.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.open() if l.strip()]


def main():
    verified = {}
    vp = CANON / "_verified.json"
    if vp.exists():
        verified = json.loads(vp.read_text())

    jurs = sorted(p.name.split("_")[0].upper()
                  for p in CANON.glob("*_ingredients.jsonl")
                  if not p.name.startswith("global"))
    if not jurs:
        raise SystemExit("[!] no canonical files yet — run the collectors first")

    records, by_jur = [], {}
    for jur in jurs:
        rows = load(jur)
        by_jur[jur] = rows
        prof = profile_for(jur)
        for r in rows:
            remember_labels(r)
            fp = fingerprint(r)
            # Read the concentration from the RECORD, never from the
            # fingerprint. The fingerprint's number is a comparison value —
            # for the US it is the raw filed strength, which is not a
            # percentage (see docs/upstream_unit_patch.md). Printing it as
            # percent_w_w is exactly the mistake this project keeps warning
            # other people about: it turns a 216 mg/g zinc into "216%".
            actives = [{"name": a.get("name"),
                        "unii": a.get("unii"),
                        "percent_w_w": a.get("percent_w_w"),
                        "percent_estimate": a.get("percent_estimate"),
                        "estimate_basis": a.get("estimate_basis")}
                       for a in r.get("actives") or []]
            records.append({
                "global_id": r["id"],
                "jurisdiction": jur,
                "authority": r.get("authority"),
                "product_name": r.get("product_name"),
                "company": r.get("company"),
                "spf_label": r.get("spf_label"),
                "baby_labelled": bool(r.get("baby_flag_source")),
                # Human-readable filter names, not the fingerprint's
                # identity strings.
                "uv_filters": sorted(r.get("uv_filters") or []),
                "actives": actives,
                "mineral_only": r.get("mineral_only"),
                "zinc_percent": r.get("zinc_percent"),
                "zinc_percent_is_estimate": bool(
                    r.get("zinc_percent_is_estimate")),
                "zinc_position": r.get("zinc_position"),
                "ingredients": normalize_list(r.get("inactives") or []),
                "ingredients_as_published": r.get("inactives") or [],
                "n_ingredients": fp["n_inactives"],
                "coverage": fp["coverage"],
                "concentrations_published": prof["actives_concentration"],
                "order_is_data": prof["inactive_order"],
                "fp_full": fp["fp_full"],
                "fp_inactives": fp["fp_inactives"],
                "status_active": r.get("status_active"),
                "source_url": r.get("source_url"),
                "observed": r.get("observed"),
                "collection_method": r.get("collection_method")
                                     or r.get("excipient_source") or "api",
            })

    # ---- shared-formulation clusters, within a jurisdiction ---------------
    # Only products whose excipient list we actually hold can be clustered;
    # comparing on an empty list would put every uncollected product in one
    # enormous fake cluster.
    clusters = defaultdict(list)
    for rec in records:
        if rec["coverage"] == "full" and rec["n_ingredients"] >= 5:
            clusters[(rec["jurisdiction"], rec["fp_inactives"])].append(rec)
    cluster_stats = {j: {"clusters": 0, "products": 0,
                         "cross_company_clusters": 0,
                         "cross_company_products": 0} for j in jurs}
    for (jur, fpi), members in clusters.items():
        if len(members) < 2:
            continue
        companies = {(m["company"] or "").strip().lower() for m in members}
        cross = len(companies) > 1
        cid = f"{jur}-FORM-{fpi[:8]}"
        for m in members:
            m["formulation_cluster"] = cid
            m["formulation_shared_with"] = len(members) - 1
            m["formulation_cross_company"] = cross
        cluster_stats[jur]["clusters"] += 1
        cluster_stats[jur]["products"] += len(members)
        if cross:
            cluster_stats[jur]["cross_company_clusters"] += 1
            cluster_stats[jur]["cross_company_products"] += len(members)

    with OUT.open("w") as f:
        for r in sorted(records, key=lambda x: x["global_id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- summary ---------------------------------------------------------
    vocab = Counter()
    for r in records:
        vocab.update(set(r["ingredients"]))
    per_jur = {}
    for jur in jurs:
        rows = [r for r in records if r["jurisdiction"] == jur]
        full = [r for r in rows if r["coverage"] == "full"]
        # Never mix a measured concentration with an estimated one in the
        # same median. Australia and Canada publish real numbers; the US
        # number is currently derived from a unitless strength.
        estimated = any(r.get("zinc_percent_is_estimate") for r in rows)
        zinc = [r["zinc_percent"] for r in rows
                if isinstance(r["zinc_percent"], (int, float))
                and 0.5 <= r["zinc_percent"] <= 40]
        per_jur[jur] = {
            "products": len(rows),
            "with_full_ingredients": len(full),
            "mineral_only": sum(1 for r in rows if r["mineral_only"]),
            "baby_labelled": sum(1 for r in rows if r["baby_labelled"]),
            "median_ingredients": (sorted(r["n_ingredients"] for r in full)
                                   [len(full) // 2] if full else None),
            "zinc_median_percent": (sorted(zinc)[len(zinc) // 2]
                                    if zinc else None),
            "zinc_median_is_estimate": estimated,
            "publishes": PUBLISHES.get(jur, "unknown"),
            "last_verified": (verified.get(jur) or {}).get("last_verified"),
            "shared_formulation": cluster_stats[jur],
        }

    # An ingredient present in every jurisdiction we hold is a genuine
    # global standard; one that is huge in a single country is a national
    # habit. Both are content; conflating them is not.
    seen_in = defaultdict(set)
    for r in records:
        for ing in set(r["ingredients"]):
            seen_in[ing].add(r["jurisdiction"])
    universal = sorted(i for i, js in seen_in.items() if len(js) == len(jurs))

    summary = {
        "generated_from": {j: len(by_jur[j]) for j in jurs},
        "total_products": len(records),
        "total_with_full_ingredients":
            sum(1 for r in records if r["coverage"] == "full"),
        "distinct_ingredients_after_normalisation": len(vocab),
        "ingredients_present_in_every_jurisdiction": universal[:200],
        "top_ingredients": vocab.most_common(40),
        "per_jurisdiction": per_jur,
        "caveats": [
            "Counts are comparable only where the registers publish the same "
            "thing — see per_jurisdiction.publishes before quoting a share.",
            "Canada covers mineral-filter sunscreens only (NHP). Chemical "
            "sunscreens are regulated as drugs (DIN) and are not in LNHPD.",
            "US concentrations are not publishable yet: the upstream "
            "scraper drops the SPL strength unit, so 50 may be 5% or 50%. "
            "Ingredient presence, filter systems and formulation clusters "
            "are unaffected; percentages are not.",
            "The US corpus is cast on 19 UV-filter UNIIs, so a sunscreen "
            "using only a filter outside that set is not collected.",
            "Australia's excipient lists are alphabetical, so no "
            "concentration can be inferred from their order.",
            "Korea publishes no concentrations; ingredient position is a "
            "proxy, not a measurement.",
        ],
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1))

    print(f"[*] {len(records)} products -> {OUT.name}")
    for jur, s in per_jur.items():
        cs = s["shared_formulation"]
        share = (f"{cs['cross_company_products']}/{s['with_full_ingredients']}"
                 if s["with_full_ingredients"] else "n/a")
        print(f"    {jur}: {s['products']:>5} products, "
              f"{s['with_full_ingredients']:>5} with full lists, "
              f"median {s['median_ingredients']} ingredients, "
              f"cross-company shared formulations {share}")
    print(f"[*] {len(vocab)} distinct ingredients after normalisation; "
          f"{len(universal)} appear in all {len(jurs)} jurisdictions")
    print(f"[*] summary -> {SUMMARY.name}")


if __name__ == "__main__":
    main()

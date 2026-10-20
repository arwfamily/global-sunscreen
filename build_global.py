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
from core.scope_rules import scope_reason
import re

ROOT = Path(__file__).parent
CANON = ROOT / "data" / "canonical"
OUT = CANON / "global_sunscreens.jsonl"
EXCLUDED = CANON / "global_excluded.jsonl"
# Product-name baby/kids words, the same rule in every country. Canada's
# "recommended population: children" is a suitability statement on most
# sunscreen licences, not a baby product, so it is kept as its own field.
BABY_NAME = re.compile(r"\b(?:BAB(?:Y|IES)|INFANTS?|NEWBORN|TODDLERS?|KIDS?|KIDZ|CHILD(?:REN)?(?:'S)?|JUNIOR|"
                       r"LITTLE ONES|B[EÉ]B[EÉ]S?|ENFANTS?|NI[ÑN]OS)\b|아기|베이비|키즈|유아|어린이|아이(?:용|들)", re.I)
PCT_UNIT = re.compile(r"^\s*(?:%|percent)\s*(?:\((?:w/w|p/p)\)|p/p|w/w)?\s*$", re.I)


def ca_percent(a):
    """LNHPD files strength as quantity + unit; a weight-per-weight percent is the
    label %. w/v and v/v are not w/w, so they stay unknown."""
    if a.get("percent_w_w") is not None:
        return a["percent_w_w"]
    if a.get("quantity") is not None and PCT_UNIT.match(a.get("unit") or ""):
        q = a["quantity"]
        return q if 0 < q <= 40 else None
    return None
SUMMARY = CANON / "global_summary.json"

# What each register actually publishes. Printed with every summary so a
# number is never read as if it meant the same thing in four countries.
PUBLISHES = {
    "US": "label-verified inactive list (printed Drug Facts + SPL table, label "
          "order) from the US release; active % w/w from the printed Drug Facts panel",
    "CA": "actives with exact % w/w (LNHPD quantity), inactive names only "
          "(natural health product licences: mineral filters; chemical-filter "
          "sunscreens are DIN/DPD and not in LNHPD)",
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

    records, by_jur, excluded = [], {}, []
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
            v = r.get("verified") if jur == "US" else None
            why_out = scope_reason(r.get("product_name") or "")
            if jur != "US" and why_out:
                excluded.append({"global_id": r["id"], "jurisdiction": jur,
                                 "product_name": r.get("product_name"),
                                 "company": r.get("company"), "excluded_reason": why_out})
                continue
            actives = [{"name": a.get("name"),
                        "unii": a.get("unii"),
                        "percent_w_w": ca_percent(a) if jur == "CA" else a.get("percent_w_w"),
                        "percent_estimate": a.get("percent_estimate"),
                        "estimate_basis": a.get("estimate_basis")}
                       for a in r.get("actives") or []]
            # `ingredients` (the cross-country vocabulary) stays on the register's
            # controlled names: for the US the FDA substance names. The US label-
            # verified list (printed Drug Facts + filing, label order, duplicates
            # under another name removed) is carried as ingredients_label_verified.
            published = r.get("inactives") or []
            label_list = (v.get("inactives") or None) if v else None
            normalised = normalize_list(published)
            if len(normalised) != len(published):
                # An ingredient must never leave the record between the
                # register and us. If cleaning ever eats one, stop the build
                # rather than publish a formulation that is missing a line.
                raise SystemExit(
                    f"[!] {r['id']}: {len(published)} ingredients published, "
                    f"{len(normalised)} after normalisation — refusing to "
                    f"build a store that loses an ingredient. Check "
                    f"core/normalize.py against: {published}")
            records.append({
                "global_id": r["id"],
                "jurisdiction": jur,
                "authority": r.get("authority"),
                "product_name": r.get("product_name"),
                "company": r.get("company"),
                "spf_label": r.get("spf_label"),
                "baby_labelled": (bool(v.get("is_baby_kids")) if v else
                                  bool(r["baby_reviewed"]) if r.get("baby_reviewed") is not None else
                                  bool(BABY_NAME.search(r.get("product_name") or ""))),
                "population_includes_children": (bool(r.get("baby_flag_source"))
                                                 if jur == "CA" else None),
                # Human-readable filter names, not the fingerprint's
                # identity strings.
                "uv_filters": sorted(r.get("uv_filters") or []),
                "actives": actives,
                "mineral_only": ((v.get("filter_type") == "mineral_only") if v
                                 else r.get("mineral_only")),
                "filter_type": v.get("filter_type") if v else None,
                "label_check": v.get("label_check") if v else None,
                "recalls_matched": v.get("recalls_matched") if v else None,
                "zinc_percent": r.get("zinc_percent"),
                "zinc_percent_is_estimate": bool(
                    r.get("zinc_percent_is_estimate")),
                "zinc_position": r.get("zinc_position"),
                "ingredients": normalised,
                "ingredients_as_published": published,
                "ingredients_label_verified": label_list,
                "n_ingredients": len(label_list) if label_list else fp["n_inactives"],
                "n_ingredients_register": fp["n_inactives"],
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
        # clusters compare the register's own list, the one the fingerprint is built on
        if rec["coverage"] == "full" and rec["n_ingredients_register"] >= 5:
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

    with EXCLUDED.open("w") as f:
        for r in sorted(excluded, key=lambda x: x["global_id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
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
            "licence_or_listing_active": sum(1 for r in rows if r.get("status_active") is not False),
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
            "US active percentages come from the printed Drug Facts panel. US "
            "`ingredients` uses the FDA filing's substance names (a controlled "
            "vocabulary for cross-country counts); the label-verified list a "
            "parent reads is `ingredients_label_verified`.",
            "The US corpus is every DailyMed SPL with a UV-filter active (UNII "
            "search plus a title sweep of all SPL listings).",
            "SPF makeup, SPF lip products and diaper creams are out of scope in "
            "every jurisdiction, by the same rules (global_excluded.jsonl).",
            "baby_labelled: US and Korea are reviewed decisions (product name, or "
            "a baby/kids-care brand line); Australia and Canada are the product "
            "name. Canada's recommended-population field is kept as "
            "population_includes_children.",
            "Korea is hand-collected (mostly baby/kids sunscreens, plus the adult "
            "ones met on the way; not the whole market); Korean label "
            "names are mapped to INCI by two agreeing readings "
            "(data/regulatory/kr_inci_map.json).",
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

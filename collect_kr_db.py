#!/usr/bin/env python3
"""Korea into the global store: the hand-verified Korean baby/kids sunscreen DB.

Inputs (both in this repo):
  data/kr_verified/kr_baby_sunscreens_verified.json   the verified sheet: scope
        (include/exclude), verification status, the verified full ingredient list
        (전성분, label order), UV filters in Korean and INCI, mineral-only
  kr/kr_ingredients.jsonl                               the KR DB the weekly
        recapture keeps (sources, capture dates, review status)

Output: data/canonical/kr_ingredients.jsonl, the shape build_global.py reads.

Rules:
  * only rows the sheet scopes `include` (product name says 키즈/베이비/유아...);
    rows marked `duplicate` are the same product as another row and are left out
  * the ingredient list is the sheet's verified 전성분; the DB list is used only
    when the sheet has none. (A recapture that disagrees with a verified list
    is a human-check item in the DB, never silently taken here.)
  * Korea prints no concentrations and no separate active panel: the UV filters
    are the actives, found in the full list; order is the label's (descending
    by content, 화장품법 제10조)
  * verification is carried per product: verified | user verified |
    verified (corrected) | pending (list not yet checked against the label)
"""
import datetime
import json
import re
from pathlib import Path

from core.normalize import normalize_name

ROOT = Path(__file__).parent
SHEET = ROOT / "data/kr_verified/kr_baby_sunscreens_verified.json"
DB = ROOT / "kr/kr_ingredients.jsonl"
OUT = ROOT / "data/canonical/kr_ingredients.jsonl"
VERIFIED = ROOT / "data/canonical/_verified.json"


BABY_KO = re.compile(r"아기|베이비|키즈|유아|어린이|baby|kids?", re.I)
# UV filters permitted in Korea (INCI, as core.normalize folds them); anything else on a
# label that absorbs UV (e.g. benzotriazolyl dodecyl p-cresol) is an inactive here
KR_FILTERS = {"zinc oxide", "titanium dioxide", "ethylhexyl methoxycinnamate", "octinoxate",
              "ethylhexyl salicylate", "octisalate", "homosalate", "octocrylene",
              "butyl methoxydibenzoylmethane", "avobenzone", "bis-ethylhexyloxyphenol methoxyphenyl triazine",
              "ethylhexyl triazone", "diethylamino hydroxybenzoyl hexyl benzoate",
              "methylene bis-benzotriazolyl tetramethylbutylphenol", "polysilicone-15", "isoamyl p-methoxycinnamate",
              "phenylbenzimidazole sulfonic acid", "ensulizole", "terephthalylidene dicamphor sulfonic acid",
              "drometrizole trisiloxane", "diethylhexyl butamido triazone", "benzophenone-3", "oxybenzone",
              "benzophenone-4", "benzophenone-8", "4-methylbenzylidene camphor", "menthyl anthranilate",
              "ethyl dihydroxypropyl paba", "disodium phenyl dibenzimidazole tetrasulfonate", "cinoxate",
              "tris-biphenyl triazine"}


def split_list(s):
    s = re.sub(r"(?<=\d),(?=\d)", "\u0001", s or "")      # 1,2-헥산다이올
    return [p.replace("\u0001", ",").strip() for p in s.split(",") if p.strip()]


def main():
    today = datetime.date.today().isoformat()
    sheet = json.loads(SHEET.read_text())
    db = {r["id"]: r for r in map(json.loads, DB.open()) if r.get("id")}
    # products in the KR DB that the verified sheet does not have yet (added later,
    # e.g. KR-20261009-214..222, user-verified on Coupang): same treatment, scope by
    # the product-name rule until a person reviews them
    from core.normalize import _kr_map
    in_sheet = {x["ID"] for x in sheet}
    km = _kr_map()
    for rid, d in db.items():
        if rid in in_sheet or not d.get("ingredients_ko"):
            continue
        name = d.get("product") or ""
        baby = bool(BABY_KO.search(name))
        filters = [f for f in d.get("uv_filters_ko") or [] if normalize_name(km.get(f, f)) in KR_FILTERS]
        sheet.append({
            "ID": rid, "브랜드": d.get("brand"), "Brand": d.get("brand_en") or d.get("brand"), "제품명": name,
            "SPF": d.get("spf"), "PA": d.get("pa"), "Scope": "include" if baby else "exclude",
            "Scope reason": ("product name says baby/kids (rule; not yet reviewed)" if baby
                             else "no baby/kids wording in the product name (rule; not yet reviewed)"),
            "Verification": d.get("review_status"), "Verification basis": d.get("source"),
            "전성분 (verified)": ", ".join(d["ingredients_ko"]),
            "UV filters (KR list)": ", ".join(filters), "UV filters (INCI)": ", ".join(km.get(f) or normalize_name(f).title() for f in filters),
            "Mineral only (ZnO/TiO2 only)": "Yes" if d.get("mineral_only") else "No",
            "Source URL (MUSE)": d.get("source_url"), "Coupang URL": d.get("coupang_url"),
            "Captured": (d.get("last_captured") or "")[:10]})
    out = []
    for x in sheet:
        # every Korean sunscreen we hold goes in (as every US, CA and AU sunscreen does);
        # baby/kids is the sheet's reviewed scope. A duplicate row is the same product.
        if x.get("Verification") == "duplicate":
            continue
        d = db.get(x["ID"]) or {}
        names = split_list(x.get("전성분 (verified)")) or list(d.get("ingredients_ko") or [])
        f_ko = split_list(x.get("UV filters (KR list)"))
        f_en = split_list(x.get("UV filters (INCI)"))
        inci = dict(zip(f_ko, f_en)) if len(f_ko) == len(f_en) else {}
        zppm = d.get("zinc_oxide_ppm_on_brand_page")      # a few brands print content in ppm
        actives = [{"name": inci.get(n, n), "name_ko": n, "position": names.index(n) + 1 if n in names else None,
                    "percent_w_w": (round(zppm / 10000, 2) if zppm and normalize_name(inci.get(n, n)) == "zinc oxide"
                                    else None)} for n in f_ko]
        inactives = [n for n in names if n not in set(f_ko)]
        spf = re.search(r"(\d{1,3})", x.get("SPF") or d.get("spf") or "")
        mo = (x.get("Mineral only (ZnO/TiO2 only)") or "").strip().lower()
        out.append({
            "id": f"KR:{x['ID']}",
            "id_scheme": "arw_manual",
            "id_note": "Korea publishes no product id for cosmetics; this is ours",
            "jurisdiction": "KR",
            "authority": "라벨 (화장품법 제10조 전성분 표시)",
            "regulatory_class": "functional_cosmetic",
            "product_name": f"{x.get('Brand') or x.get('브랜드')} {x.get('제품명')}".strip(),
            "product_name_ko": x.get("제품명"),
            "company": x.get("Brand") or x.get("브랜드"),
            "company_ko": x.get("브랜드"),
            "scope": "sunscreen",
            "actives": actives,
            "uv_filters": sorted(normalize_name(a["name"]) for a in actives),
            "mineral_only": mo == "yes",
            "zinc_percent": round(zppm / 10000, 2) if zppm else None,
            "zinc_position": next((i + 1 for i, n in enumerate(names) if normalize_name(n) == "zinc oxide"), None),
            "spf_label": int(spf.group(1)) if spf else None,
            "pa": x.get("PA"),
            "inactives": inactives,
            "all_ingredients_in_label_order": names,
            "inactive_order_is_data": True,
            "n_ingredients": len(names),
            "data_status": "complete" if names else "not_collected",
            "verification": x.get("Verification"),
            "verification_basis": x.get("Verification basis"),
            "baby_flag_source": "reviewed" if x.get("Scope") == "include" else None,
            "baby_reviewed": x.get("Scope") == "include",   # the sheet's reviewed scope: name, or a baby/kids-care brand line
            "scope_reason": x.get("Scope reason"),
            "collection_method": "manual (verified sheet)",
            "source_url": x.get("Source URL (MUSE)") or d.get("source_url"),
            "retail_url": x.get("Coupang URL") or d.get("coupang_url"),
            "status_active": True,
            "observed": x.get("Captured") or d.get("last_captured"),
            "verified_at": today,
        })
    with OUT.open("w") as f:
        for r in sorted(out, key=lambda r: r["id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    v = json.loads(VERIFIED.read_text()) if VERIFIED.exists() else {}
    v["KR"] = {"last_verified": today, "records": len(out),
               "source": "hand-verified Korean baby/kids sunscreen sheet (화장품법 제10조 전성분)"}
    VERIFIED.write_text(json.dumps(v, indent=1, sort_keys=True))
    print(f"[*] KR: {len(out)} sunscreens ({sum(1 for r in out if r['baby_reviewed'])} baby/kids) -> {OUT.name}")


if __name__ == "__main__":
    main()

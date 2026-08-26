"""
adapters/kr_label.py — Korean sunscreen labels into the canonical shape.

Korea is the odd one out and it is worth being precise about why.

A sunscreen in Korea is a 기능성화장품 (functional cosmetic), not a drug. The
formulation filed with 식약처 is a trade secret and is never published, so
there is no government product register to walk — we checked all three
data.go.kr datasets and none of them return ingredients. But 화장품법 제10조
requires the FULL ingredient list on the product itself, in descending
order of content. So the data is legally public; it just lives at the point
of sale instead of in a register.

Consequences the rest of the pipeline must respect:
  - no concentrations (a handful of brands volunteer ppm — parsed below)
  - ORDER IS DATA. It is the only concentration signal Korea gives, so a
    reordering is a real reformulation event here, unlike in AU/CA.
  - names are Korean standard names, folded to INCI by core.normalize
    (fully, once the KCIA 표준화 명칭 목록 CSV is dropped in)
  - there is no official product id, so ids are ours and say so:
    KR-LABEL-#### with id_scheme "arw_manual"
"""

import re

# "징크옥사이드(192,000ppm)" — a few brands publish content this way.
PPM_RE = re.compile(r"\(?\s*([\d,]+(?:\.\d+)?)\s*(ppm|%)\s*\)?", re.I)
# Colour Index numbers are printed next to the pigment in Korea.
CI_RE = re.compile(r"\(?\s*ci\s*\d{5}\s*\)?", re.I)
NOISE = re.compile(r"^\s*(전성분|성분|ingredients?)\s*[:：]", re.I)

MINERAL_KO = {"zinc oxide", "titanium dioxide"}
UV_FILTERS = {
    "zinc oxide", "titanium dioxide", "octinoxate", "octisalate",
    "avobenzone", "octocrylene", "homosalate", "oxybenzone", "ensulizole",
    "bemotrizinol", "bisoctrizole", "ethylhexyl triazone",
    "diethylamino hydroxybenzoyl hexyl benzoate", "polysilicone-15",
}
# Salicylates that are NOT UV filters. Without this list butyloctyl
# salicylate — in a third of Korean baby sunscreens — reads as a filter and
# every mineral-only count is wrong.
NOT_FILTERS = {"butyloctyl salicylate", "iron oxides", "salicylic acid"}


def split_ingredients(text):
    """Split a Korean label string into ingredient names.

    Two label habits break a naive split(','):
      1. numbers with thousands separators — 1,2-헥산다이올 and (192,000ppm)
      2. some brands paste "성분: 기능" pairs with no comma at all
    """
    if not text:
        return []
    s = str(text).replace("\u2028", ",").replace("\u2029", ",")
    s = NOISE.sub("", s)
    s = s.replace("·", ",").replace("／", ",").replace("|", ",")
    # protect "1,2-" and "2,3-" style locants before splitting on commas
    s = re.sub(r"(?<=\d),(?=\d\s*-)", "\u0001", s)
    # protect thousands separators inside a parenthesised quantity
    s = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "\u0002", s)
    parts = [p for p in re.split(r"[,\n;]+", s)]
    if len(parts) <= 2:                      # no commas: try newline/space runs
        parts = re.split(r"\s{2,}|\n", s)
    out = []
    for p in parts:
        p = p.replace("\u0001", ",").replace("\u0002", ",").strip()
        p = re.sub(r"\s*[:：]\s*[^,]*$", "", p) if "：" in p or ":" in p else p
        if len(p) > 1:
            out.append(p)
    return out


def parse_one(raw):
    """-> (clean name, percent or None). Percent only when the label gave it."""
    name = str(raw).strip()
    pct = None
    m = PPM_RE.search(name)
    if m:
        val = float(m.group(1).replace(",", ""))
        pct = round(val / 10000.0, 4) if m.group(2).lower() == "ppm" else val
        name = PPM_RE.sub("", name)
    name = CI_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" ,;.:()")
    return name, pct


def build_record(row, observed=None, seq=None):
    """row: {product_name, ingredients_text, brand?, spf?, url?, source_note?}"""
    from core.normalize import normalize_name       # local: avoids a cycle

    names, pcts = [], {}
    for piece in split_ingredients(row.get("ingredients_text")):
        nm, pct = parse_one(piece)
        if not nm:
            continue
        names.append(nm)
        if pct is not None:
            pcts[normalize_name(nm)] = pct

    norm = [normalize_name(n) for n in names]
    filters = [n for n in norm if n in UV_FILTERS and n not in NOT_FILTERS]
    actives, inactives = [], []
    for original, n in zip(names, norm):
        if n in filters and not any(a["name"] == original for a in actives):
            actives.append({"name": original, "quantity": pcts.get(n),
                            "unit": "%" if pcts.get(n) is not None else None,
                            "percent_w_w": pcts.get(n),
                            "position": norm.index(n) + 1})
        else:
            inactives.append(original)

    pname = str(row.get("product_name") or "").strip()
    spf = row.get("spf") or (re.search(r"SPF\s*(\d{1,3})", pname, re.I).group(1)
                             if re.search(r"SPF\s*(\d{1,3})", pname, re.I) else None)
    fset = set(filters)
    rec = {
        "id": row.get("id") or f"KR-LABEL-{seq:04d}",
        "id_scheme": "arw_manual",
        "id_note": "Korea publishes no product id for cosmetics; this is ours",
        "jurisdiction": "KR",
        "authority": "라벨 (화장품법 제10조 전성분 표시)",
        "regulatory_class": "functional_cosmetic",
        "product_name": pname,
        "company": str(row.get("brand") or "").strip(),
        "scope": "sunscreen",
        "actives": actives,
        "uv_filters": sorted(fset),
        "mineral_only": bool(fset) and fset <= MINERAL_KO,
        "zinc_percent": pcts.get("zinc oxide"),
        # Korea prints no concentration, but the list is in descending
        # order by law, so where zinc sits IS the concentration signal.
        # Position 2 (straight after water) is a high load.
        "zinc_position": next((i + 1 for i, n in enumerate(norm)
                               if n == "zinc oxide"), None),
        "spf_label": int(spf) if str(spf).isdigit() else None,
        "inactives": inactives,
        "all_ingredients_in_label_order": names,
        "inactive_order_is_data": True,
        "n_ingredients": len(names),
        "data_status": "complete" if names else "not_collected",
        "collection_method": "manual",
        "source_url": row.get("url"),
        "source_note": row.get("source_note") or "brand/retailer product page",
        "observed": observed,
        "verified_at": observed,
    }
    if re.search(r"(baby|아기|베이비|키즈|kids?|어린이|유아)", pname, re.I):
        rec["baby_flag_source"] = "product_name"
    return rec

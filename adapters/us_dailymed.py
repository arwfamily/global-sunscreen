"""
adapters/us_dailymed.py — FDA DailyMed (SPL) records into the canonical shape.

Source: the tinysafe-dailymed-scraper-v2 corpus
(data/canonical/us_sunscreens.jsonl, 13,285 SPLs as of 2026-08-26). It
replaced a 520-product feed that had been pre-filtered to 100%-mineral baby
products — a filter that silently made every "does the US market use X"
count circular. The new net is cast on UV-filter UNIIs, so chemical filters
and hidden boosters are in it for the first time.

What that upgrade gives this repo, beyond ten times the products:

  **Every ingredient carries a UNII.** UNII is FDA's substance identifier —
  a government-issued code for the molecule, not a name. It is the join key
  we have been approximating with a synonym table: GLYCEROL (AU), Glycerin
  (US), 글리세린 (KR) are three strings and one UNII. Where a record has a
  UNII we fingerprint on that, so an SPL that re-types a name cannot look
  like a reformulation, and a cross-country match cannot be missed because
  two registers spell a substance differently.

Scope, and why it is not "everything in the file": a net cast on zinc oxide
catches diaper creams, calamine lotion and lipstick. The upstream corpus
labels those (`category`), and this adapter keeps the sunscreen categories
by default. Excluded records are written to data/canonical/us_excluded.jsonl
with their reason, never silently dropped — an empty bucket and an
unexamined bucket must not look the same.
"""

import re

SPF_RE = re.compile(r"\bSPF\s*(\d{1,3})\b", re.I)
MINERAL_UNII = {"SOI2LOH54Z": "zinc oxide", "15FIX9V2JP": "titanium dioxide"}
MINERAL_NAMES = {"zinc oxide", "titanium dioxide"}
# Categories that are sunscreens for our purposes. Makeup with SPF and lip
# balms are real UV products and interesting for trend work, but mixing them
# into a "sunscreen market" number would inflate it, so widening is a
# deliberate act: US_CATEGORIES=sunscreen,makeup,lip_balm
DEFAULT_CATEGORIES = ("sunscreen",)


def _strength(v):
    """The raw number the SPL printed. None stays None: a missing strength
    is not zero percent."""
    if v in (None, ""):
        return None
    try:
        return round(float(str(v).strip().rstrip("%")), 4)
    except ValueError:
        return None


# ---- the unit problem, stated plainly --------------------------------------
# The upstream scraper reads <numerator value="..."> and does NOT read its
# unit= attribute or the <denominator>. So "50" on an octisalate is 50 mg/g
# (5%) and "20" on a zinc oxide is probably 20%, and the file cannot tell
# them apart. 43% of in-scope products carry a value that is impossible as a
# percentage, which is how we found this.
#
# Rather than guess into the field everything else reads, we split it:
#   strength_raw          the number, as filed
#   percent_w_w           null until the unit is known — no invented numbers
#   percent_estimate      a documented reading, with its assumption attached
#   concentration_status  why percent_w_w is null
#
# Change detection compares strength_raw, so it is unaffected: the same
# product filed on the same scale two months apart still shows a real move.
# Only the reporting side has to wait for the upstream fix (see
# docs/upstream_unit_patch.md).
PLAUSIBLE_PERCENT = 30.0      # no UV filter is monographed above 25%
MG_PER_G_CEILING = 500.0      # 500 mg/g = 50%


def _estimate_percent(v):
    if v is None:
        return None, None
    if v <= PLAUSIBLE_PERCENT:
        return v, "assumed_percent"
    if v <= MG_PER_G_CEILING:
        return round(v / 10.0, 4), "assumed_mg_per_g"
    return None, "out_of_range"


def build_record(p, observed=None, corpus_version=None):
    setid = str(p.get("setid") or "").strip()
    actives, inactives, inactive_uniis = [], [], []

    for a in p.get("active_ingredients") or []:
        name = str(a.get("name") or "").strip()
        if not name:
            continue
        raw = _strength(a.get("strength"))
        # The upstream unit fix landed on 2026-08-26: SPL quantities are now
        # read as the RATIO they are (numerator + unit over denominator +
        # unit) and converted. The field is `percent_ww`; `percent_w_w` is
        # accepted too so a rename upstream cannot silently blank the axis.
        upstream_pct = _strength(a.get("percent_ww"))
        if upstream_pct is None:
            upstream_pct = _strength(a.get("percent_w_w"))
        pct_basis = a.get("percent_basis")
        est, basis = ((upstream_pct, pct_basis or "upstream_percent")
                      if upstream_pct is not None else _estimate_percent(raw))
        actives.append({"name": name,
                        "unii": a.get("unii") or None,
                        "strength_raw": raw,
                        # quantity is what the fingerprint compares: the
                        # published percentage once there is one, and until
                        # then the raw filed number (stable per product, so
                        # a real move still shows). unit is only asserted
                        # when it is actually known.
                        "quantity": upstream_pct if upstream_pct is not None else raw,
                        "unit": "%" if upstream_pct is not None else None,
                        "percent_w_w": upstream_pct,
                        "percent_estimate": est,
                        "estimate_basis": basis,
                        # Kept so a reader can see HOW the percentage was
                        # reached. Roughly half of US sunscreen actives are
                        # filed per volume (mg/mL), so their "percent" is
                        # w/v — equal to w/w only where density is 1.
                        "percent_basis": pct_basis,
                        "strength_unit": a.get("strength_unit"),
                        "denominator": a.get("denominator"),
                        "denominator_unit": a.get("denominator_unit")})
    for i in p.get("inactive_ingredients") or []:
        if isinstance(i, dict):
            name, unii = str(i.get("name") or "").strip(), i.get("unii") or None
        else:
            name, unii = str(i).strip(), None
        if not name:
            continue
        inactives.append(name)
        inactive_uniis.append(unii)

    active_names = {a["name"].lower() for a in actives}
    active_uniis = {a["unii"] for a in actives if a["unii"]}
    mineral_only = (bool(active_uniis) and active_uniis <= set(MINERAL_UNII)
                    if active_uniis
                    else bool(active_names) and active_names <= MINERAL_NAMES)
    zinc_a = next((a for a in actives if a["unii"] == "SOI2LOH54Z"
                   or a["name"].lower() == "zinc oxide"), None)
    # Published first, estimate only as a fallback, and say which it was.
    zinc = (zinc_a["percent_w_w"] if zinc_a and zinc_a["percent_w_w"] is not None
            else (zinc_a or {}).get("percent_estimate"))
    zinc_estimated = bool(zinc_a) and zinc_a["percent_w_w"] is None
    name = str(p.get("product_name") or p.get("title") or "").strip()
    spf = p.get("spf")
    if spf is None and SPF_RE.search(name):
        spf = SPF_RE.search(name).group(1)

    rec = {
        "id": f"US:SPL-{setid}",
        "id_scheme": "spl_setid",
        "jurisdiction": "US",
        "authority": "FDA (DailyMed SPL)",
        "regulatory_class": "otc_monograph_drug",
        "product_name": name,
        "company": _labeler(p.get("title")),
        "scope": "sunscreen",
        "category": p.get("category"),
        "actives": actives,
        "uv_filters": sorted(active_names),
        "mineral_only": mineral_only,
        "zinc_percent": zinc,
        "spf_label": int(spf) if str(spf).isdigit() else None,
        "inactives": inactives,
        # Parallel list, same order and length as `inactives`. Kept parallel
        # rather than as objects so every other country's records — which
        # have no UNIIs — stay the same shape.
        "inactive_uniis": inactive_uniis,
        "inactive_order_is_data": True,
        "inactive_source": p.get("inactive_source"),
        "contains_chemical_filter": p.get("contains_chemical_filter"),
        "has_hidden_chemical_filter": p.get("has_hidden_chemical_filter"),
        "mineral_type": p.get("mineral_type"),
        "concentration_status": ("published" if any(
            a["percent_w_w"] is not None for a in actives)
            else "not_convertible"),
        "zinc_percent_is_estimate": zinc_estimated,
        "data_status": "complete" if inactives else (
            "not_published" if p.get("inactive_source") == "empty"
            else "not_collected"),
        # The upstream corpus computes its own formulation hash and keeps its
        # own history. Carrying it lets the two watches be compared: if it
        # moves and ours does not (or the reverse), one of the two rules is
        # wrong and we want to know which.
        "upstream_formulation_hash": p.get("formulation_hash"),
        "upstream_first_seen": p.get("first_seen"),
        "corpus_version": corpus_version,
        "source_url": p.get("dailymed_url") or (
            f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
            if setid else None),
        "observed": observed,
        "verified_at": observed,
    }
    if p.get("baby_labeled"):
        rec["baby_flag_source"] = "product_title"
    flags = [f"strength_unit_unknown:{a['name']}" for a in actives
             if a["estimate_basis"] == "assumed_mg_per_g"]
    flags += [f"strength_out_of_range:{a['name']}" for a in actives
              if a["estimate_basis"] == "out_of_range"]
    # The upstream parser labels what it could not convert instead of
    # guessing — carry those labels through rather than dropping the active.
    flags += [f"strength_{a['percent_basis']}:{a['name']}" for a in actives
              if str(a.get("percent_basis") or "").startswith(
                  ("unhandled_units", "rejected_over_100",
                   "numerator_equals_denominator", "unitless_assumed"))]
    # A monographed mineral filter above 25% is outside what FDA allows;
    # flagged for a human, never silently corrected or dropped.
    flags += [f"above_monograph_limit:{a['name']}={a['percent_w_w']}"
              for a in actives
              if a["percent_w_w"] is not None and a["percent_w_w"] > 25
              and a["name"].lower() in ("zinc oxide", "titanium dioxide")]
    if flags:
        # Kept and flagged, never dropped: when the upstream unit fix lands
        # we want the correction to show up as a change, not as a new product.
        rec["qa_flags"] = flags
    return rec


def _labeler(title):
    """DailyMed titles end with the labeler in brackets: '... [ACME LLC]'."""
    m = re.search(r"\[([^\]]+)\]\s*$", str(title or ""))
    return m.group(1).strip() if m else ""


def in_scope(p, categories=DEFAULT_CATEGORIES):
    """(bool, reason). A UV-filter net catches products that are not
    sunscreens; the upstream corpus labels them and we say which we kept."""
    cat = p.get("category") or "other"
    if cat in categories:
        return True, None
    return False, f"category:{cat}"

"""
CA adapter — Health Canada LNHPD (Licensed Natural Health Products Database).

Why Canada is the second country after the US: in Canada a sunscreen whose
only UV filters are mineral (zinc oxide / titanium dioxide) is a NATURAL
HEALTH PRODUCT and needs an NPN, so every mineral sunscreen on the Canadian
market is enumerable from this one public register — the Canadian equivalent
of the US OTC monograph M020 field. (Chemical-filter sunscreens take the DIN
drug pathway and live in the DPD, a separate source.)

Verified live 2026-08-20: api/natural-licences/, no auth, JSON, daily refresh,
825,818 medicinal-ingredient rows.

Endpoint shapes differ and the collector depends on the difference:
  paginated (100/page, no id needed): productlicence, medicinalingredient,
                                      productpurpose, productrisk
  per-product id REQUIRED:            nonmedicinalingredient, productdose,
                                      productroute
So we bulk-walk the wide tables and fetch the per-id tables ONLY for the
products the purpose text marks as in-scope — full inactive-ingredient lists
for a few thousand skincare products instead of 200k pointless calls.

Everything joins on lnhpd_id. licence_number (NPN, 8 digits) is the public,
stable, on-label identifier — it is the record id; we never invent one.
"""

import hashlib
import json
import re

# Purpose text is how Canada tells us what a product IS. Sunscreen purposes
# are formulaic ("Helps prevent sunburn", "provides broad spectrum...").
# 2026-08-21: this used to include a bare `sunburn`, which matched every
# product whose purpose text merely mentions sunburn as something it soothes
# — zinc ointments, calamine, anti-itch creams, even a fibre laxative whose
# text says "burning sensation". 2,309 "sunscreens" came back, 361 of them
# without any UV filter at all. A sunscreen makes a PROTECTION claim, so
# require protection semantics, not the word.
SUNSCREEN_RE = re.compile(
    r"sunscreen|écran solaire|"
    r"(?:prevent|protect|protection|prevents|protects|helps? prevent|"
    r"helps? protect)\w*[^.]{0,40}sunburn|"
    r"sunburn protection|sun protection factor|\bSPF\b|"
    r"UVA\s*/?\s*UVB|broad[- ]spectrum", re.I)
SKINCARE_RE = re.compile(
    r"\b(skin|diaper|nappy|rash|moisturi[sz]|emollient|dermal|eczema|"
    r"chafing|barrier cream|lip balm|cleanser|baby wash|topical)\b", re.I)
BABY_RE = re.compile(
    r"\b(baby|babies|infant|toddler|child|children|kids|newborn|"
    r"p[ae]diatric|nappy|diaper)\b", re.I)
# Mineral UV filters, as Health Canada names them.
MINERAL_UV = {"zinc oxide", "titanium dioxide"}


def scope_of(purposes, product_name, dosage_form, active_names=None):
    """Which bucket a product falls in. Purpose text wins; name is backup.

    `active_names` is optional because scope is decided twice: once before
    enrichment (cheap, text only, deliberately generous — it decides who is
    worth four API calls) and again after, when the actives are known. In
    LNHPD a sunscreen is a mineral sunscreen by construction: chemical
    filters make a product a drug with a DIN, so it is not in this register
    at all. A product with no ZnO/TiO2 therefore cannot be a sunscreen here,
    whatever its purpose text says.
    """
    blob = " ".join(purposes) + " " + (product_name or "")
    if SUNSCREEN_RE.search(blob):
        if active_names is None or (active_names & MINERAL_UV):
            return "sunscreen"
    if SKINCARE_RE.search(blob) or re.search(
            r"\b(cream|lotion|ointment|balm|salve|gel)\b", dosage_form or "", re.I):
        return "skincare"
    return None


def build_record(lic, purposes, medicinal, nonmedicinal, routes, doses):
    """One canonical ingredient record from the six LNHPD tables."""
    actives = [{
        "name": m.get("ingredient_name"),
        "quantity": m.get("quantity"),
        "unit": m.get("quantity_unit_of_measure"),
        "quantity_min": m.get("quantity_minimum"),
        "quantity_max": m.get("quantity_maximum"),
        "potency_amount": m.get("potency_amount"),
        "potency_constituent": m.get("potency_constituent"),
        "potency_unit": m.get("potency_unit_of_measure"),
        "source_material": m.get("source_material"),
    } for m in medicinal]
    active_names = {str(a["name"] or "").strip().lower() for a in actives}
    npn = str(lic.get("licence_number") or "").strip()
    name = lic.get("product_name") or ""
    dosage = lic.get("dosage_form") or ""
    scope = scope_of(purposes, name, dosage, active_names)
    rec = {
        "id": f"CA:NPN-{npn}" if npn else f"CA:lnhpd-{lic.get('lnhpd_id')}",
        "id_scheme": "npn" if npn else "lnhpd_id",
        "jurisdiction": "CA",
        "authority": "Health Canada NNHPD (LNHPD)",
        "regulatory_class": "natural_health_product",
        "source_product_key": lic.get("lnhpd_id"),
        "product_name": name,
        "company": lic.get("company_name"),
        "dosage_form": dosage,
        "routes": [r.get("route_type_desc") for r in routes],
        "purposes": purposes,
        "actives": actives,
        # LNHPD's non-medicinal list has names only (no order, no quantity) —
        # thinner than a US SPL inactive list. Recorded as-is, never padded.
        "inactives": [n.get("ingredient_name") for n in nonmedicinal],
        "populations": sorted({d.get("population_type_desc")
                               for d in doses if d.get("population_type_desc")}),
        "licence_date": lic.get("licence_date"),
        "revised_date": lic.get("revised_date"),
        "status_active": bool(lic.get("flag_product_status")),
        "attested_monograph": bool(lic.get("flag_attested_monograph")),
        "scope": scope,
        "source_url": f"https://health-products.canada.ca/lnhpd-bdpsnh/info?licence={npn}"
                      if npn else "",
    }
    if scope == "sunscreen":
        # The Sunnytime question, answered per product by the register itself.
        rec["uv_filters"] = sorted(active_names & MINERAL_UV) or sorted(active_names)
        rec["mineral_only"] = bool(active_names) and active_names <= MINERAL_UV
    # Two independent signals, recorded separately: what the register says
    # the product is for, and what the marketing says. Previously only the
    # text was read, so every product came back baby=0 even though 223 of
    # them are registered for infants.
    pops = " ".join(rec["populations"]).lower()
    baby_pop = bool(re.search(r"infant|child|all ages", pops))
    baby_txt = bool(BABY_RE.search(" ".join(purposes) + " " + name))
    if baby_pop or baby_txt:
        rec["baby"] = True
        rec["baby_flag_source"] = ",".join(
            s for s, on in (("population", baby_pop), ("purpose_or_name", baby_txt)) if on)
    # --- formulation fingerprint (the whole point of the time series) -------
    # A stable hash of WHAT IS IN THE PRODUCT, deliberately excluding
    # everything that is not formulation (dates, status flags, company
    # renames). When this hash changes between runs, the manufacturer
    # reformulated — that event is the asset, and it is invisible unless we
    # fingerprint every observation. Actives are sorted (register order is
    # not meaningful); inactives keep source order, because for a full
    # ingredient list the order is itself information.
    fp = {
        "actives": sorted(
            (str(a["name"] or "").strip().lower(), a["quantity"], a["unit"])
            for a in actives),
        "inactives": [str(i or "").strip().lower() for i in rec["inactives"]],
        "dosage_form": dosage.strip().lower(),
    }
    rec["formulation_hash"] = hashlib.sha1(
        json.dumps(fp, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    rec["n_actives"] = len(actives)
    rec["n_inactives"] = len(rec["inactives"])
    return rec

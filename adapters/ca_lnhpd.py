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

import re

# Purpose text is how Canada tells us what a product IS. Sunscreen purposes
# are formulaic ("Helps prevent sunburn", "provides broad spectrum...").
SUNSCREEN_RE = re.compile(
    r"sunscreen|sunburn|sun protection|SPF|UVA|UVB|ultraviolet", re.I)
SKINCARE_RE = re.compile(
    r"\b(skin|diaper|nappy|rash|moisturi[sz]|emollient|dermal|eczema|"
    r"chafing|barrier cream|lip balm|cleanser|baby wash|topical)\b", re.I)
BABY_RE = re.compile(
    r"\b(baby|babies|infant|toddler|child|children|kids|newborn|"
    r"p[ae]diatric|nappy|diaper)\b", re.I)
# Mineral UV filters, as Health Canada names them.
MINERAL_UV = {"zinc oxide", "titanium dioxide"}


def scope_of(purposes, product_name, dosage_form):
    """Which bucket a product falls in. Purpose text wins; name is backup."""
    blob = " ".join(purposes) + " " + (product_name or "")
    if SUNSCREEN_RE.search(blob):
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
    scope = scope_of(purposes, name, dosage)
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
    if BABY_RE.search(" ".join(purposes) + " " + name):
        rec["baby_flag_source"] = "purpose_or_name"
    return rec

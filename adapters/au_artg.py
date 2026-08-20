"""
AU adapter — TGA Australian Register of Therapeutic Goods (ARTG).

Australia regulates sunscreen as a therapeutic good, so every product on the
market carries an AUST L (listed) or AUST R (registered) number and its
ACTIVE ingredients are public with exact quantities. Verified 2026-08-21 from
a real ARTG "Export data" download: 505 rows, actives given as
"zinc oxide, Quantity: 250 mg/g; titanium dioxide, Quantity: 40 mg/g".

Two inputs, deliberately separate:

  1. The official Export data spreadsheet — bulk, sanctioned, no scraping.
     Gives ARTG ID, product name, sponsor, and actives with quantities.
     This is the spine.
  2. Per-product PDF text (the "Download PDF" on an ARTG entry), pasted or
     saved by hand into data/raw/au/pdf/{ARTG_ID}.txt. This is the ONLY
     place excipients appear. tga.gov.au disallows automated access, so
     these arrive manually and the adapter simply reads whatever is there —
     a product with no PDF yet is still a valid record, just without the
     inactive list. Coverage is reported, never faked.

Units: the register uses mg/g. 250 mg/g = 25% w/w. We store both, because
the source unit is the source's, and the percentage is what a formulator
reads.
"""

import hashlib
import json
import re

MINERAL_UV = {"zinc oxide", "titanium dioxide"}
BABY_RE = re.compile(
    r"\b(baby|babies|infant|toddler|kid|kids|child|children|junior|"
    r"sensitive)\b", re.I)
SPF_RE = re.compile(r"SPF\s*(\d{1,3})", re.I)

# "octyl methoxycinnamate, Quantity: 75 mg/g"
ACTIVE_RE = re.compile(
    r"^(?P<name>.*?),\s*Quantity:\s*(?P<qty>[\d.]+)\s*(?P<unit>\S+)\s*$")


def parse_actives(cell):
    """Parse the Export sheet's 'Active Ingredients' cell."""
    out = []
    for part in str(cell or "").split(";"):
        part = part.strip()
        if not part or part.lower() == "nan":
            continue
        m = ACTIVE_RE.match(part)
        if m:
            qty = float(m.group("qty"))
            unit = m.group("unit")
            pct = round(qty / 10, 4) if unit.lower() == "mg/g" else None
            out.append({"name": m.group("name").strip(), "quantity": qty,
                        "unit": unit, "percent_w_w": pct})
        else:
            # No quantity declared — keep the name, admit the gap.
            out.append({"name": part, "quantity": None, "unit": None,
                        "percent_w_w": None})
    return out


# The PDF's ingredient block. TGA prints excipients under a heading that has
# varied ("Excipients", "Other ingredients", "Inactive ingredients"), so all
# three are accepted; the block ends at the next ALL-CAPS-ish heading.
# NOTE on flags: the heading is matched case-insensitively, but the
# terminator MUST NOT be. With a global re.I, "[A-Z]" also matches lowercase,
# so the block ended at the very first ingredient line and only one name
# survived (caught in testing on a 5-ingredient fixture). The (?i:...) group
# scopes ignore-case to the heading alone.
EXCIPIENT_BLOCK_RE = re.compile(
    r"(?i:Excipients?|Other ingredients?|Inactive ingredients?)\s*[:\-]?\s*\n"
    r"(?P<body>.*?)"
    r"(?=\n\s*(?:[A-Z][A-Za-z ]{3,}[:\n]|Page \d|Conditions\b|"
    r"Standard conditions\b)|\Z)",
    re.S)
NOISE_RE = re.compile(r"^\s*(page \d+|-{3,}|_{3,}|\d+\s*$)", re.I)


def parse_pdf_excipients(text):
    """Pull the inactive-ingredient names out of an ARTG PDF's text.

    Returns [] when the PDF has no excipient block — an honest empty, not a
    guess. The caller records pdf_present separately so a missing PDF and a
    genuinely empty list never look alike.
    """
    if not text:
        return []
    m = EXCIPIENT_BLOCK_RE.search(text)
    if not m:
        return []
    names = []
    for line in m.group("body").splitlines():
        line = line.strip(" \t•-*")
        if not line or NOISE_RE.match(line):
            continue
        # A line may hold several comma-separated names, or one name with a
        # trailing quantity ("zinc oxide 250 mg/g") we do not want here.
        for piece in re.split(r"[;,]", line):
            piece = re.sub(r"\s*\d[\d.]*\s*(mg/g|mg|g|%|mL|w/w)\b.*$", "",
                           piece, flags=re.I).strip()
            if len(piece) > 1 and not piece.lower().startswith("quantity"):
                names.append(piece)
    return names


def build_record(row, pdf_text=None, observed=None):
    artg_id = str(row.get("ARTG ID") or "").strip()
    name = str(row.get("Product Name") or "").strip()
    actives = parse_actives(row.get("Active Ingredients"))
    active_names = {a["name"].strip().lower() for a in actives if a["name"]}
    inactives = parse_pdf_excipients(pdf_text)
    spf = SPF_RE.search(name)
    zinc = next((a["percent_w_w"] for a in actives
                 if a["name"].strip().lower() == "zinc oxide"), None)
    rec = {
        "id": f"AU:ARTG-{artg_id}",
        "id_scheme": "artg_id",
        "jurisdiction": "AU",
        "authority": "TGA (ARTG)",
        "regulatory_class": "therapeutic_good",
        "product_name": name,
        "company": str(row.get("Sponsor Name") or "").strip(),
        "scope": "sunscreen",
        "actives": actives,
        "uv_filters": sorted(active_names),
        "mineral_only": bool(active_names) and active_names <= MINERAL_UV,
        "zinc_percent": zinc,
        "spf_label": int(spf.group(1)) if spf else None,
        "inactives": inactives,
        # Provenance for the two-speed input: the spine came from the
        # official export, the inactive list (if any) from a hand-collected
        # PDF. Never let a missing PDF read as "this product has no
        # excipients".
        "pdf_present": bool(pdf_text),
        "source_export": "TGA ARTG Export data",
        "source_url": f"https://www.tga.gov.au/resources/artg/{artg_id}",
        "observed": observed,
    }
    if BABY_RE.search(name):
        rec["baby_flag_source"] = "product_name"
    fp = {
        "actives": sorted((a["name"].strip().lower(), a["quantity"], a["unit"])
                          for a in actives),
        "inactives": [i.strip().lower() for i in inactives],
    }
    rec["formulation_hash"] = hashlib.sha1(
        json.dumps(fp, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    rec["n_actives"] = len(actives)
    rec["n_inactives"] = len(inactives)
    return rec

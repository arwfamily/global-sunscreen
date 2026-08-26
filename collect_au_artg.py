"""
AU collector — build canonical records from the ARTG export + manual PDFs.

No network at all. Everything it reads is already in the repo:
    data/raw/au/*.xlsx | *.csv     official TGA "Export data" downloads
    data/raw/au/pdf/{ARTG_ID}.txt  hand-saved ARTG PDF text (excipients)

Run it after adding either kind of file. Re-running is safe and cheap: the
canonical store is rebuilt from the raw inputs every time, and the
formulation history is appended to only when something actually changed.

Why manual PDFs: tga.gov.au disallows automated access, and the excipient
list lives only in the per-product PDF. Rather than crawl a site that has
asked us not to, we take the official bulk export for the spine and add
inactive lists by hand for the products that matter — the 131 mineral-only
sunscreens, and inside those the 18 baby/sensitive ones first.

Run:  python collect_au_artg.py
"""

import datetime
import glob
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

from adapters.au_artg import build_record

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw" / "au"
PDF_DIR = RAW / "pdf"
CURATED = RAW / "au_sunscreens.json"      # hand-transcribed excipient lists
OUT = ROOT / "data" / "canonical" / "au_ingredients.jsonl"
HIST = ROOT / "data" / "canonical" / "au_formulation_history.jsonl"
REQUIRED = ("ARTG ID", "Product Name", "Active Ingredients")
VERIFIED = ROOT / "data" / "canonical" / "_verified.json"
# Fields that are about WHEN we looked, not about the product.
VOLATILE = ("observed", "verified_at", "last_seen")


def _read_any(path):
    """Yield dict rows from .jsonl (preferred), .csv, or .xlsx.

    JSONL is the format we keep in the repo: git stores it as text, so a
    later export shows up as a readable diff (which products appeared or
    disappeared), and there is no binary-mangling risk. GitHub's web
    uploader flagged the original .xlsx for line-ending "normalisation",
    which would have silently corrupted it. Spreadsheets are still accepted
    for convenience, but converting to JSONL is the recommended path.
    """
    if path.endswith(".jsonl"):
        with open(path) as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
        return
    import pandas as pd           # only needed for the spreadsheet path
    df = pd.read_excel(path) if path.endswith(".xlsx") else pd.read_csv(path)
    for _, r in df.iterrows():
        yield {k: (None if pd.isna(v) else v) for k, v in r.items()}


def load_rows():
    """Read every export file in data/raw/au/, newest last so it wins."""
    rows, files = {}, sorted(glob.glob(str(RAW / "*.jsonl"))
                             + glob.glob(str(RAW / "*.csv"))
                             + glob.glob(str(RAW / "*.xlsx")))
    if not files:
        sys.exit(f"[!] no export files in {RAW} — add the TGA 'Export data' "
                 f"download (converted to .jsonl) there first")
    for f in files:
        n, checked = 0, False
        for r in _read_any(f):
            if not checked:
                missing = [c for c in REQUIRED if c not in r]
                if missing:
                    print(f"  [!] {os.path.basename(f)}: missing {missing} "
                          f"— skipped")
                    break
                checked = True
            aid = str(r.get("ARTG ID") or "").strip()
            if not aid or aid.lower() == "nan":
                continue
            rows[aid] = r          # later file wins for the same ARTG ID
            n += 1
        if n:
            print(f"  [*] {os.path.basename(f)}: {n} rows")
    return rows


def load_curated():
    """ARTG ID -> {excipients, data_status} from the curated JSON.

    This is the file to keep updating: every new PDF read by hand goes in
    here, and the collector picks it up on the next run with no code change.
    """
    if not CURATED.exists():
        print(f"  [*] no curated excipient file at {CURATED.name}")
        return {}
    doc = json.loads(CURATED.read_text())
    out = {}
    for p in doc.get("products", []):
        aid = str(p.get("artg_id") or "").strip()
        if not aid:
            continue
        out[aid] = {"excipients": p.get("excipients") or [],
                    "data_status": p.get("data_status")}
    have = sum(1 for v in out.values() if v["excipients"])
    print(f"  [*] {CURATED.name}: {len(out)} products, {have} with excipients "
          f"(generated {doc.get('generated_at')})")
    return out


def load_pdf(artg_id):
    p = PDF_DIR / f"{artg_id}.txt"
    return p.read_text(errors="replace") if p.exists() else None


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()

    previous = {}
    if OUT.exists():
        for line in OUT.open():
            if line.strip():
                r = json.loads(line)
                previous[r["id"]] = r

    rows = load_rows()
    curated = load_curated()
    store, changes = {}, []
    for aid, row in rows.items():
        if not aid.isdigit():
            # The TGA export ends with a footer row describing the search
            # ("Applied filters: SearchValues contains 'sunscreen'"). It has
            # no ARTG ID, so it is not a product. Dropping it here keeps it
            # out of every downstream count.
            print(f"  [!] skipped non-product row: {aid[:60]!r}")
            continue
        cur = curated.get(aid) or {}
        rec = build_record(row, load_pdf(aid), today,
                           manual_excipients=cur.get("excipients"),
                           data_status=cur.get("data_status"))
        rec["verified_at"] = today
        old = previous.get(rec["id"])
        # Australia is rebuilt from a file that only changes when she adds
        # one. Stamping today's date onto all 501 records every morning
        # rewrote the whole file daily: half a megabyte of diff that said
        # nothing, and a git history where a real reformulation would be
        # invisible. Dates move only when the record moves; when the whole
        # source was checked is recorded once, in _verified.json.
        if old and {k: v for k, v in rec.items() if k not in VOLATILE} == \
                   {k: v for k, v in old.items() if k not in VOLATILE}:
            for k in VOLATILE:
                if k in old:
                    rec[k] = old[k]
        if not old:
            changes.append(("new", rec))
        elif old.get("formulation_hash") != rec["formulation_hash"]:
            # Either a real reformulation, or the first time a PDF filled in
            # the inactive list. Distinguish them — one is a market event,
            # the other is our own coverage improving.
            kind = ("pdf_added" if not old.get("pdf_present")
                    and rec["pdf_present"] else "reformulated")
            changes.append((kind, rec, old))
        rec["first_seen"] = (old or {}).get("first_seen", today)
        rec["last_seen"] = today
        store[rec["id"]] = rec

    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w") as f:
        for r in sorted(store.values(), key=lambda x: x["id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(OUT)

    verified = json.loads(VERIFIED.read_text()) if VERIFIED.exists() else {}
    verified["AU"] = {"last_verified": today, "records": len(store),
                      "source": "TGA ARTG export + hand-read PDFs"}
    VERIFIED.write_text(json.dumps(verified, indent=1, sort_keys=True))

    if changes:
        with HIST.open("a") as f:
            for c in changes:
                kind, rec = c[0], c[1]
                old = c[2] if len(c) > 2 else None
                f.write(json.dumps({
                    "id": rec["id"], "observed": today, "change": kind,
                    "formulation_hash": rec["formulation_hash"],
                    "previous_hash": (old or {}).get("formulation_hash"),
                    "product_name": rec["product_name"],
                    "company": rec["company"],
                    "actives": rec["actives"], "inactives": rec["inactives"],
                    "zinc_percent": rec["zinc_percent"],
                    "spf_label": rec["spf_label"],
                    "mineral_only": rec["mineral_only"],
                    "pdf_present": rec["pdf_present"],
                }, ensure_ascii=False) + "\n")

    # ---- report: coverage first, because the PDF gap is the real state ----
    vals = list(store.values())
    mineral = [r for r in vals if r["mineral_only"]]
    baby = [r for r in vals if r.get("baby_flag_source")]
    baby_min = [r for r in mineral if r.get("baby_flag_source")]
    withpdf = [r for r in vals if r["pdf_present"]]
    print(f"\n[*] store={len(vals)} -> {OUT}")
    print(f"[*] mineral-only={len(mineral)}  baby-labelled={len(baby)}  "
          f"baby mineral={len(baby_min)}")
    print(f"[*] excipient coverage: {len(withpdf)}/{len(vals)} products have "
          f"a PDF ({len(withpdf) and sum(r['n_inactives'] for r in withpdf) // max(1, len(withpdf))} "
          f"inactives on average)")
    missing = [r for r in baby_min if not r["pdf_present"]]
    if missing:
        print(f"[*] baby mineral products still needing a PDF ({len(missing)}):")
        for r in sorted(missing, key=lambda x: -(x["zinc_percent"] or 0)):
            print(f"    {r['id'].split('-')[1]:>7}  ZnO "
                  f"{str(r['zinc_percent'] or '?'):>6}%  {r['product_name'][:48]}")
    zn = sorted(r["zinc_percent"] for r in mineral if r["zinc_percent"])
    if zn:
        print(f"[*] zinc oxide across mineral-only: median "
              f"{zn[len(zn)//2]:.1f}%, range {zn[0]:.1f}-{zn[-1]:.1f}%")
    if changes:
        from collections import Counter
        print(f"[*] history: {dict(Counter(c[0] for c in changes))} -> {HIST}")


if __name__ == "__main__":
    main()

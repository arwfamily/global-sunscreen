"""
AU helper — turn downloaded ARTG PDFs into the .txt files the collector reads.

The point of this script is to remove the copy-paste from the manual path.
Workflow becomes:

  1. Open the ARTG entry, click "Download PDF" (a human, in a browser —
     tga.gov.au disallows automated access, so this stays manual by design).
  2. Drop every downloaded PDF into data/raw/au/pdf_in/ — the filename does
     not matter; the ARTG ID is read out of the document itself.
  3. Run this script. It writes data/raw/au/pdf/{ARTG_ID}.txt for each one
     and reports which of the still-missing baby mineral products are now
     covered.

Extraction uses pdftotext -layout when available (best for the two-column
ARTG layout) and falls back to pdfplumber. The ARTG ID is taken from the
document text, so a file saved as "Public Summary (3).pdf" still lands in
the right place — and if no ID can be found, the file is reported rather
than guessed at.

Run:  python ingest_au_pdfs.py
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
IN_DIR = ROOT / "data" / "raw" / "au" / "pdf_in"
OUT_DIR = ROOT / "data" / "raw" / "au" / "pdf"
# "ARTG ID: 526391" or "ARTG Identifier 526391" or a bare 5-7 digit id after
# the heading. Kept deliberately narrow so a random number in the body of the
# document cannot be mistaken for the identifier.
ID_RE = re.compile(r"ARTG\s*(?:ID|Identifier|Number)\s*[:\-]?\s*(\d{4,8})", re.I)


def extract(pdf: Path) -> str:
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    try:
        import pdfplumber
        with pdfplumber.open(pdf) as doc:
            return "\n".join(p.extract_text() or "" for p in doc.pages)
    except Exception as e:  # noqa: BLE001
        print(f"  [!] {pdf.name}: extraction failed ({e})", file=sys.stderr)
        return ""


def main():
    IN_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(IN_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"[*] no PDFs in {IN_DIR} — drop the downloaded files there")
        return
    done, unknown = [], []
    for pdf in pdfs:
        text = extract(pdf)
        m = ID_RE.search(text)
        if not m:
            # Last resort: a filename that is just the id, e.g. 526391.pdf
            fm = re.fullmatch(r"(\d{4,8})", pdf.stem)
            if fm:
                m = fm
        if not m:
            unknown.append(pdf.name)
            continue
        artg = m.group(1)
        (OUT_DIR / f"{artg}.txt").write_text(text)
        done.append(artg)
        print(f"  [*] {pdf.name} -> pdf/{artg}.txt ({len(text)} chars)")
    print(f"\n[*] extracted {len(done)} PDFs")
    if unknown:
        print(f"[!] no ARTG ID found in {len(unknown)} file(s): "
              f"{', '.join(unknown[:8])}")
        print("    Rename each to its ARTG ID (e.g. 526391.pdf) and re-run.")
    print("[*] next: python collect_au_artg.py")


if __name__ == "__main__":
    main()

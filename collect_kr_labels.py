"""
KR collector — build canonical records from hand-collected Korean labels.

No network. Reads whatever is in data/raw/kr/:

    *.csv                      one row per product. Column names are matched
                               loosely, so the sheet you already keep works:
                               product name  <- 제품명 / product / name / title
                               ingredients   <- Full Ingredients List /
                                                전성분 / ingredients
                               brand, spf, url, id are used if present.
    ingredients/{slug}.txt     alternative: paste one label per file. First
                               line is the product name, the rest is the
                               ingredient list.

Ids are ours (KR-LABEL-0001...) because Korea publishes no product id for
cosmetics. Keep an `id` column in the CSV once a product has one so it stays
stable when rows are re-sorted — otherwise the same product could be handed
a different id on the next run, and the monitor would read that as one
product delisted and another appearing.

Run:  python collect_kr_labels.py
"""

import csv
import datetime
import glob
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

from adapters.kr_label import build_record

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw" / "kr"
OUT = ROOT / "data" / "canonical" / "kr_ingredients.jsonl"
VERIFIED = ROOT / "data" / "canonical" / "_verified.json"
VOLATILE = ("observed", "verified_at", "last_seen")

NAME_KEYS = ("product name", "product_name", "제품명", "name", "title",
             "product", "제품")
ING_KEYS = ("full ingredients list", "full_ingredients", "전성분",
            "ingredients", "ingredient list", "성분")
BRAND_KEYS = ("brand", "브랜드", "company", "제조사")
URL_KEYS = ("url", "구매링크", "link", "product url")


def pick(row, keys):
    low = {str(k).strip().lower(): v for k, v in row.items() if k}
    for k in keys:
        if k in low and str(low[k]).strip() not in ("", "nan", "None"):
            return str(low[k]).strip()
    for k, v in low.items():                      # loose contains-match
        if any(t in k for t in keys) and str(v).strip() not in ("", "nan"):
            return str(v).strip()
    return None


def rows_from_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ing = pick(row, ING_KEYS)
            name = pick(row, NAME_KEYS)
            if not ing or not name:
                continue
            yield {"product_name": name, "ingredients_text": ing,
                   "brand": pick(row, BRAND_KEYS), "url": pick(row, URL_KEYS),
                   "spf": pick(row, ("spf",)), "id": pick(row, ("id",)),
                   "source_note": f"csv:{Path(path).name}"}


def rows_from_txt(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return
    head, _, body = text.partition("\n")
    yield {"product_name": head.strip(), "ingredients_text": body.strip(),
           "id": f"KR-LABEL-{Path(path).stem}",
           "source_note": f"txt:{Path(path).name}"}


def main():
    today = datetime.date.today().isoformat()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    previous = {}
    if OUT.exists():
        for line in OUT.open():
            if line.strip():
                r = json.loads(line)
                previous[r["id"]] = r
    # Reuse the id we already gave a product with this name, so re-sorting
    # the sheet never looks like a delisting.
    by_name = {r["product_name"]: r["id"] for r in previous.values()}

    inputs = sorted(glob.glob(str(RAW / "*.csv"))) + \
        sorted(glob.glob(str(RAW / "ingredients" / "*.txt")))
    if not inputs:
        print(f"[*] nothing in {RAW} yet — add the Korea sheet as .csv or "
              f"paste labels into {RAW}/ingredients/*.txt")
        return

    store, seq = {}, 0
    for path in inputs:
        n = 0
        reader = rows_from_csv(path) if path.endswith(".csv") else rows_from_txt(path)
        for row in reader:
            seq += 1
            if not row.get("id"):
                row["id"] = by_name.get(row["product_name"])
            rec = build_record(row, today, seq)
            old = previous.get(rec["id"])
            if old and {k: v for k, v in rec.items() if k not in VOLATILE} == \
                       {k: v for k, v in old.items() if k not in VOLATILE}:
                for k in VOLATILE:
                    if k in old:
                        rec[k] = old[k]
            store[rec["id"]] = rec
            n += 1
        print(f"  [*] {Path(path).name}: {n} products")

    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w") as f:
        for r in sorted(store.values(), key=lambda x: x["id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(OUT)

    verified = json.loads(VERIFIED.read_text()) if VERIFIED.exists() else {}
    verified["KR"] = {"last_verified": today, "records": len(store),
                      "source": "manual label collection (화장품법 10조)"}
    VERIFIED.write_text(json.dumps(verified, indent=1, sort_keys=True))

    vals = list(store.values())
    mineral = [r for r in vals if r["mineral_only"]]
    zinc_pos = [r["zinc_position"] for r in vals if r.get("zinc_position")]
    untranslated = sum(1 for r in vals for i in r["inactives"]
                       if any("\uac00" <= ch <= "\ud7a3" for ch in i))
    print(f"\n[*] store={len(vals)} -> {OUT}")
    print(f"[*] mineral-only={len(mineral)}  "
          f"baby-flagged={sum(1 for r in vals if r.get('baby_flag_source'))}  "
          f"median ingredients="
          f"{sorted(r['n_ingredients'] for r in vals)[len(vals)//2] if vals else 0}")
    if zinc_pos:
        print(f"[*] zinc position (concentration proxy): median "
              f"{sorted(zinc_pos)[len(zinc_pos)//2]}, "
              f"at position 2 in {sum(1 for p in zinc_pos if p == 2)} products")
    if untranslated:
        print(f"[!] {untranslated} ingredient mentions are still Korean-only. "
              f"Add the KCIA 표준화 명칭 목록 as data/reference/kcia_names.csv "
              f"(ko,inci) to fold them into INCI for cross-country counts.")


if __name__ == "__main__":
    main()

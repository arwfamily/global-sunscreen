"""
US collector — pull the DailyMed corpus into canonical records.

Source: arwfamily/tinysafe-dailymed-scraper-v2, data/canonical/us_sunscreens.jsonl
(13,285 SPLs). That repo does the scraping, UNII resolution and its own
snapshot history; this one takes its canonical output, scopes it, and puts
it in the same shape as Australia, Canada and Korea so one monitor can watch
all four.

    data/raw/us/us_sunscreens.jsonl      L0, exactly as fetched
    data/canonical/us_ingredients.jsonl  in scope
    data/canonical/us_excluded.jsonl     out of scope, with the reason

Scope: sunscreen categories only, because the upstream net is cast on
UV-filter UNIIs and therefore also catches diaper creams, calamine and
lipstick. Widen deliberately:

    US_CATEGORIES=sunscreen,makeup,lip_balm python collect_us_dailymed.py

Run:  python collect_us_dailymed.py
"""

import datetime
import hashlib
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

from adapters.us_dailymed import DEFAULT_CATEGORIES, build_record, in_scope

ROOT = Path(__file__).parent
FEED = os.environ.get(
    "US_FEED",
    "https://raw.githubusercontent.com/arwfamily/tinysafe-dailymed-scraper-v2/"
    "main/data/canonical/us_sunscreens.jsonl")
CATEGORIES = tuple(c.strip() for c in
                   os.environ.get("US_CATEGORIES",
                                  ",".join(DEFAULT_CATEGORIES)).split(",")
                   if c.strip())
RAW = ROOT / "data" / "raw" / "us" / "us_sunscreens.jsonl"
OUT = ROOT / "data" / "canonical" / "us_ingredients.jsonl"
EXCL = ROOT / "data" / "canonical" / "us_excluded.jsonl"
VERIFIED = ROOT / "data" / "canonical" / "_verified.json"
VOLATILE = ("observed", "verified_at", "last_seen")


def fetch():
    req = urllib.request.Request(FEED, headers={"User-Agent": "arw-ingredients/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def main():
    today = datetime.date.today().isoformat()
    RAW.parent.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    try:
        body = fetch()
    except Exception as e:
        # An upstream outage must never blank the store.
        if not RAW.exists():
            sys.exit(f"[!] could not fetch {FEED} and no local copy: {e}")
        print(f"[!] fetch failed ({e}) — rebuilding from the stored raw copy")
        body = RAW.read_bytes()
    else:
        changed = (not RAW.exists()
                   or hashlib.sha1(RAW.read_bytes()).digest()
                   != hashlib.sha1(body).digest())
        if changed:
            RAW.write_bytes(body)
            print(f"[*] corpus updated ({len(body)/1e6:.1f} MB)")
        else:
            print("[*] corpus unchanged since last run")

    products = [json.loads(l) for l in body.decode().splitlines() if l.strip()]
    corpus_version = max((p.get("last_seen") or "" for p in products),
                         default=today)
    print(f"[*] {len(products)} SPLs in the corpus (last_seen {corpus_version}) "
          f"— keeping categories {CATEGORIES}")

    previous = {}
    if OUT.exists():
        for line in OUT.open():
            if line.strip():
                r = json.loads(line)
                previous[r["id"]] = r

    store, dropped, why = {}, [], Counter()
    for p in products:
        keep, reason = in_scope(p, CATEGORIES)
        if not keep:
            why[reason] += 1
            dropped.append({"id": f"US:SPL-{p.get('setid')}",
                            "product_name": p.get("product_name"),
                            "category": p.get("category"),
                            "actives": [a.get("name") for a in
                                        p.get("active_ingredients") or []],
                            "excluded_reason": reason})
            continue
        rec = build_record(p, today, corpus_version)
        old = previous.get(rec["id"])
        if old and {k: v for k, v in rec.items() if k not in VOLATILE} == \
                   {k: v for k, v in old.items() if k not in VOLATILE}:
            for k in VOLATILE:
                if k in old:
                    rec[k] = old[k]
        store[rec["id"]] = rec

    for path, rows in ((OUT, sorted(store.values(), key=lambda x: x["id"])),
                       (EXCL, sorted(dropped, key=lambda x: x["id"]))):
        tmp = path.with_suffix(".tmp")
        with tmp.open("w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp.replace(path)

    verified = json.loads(VERIFIED.read_text()) if VERIFIED.exists() else {}
    verified["US"] = {"last_verified": today, "records": len(store),
                      "source": FEED, "categories_kept": list(CATEGORIES),
                      "corpus_version": corpus_version,
                      "corpus_size": len(products)}
    VERIFIED.write_text(json.dumps(verified, indent=1, sort_keys=True))

    vals = list(store.values())
    withi = [r for r in vals if r["inactives"]]
    unii_cov = sum(1 for r in vals for u in r["inactive_uniis"] if u)
    unii_tot = sum(len(r["inactive_uniis"]) for r in vals)
    print(f"\n[*] in scope {len(vals)} -> {OUT.name}; "
          f"out of scope {len(dropped)} -> {EXCL.name}")
    for reason, n in why.most_common():
        print(f"      {n:6d}  {reason}")
    print(f"[*] full ingredient lists {len(withi)}/{len(vals)}, "
          f"median {sorted(len(r['inactives']) for r in withi)[len(withi)//2] if withi else 0} "
          f"ingredients")
    print(f"[*] UNII coverage on inactives: {unii_cov}/{unii_tot} "
          f"({unii_cov/max(1,unii_tot):.0%}) — that share is compared on a "
          f"substance code rather than a name")
    print(f"[*] mineral-only {sum(1 for r in vals if r['mineral_only'])}, "
          f"chemical filter {sum(1 for r in vals if r.get('contains_chemical_filter'))}, "
          f"hidden booster {sum(1 for r in vals if r.get('has_hidden_chemical_filter'))}, "
          f"baby-labelled {sum(1 for r in vals if r.get('baby_flag_source'))}")
    pub = [r for r in vals if r.get("concentration_status") == "published"]
    est = [r for r in vals if r.get("zinc_percent_is_estimate")]
    wv = sum(1 for r in vals for a in r["actives"] if a.get("percent_basis") == "w/v")
    ww = sum(1 for r in vals for a in r["actives"] if a.get("percent_basis") == "w/w")
    flags = Counter(f.split(":")[0] for r in vals for f in r.get("qa_flags") or [])
    print(f"[*] concentrations: {len(pub)}/{len(vals)} products carry a "
          f"published percentage; {len(vals) - len(pub)} could not be "
          f"converted and say so rather than guessing")
    print(f"[*] basis: {ww} actives w/w, {wv} w/v — a w/v percentage equals "
          f"w/w only where density is 1, so a lotion's number is close and "
          f"an oil's is not. Carried on every active as percent_basis.")
    if est:
        print(f"[!] {len(est)} products still fall back to an estimated zinc "
              f"percentage (upstream could not convert the filed unit)")
    for k, n in flags.most_common():
        print(f"      {n:6d}  {k}")


if __name__ == "__main__":
    main()

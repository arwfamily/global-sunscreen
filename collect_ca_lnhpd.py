"""
CA collector — Health Canada LNHPD ingredient register.

Two-speed design, forced by the API's own shape:
  PHASE A (bulk walk, paginated 100/page): productlicence, productpurpose,
    medicinalingredient. These have no id requirement, so we page through
    them once and keep the raw pages under data/raw/ca_lnhpd/ (L0).
  PHASE B (targeted, per-product): nonmedicinalingredient, productroute,
    productdose — the API demands an id for these. We call them ONLY for
    products Phase A marked in scope (sunscreen / skincare), which is a few
    thousand calls instead of ~200k.

Resumable and Actions-safe, same lessons as the recall repo:
  - state file data/ca_lnhpd_state.json records the last completed page of
    each bulk table and the ids already enriched;
  - git commit+push after each batch, with rebase recovery (a long run and
    a concurrent daily run must not fight);
  - a per-run budget so one dispatch ends politely instead of timing out.

Run:  python collect_ca_lnhpd.py           # normal, budgeted
      BUDGET=999999 python collect_ca_lnhpd.py   # unlimited (first backfill)
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

from adapters.ca_lnhpd import build_record, scope_of

BASE = "https://health-products.canada.ca/api/natural-licences"
UA = "TinySafe-Ingredients/1.0 (baby product safety research)"
ROOT = Path(__file__).parent
OUT = ROOT / "data" / "canonical" / "ca_ingredients.jsonl"
RAW = ROOT / "data" / "raw" / "ca_lnhpd"
STATE = ROOT / "data" / "ca_lnhpd_state.json"
SLEEP = 0.25
BUDGET = int(os.environ.get("BUDGET", "4000"))   # requests per run
BULK = ("productlicence", "productpurpose", "medicinalingredient")

_calls = [0]


def get(path: str, tries: int = 3):
    url = f"{BASE}/{path}"
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                _calls[0] += 1
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  [!] {path[:60]} attempt {attempt+1}: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def git_checkpoint(label):
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    import subprocess

    def sh(*c):
        p = subprocess.run(c, capture_output=True, text=True)
        return p.returncode, (p.stderr or p.stdout).strip()

    sh("git", "config", "user.name", "ingredients-bot")
    sh("git", "config", "user.email", "actions@users.noreply.github.com")
    sh("git", "add", "data/")
    if sh("git", "diff", "--cached", "--quiet")[0] == 0:
        return
    if sh("git", "commit", "-m", f"ca-lnhpd: {label}")[0] != 0:
        return
    for attempt in range(4):
        if sh("git", "push")[0] == 0:
            print(f"  [*] checkpoint {label}: pushed")
            return
        if attempt == 0:
            sh("git", "fetch", "--unshallow")
        sh("git", "fetch", "origin")
        if sh("git", "rebase", "origin/HEAD")[0] != 0:
            sh("git", "rebase", "--abort")
            sh("git", "pull", "--rebase", "--autostash")
        time.sleep(3)
    print(f"  [!] checkpoint {label}: push failed", file=sys.stderr)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"pages": {}, "enriched": [], "phase": "A"}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def walk_bulk(table, state):
    """Page through one bulk table into data/raw/, resuming from state."""
    rows = []
    cache = RAW / f"{table}.jsonl"
    RAW.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        rows = [json.loads(l) for l in cache.open() if l.strip()]
    page = state["pages"].get(table, 0) + 1
    total_pages = None
    with cache.open("a") as f:
        while _calls[0] < BUDGET:
            data = get(f"{table}/?lang=en&type=json&page={page}")
            if data is None:
                print(f"  [!] {table} page {page} unreachable — stopping table")
                break
            meta = (data.get("metadata") or {}).get("pagination") or {}
            if total_pages is None and meta.get("total"):
                total_pages = -(-int(meta["total"]) // int(meta.get("limit") or 100))
                print(f"[{table}] total={meta['total']} pages={total_pages} "
                      f"(resuming at {page})")
            batch = data.get("data") or []
            if not batch:
                break
            for row in batch:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows.append(row)
            state["pages"][table] = page
            if page % 100 == 0:
                f.flush()
                save_state(state)
                git_checkpoint(f"{table} page {page}")
                print(f"  [{table}] page {page}/{total_pages or '?'} "
                      f"rows={len(rows)}")
            if not meta.get("next"):
                state["pages"][table] = "done"
                print(f"[{table}] complete: {len(rows)} rows")
                break
            page += 1
            time.sleep(SLEEP)
    save_state(state)
    return rows


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    state = load_state()

    # ---- Phase A: the three walkable tables --------------------------------
    tables = {}
    for t in BULK:
        if state["pages"].get(t) == "done":
            cache = RAW / f"{t}.jsonl"
            tables[t] = [json.loads(l) for l in cache.open() if l.strip()]
            print(f"[{t}] already complete: {len(tables[t])} rows (cached)")
        else:
            tables[t] = walk_bulk(t, state)
            if state["pages"].get(t) != "done":
                print(f"[*] budget spent inside {t} — re-run to continue")
                git_checkpoint(f"{t} partial")
                return

    # ---- index by product ---------------------------------------------------
    lics = {r["lnhpd_id"]: r for r in tables["productlicence"]}
    purposes, medicinal = {}, {}
    for r in tables["productpurpose"]:
        purposes.setdefault(r["lnhpd_id"], []).append(r.get("purpose") or "")
    for r in tables["medicinalingredient"]:
        medicinal.setdefault(r["lnhpd_id"], []).append(r)
    print(f"[*] products={len(lics)} with-purpose={len(purposes)} "
          f"with-actives={len(medicinal)}")

    targets = [pid for pid, lic in lics.items()
               if scope_of(purposes.get(pid, []), lic.get("product_name"),
                           lic.get("dosage_form"))]
    print(f"[*] in-scope (sunscreen/skincare) products: {len(targets)}")

    # ---- Phase B: per-id enrichment for in-scope products only -------------
    enriched = set(state.get("enriched") or [])
    store = {}
    if OUT.exists():
        for line in OUT.open():
            if line.strip():
                r = json.loads(line)
                store[r["id"]] = r
    done_this_run = 0
    for pid in targets:
        if pid in enriched:
            continue
        if _calls[0] >= BUDGET:
            print(f"[*] budget reached — {len(targets) - len(enriched)} "
                  f"products still to enrich; re-run to continue")
            break
        non = get(f"nonmedicinalingredient/?lang=en&type=json&id={pid}") or {}
        rou = get(f"productroute/?lang=en&type=json&id={pid}") or {}
        dos = get(f"productdose/?lang=en&type=json&id={pid}") or {}
        rec = build_record(
            lics[pid], purposes.get(pid, []), medicinal.get(pid, []),
            non.get("data") or (non if isinstance(non, list) else []),
            rou.get("data") or (rou if isinstance(rou, list) else []),
            dos.get("data") or (dos if isinstance(dos, list) else []),
        )
        store[rec["id"]] = rec
        enriched.add(pid)
        done_this_run += 1
        if done_this_run % 200 == 0:
            write_store(store)
            state["enriched"] = sorted(enriched)
            save_state(state)
            git_checkpoint(f"enriched {len(enriched)}/{len(targets)}")
            print(f"  [enrich] {len(enriched)}/{len(targets)}")
        time.sleep(SLEEP)

    write_store(store)
    state["enriched"] = sorted(enriched)
    save_state(state)
    git_checkpoint(f"enriched {len(enriched)}/{len(targets)}")

    sun = [r for r in store.values() if r.get("scope") == "sunscreen"]
    mineral = [r for r in sun if r.get("mineral_only")]
    baby = [r for r in store.values() if r.get("baby_flag_source")]
    print(f"\n[*] store={len(store)} records -> {OUT}")
    print(f"[*] sunscreens={len(sun)}  mineral-only={len(mineral)}  "
          f"baby-flagged={len(baby)}  (API calls this run: {_calls[0]})")


def write_store(store):
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w") as f:
        for r in sorted(store.values(), key=lambda x: x["id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(OUT)


if __name__ == "__main__":
    main()

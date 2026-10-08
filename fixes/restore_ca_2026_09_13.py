#!/usr/bin/env python3
"""
fixes/restore_ca_2026_09_13.py — undo the 2026-09-13 Canada data loss.

What happened
  On 2026-09-13 LNHPD did not answer during the daily rotation. Every per-id
  call for that day's 65-product slice failed; the collector turned each
  failure into an empty list, rebuilt 64 real sunscreens with zero actives,
  rescope_ca.py moved them to ca_excluded.jsonl ("no mineral UV filter"),
  and detect_reformulations.py published 64 "delisted" events. (The 65th
  record, CA:NPN-80031130, has had no actives in the register since its first
  read on 2026-08-21 and is not part of this loss.)

What this script does (idempotent; a second run changes nothing)
  1. canonical   restore the 64 records exactly as held on 2026-09-12
                 (commit bb9c012), from fixes/ca_2026-09-12_originals.jsonl
  2. excluded    remove those 64 from ca_excluded.jsonl
  3. collector   reset their verified date to the pre-loss date, so the
                 rotation re-reads them from Health Canada soon
  4. detector    clear gone_since on their state, so the restore itself is
                 not published as 64 "relisted" events
  5. events      append one "retracted" event per false "delisted" event
                 (events are append-only; the original lines stay)
  6. history     append one "correction" observation per product

The collector and rescope_ca.py were fixed in the same commit so this cannot
recur: a failed call now keeps the stored record, and a record with zero
actives is never excluded.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = "2026-10-08"
ORIG = ROOT / "fixes" / "ca_2026-09-12_originals.jsonl"
CANON = ROOT / "data" / "canonical" / "ca_ingredients.jsonl"
EXCL = ROOT / "data" / "canonical" / "ca_excluded.jsonl"
COLL_STATE = ROOT / "data" / "ca_lnhpd_state.json"
DET_STATE = ROOT / "data" / "state" / "fingerprints" / "ca.json"
EVENTS = ROOT / "data" / "events" / "ca_events.jsonl"
HIST = ROOT / "data" / "canonical" / "ca_formulation_history.jsonl"
REASON = ("2026-09-13 LNHPD fetch failure recorded as zero actives; product "
          "never left the register. Restored from the 2026-09-12 record "
          "(commit bb9c012). See fixes/restore_ca_2026_09_13.py.")


def read_jsonl(p):
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def write_jsonl(p, rows):
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(p)


def append_jsonl(p, rows):
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    orig = {r["id"]: r for r in read_jsonl(ORIG)}
    ids = set(orig)
    assert len(ids) == 64 and all(r.get("actives") for r in orig.values())

    # 1 canonical
    canon = read_jsonl(CANON)
    have = {r["id"] for r in canon}
    add = [orig[i] for i in sorted(ids - have)]
    if add:
        write_jsonl(CANON, sorted(canon + add, key=lambda r: r["id"]))
    print(f"canonical: restored {len(add)} (already present {len(ids & have)})")

    # 2 excluded
    excl = read_jsonl(EXCL)
    keep = [e for e in excl if e.get("id") not in ids]
    if len(keep) != len(excl):
        write_jsonl(EXCL, keep)
    print(f"excluded: removed {len(excl) - len(keep)}")

    # 3 collector state
    cs = json.loads(COLL_STATE.read_text(encoding="utf-8"))
    ver = cs.setdefault("verified", {})
    reset = 0
    for r in orig.values():
        k = str(r["source_product_key"])
        if ver.get(k) != r["verified_at"]:
            ver[k] = r["verified_at"]
            reset += 1
    if reset:
        COLL_STATE.write_text(json.dumps(cs, indent=1))  # same as collect_ca_lnhpd.save_state
    print(f"collector state: verified date reset for {reset}")

    # 4 detector state
    ds = json.loads(DET_STATE.read_text(encoding="utf-8"))
    cleared = 0
    for i in ids:
        rec = ds["records"].get(i)
        if rec and rec.get("gone_since") == "2026-09-13":
            rec.pop("gone_since")
            cleared += 1
    if cleared:
        DET_STATE.write_text(json.dumps(ds, ensure_ascii=False, indent=1, sort_keys=True))  # same as detect_reformulations
    print(f"detector state: gone_since cleared for {cleared}")

    # 5 events (append-only)
    ev = read_jsonl(EVENTS)
    already = {e["id"] for e in ev if e.get("change") == "retracted"}
    false_delist = [e for e in ev if e.get("change") == "delisted"
                    and e.get("observed") == "2026-09-13" and e.get("id") in ids]
    retractions = [{"id": e["id"], "observed": TODAY, "change": "retracted",
                    "retracts": {"change": "delisted", "observed": "2026-09-13"},
                    "reason": REASON, "product_name": e.get("product_name")}
                   for e in false_delist if e["id"] not in already]
    append_jsonl(EVENTS, retractions)
    print(f"events: appended {len(retractions)} retractions")

    # 6 history (append-only)
    hist = read_jsonl(HIST)
    done = {h["id"] for h in hist if h.get("change") == "correction"
            and h.get("observed") == TODAY}
    corr = []
    for i in sorted(ids - done):
        r = orig[i]
        corr.append({"id": i, "observed": TODAY, "change": "correction",
                     "corrects": {"observed": "2026-09-13", "change": "reformulated"},
                     "reason": REASON,
                     "formulation_hash": r.get("formulation_hash"),
                     "product_name": r.get("product_name"), "company": r.get("company"),
                     "actives": r.get("actives"), "inactives": r.get("inactives"),
                     "n_actives": r.get("n_actives"), "n_inactives": r.get("n_inactives")})
    append_jsonl(HIST, corr)
    print(f"history: appended {len(corr)} corrections")


if __name__ == "__main__":
    main()

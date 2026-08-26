"""
detect_reformulations.py — the one place a formulation change is declared.

Collectors collect. This decides what changed. Keeping the two apart is the
point: the same rules then apply to every country, a rule can be corrected
and re-run over data already held, and no collector can quietly invent an
event by writing its own history in its own format.

Reads   data/canonical/{jur}_ingredients.jsonl   (whatever exists)
Against data/state/fingerprints/{jur}.json       (last observed fingerprints)
Writes  data/events/{jur}_events.jsonl           (append-only, never rewritten)
        data/events/review_queue.md              (what a human should look at)

Run after any collector:
    python detect_reformulations.py                # every jurisdiction
    python detect_reformulations.py AU CA          # some of them

First run on an existing store writes one `new` event per product and
nothing else — the baseline. Every run after that is the actual watch.
"""

import datetime
import json
import sys
from collections import Counter
from pathlib import Path

from core.fingerprint import (fingerprint, classify, profile_for,
                              remember_labels,
                              META_FIELDS, RULE_VERSION)

ROOT = Path(__file__).parent
CANON = ROOT / "data" / "canonical"
STATE = ROOT / "data" / "state" / "fingerprints"
EVENTS = ROOT / "data" / "events"

# Metadata carried into the event so the log is readable on its own.
CARRY = ("product_name", "company", "jurisdiction", "spf_label",
         "mineral_only", "zinc_percent", "status_active", "source_url")


def jurisdictions():
    return sorted(p.name.split("_")[0].upper()
                  for p in CANON.glob("*_ingredients.jsonl"))


def load_canonical(jur):
    path = CANON / f"{jur.lower()}_ingredients.jsonl"
    out = {}
    with path.open() as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r
    return out


def load_state(jur):
    p = STATE / f"{jur.lower()}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"jurisdiction": jur, "baseline_taken": None, "records": {}}


def save_state(jur, state):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / f"{jur.lower()}.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True))


def append_events(jur, events):
    if not events:
        return
    EVENTS.mkdir(parents=True, exist_ok=True)
    with (EVENTS / f"{jur.lower()}_events.jsonl").open("a") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def run(jur, today):
    records = load_canonical(jur)
    state = load_state(jur)
    prev = state.get("records", {})
    baseline = state.get("baseline_taken") is None
    # A rule change makes old and new fingerprints incomparable. Re-baseline
    # quietly rather than report our own edit as market movement — and leave
    # one line in the log saying that is what happened.
    rebaselined = (not baseline
                   and state.get("rule_version") not in (None, RULE_VERSION))
    if rebaselined:
        print(f"  [*] detection rules moved "
              f"{state.get('rule_version')} -> {RULE_VERSION}: re-baselining "
              f"{len(prev)} fingerprints, no events published this run")
        append_events(jur, [{"id": f"{jur}:*", "observed": today,
                             "change": "rebaselined",
                             "from_rule_version": state.get("rule_version"),
                             "to_rule_version": RULE_VERSION,
                             "records": len(prev),
                             "note": "detection rules updated; comparison "
                                     "restarts from this snapshot"}])
        baseline = True
    prof = profile_for(jur)
    events, new_state = [], {}

    for pid, rec in records.items():
        remember_labels(rec)
        fp = fingerprint(rec)
        meta = {k: rec.get(k) for k in CARRY if k in rec}
        old = prev.get(pid)
        if not old:
            events.append({"id": pid, "observed": today, "change": "new",
                           "baseline": baseline, "fp": fp["fp_full"],
                           "coverage": fp["coverage"],
                           "snapshot": {"actives": fp["actives"],
                                        "inactives": fp["inactives"]},
                           **meta})
        elif baseline:
            pass                      # re-baselining: record, do not report
        else:
            if old.get("gone_since"):
                events.append({"id": pid, "observed": today,
                               "change": "relisted",
                               "absent_since": old["gone_since"], **meta})
            for ev in classify(old.get("meta", {}), old.get("fp", {}),
                               rec, fp):
                events.append({
                    "id": pid, "observed": today,
                    "previous_observed": old.get("verified_at"),
                    "fp": fp["fp_full"], "previous_fp": old.get("fp", {}).get("fp_full"),
                    "coverage": fp["coverage"],
                    "snapshot": {"actives": fp["actives"],
                                 "inactives": fp["inactives"]},
                    **meta, **ev})
        new_state[pid] = {"fp": fp, "verified_at": rec.get("verified_at") or today,
                          "meta": {k: rec.get(k) for k in META_FIELDS
                                   if k in rec},
                          "first_seen": (old or {}).get("first_seen", today)}

    # Registrations that were there last time and are not now.
    for pid, old in prev.items():
        if pid in records:
            continue
        if old.get("gone_since"):
            new_state[pid] = old                      # already reported
            continue
        events.append({"id": pid, "observed": today, "change": "delisted",
                       "last_verified": old.get("verified_at"),
                       "previous_fp": old.get("fp", {}).get("fp_full"),
                       **{k: v for k, v in (old.get("meta") or {}).items()
                          if k in CARRY}})
        old = dict(old)
        old["gone_since"] = today
        new_state[pid] = old

    state.update({"records": new_state, "last_run": today,
                  "rule_version": RULE_VERSION,
                  "baseline_taken": state.get("baseline_taken") or today,
                  "profile": prof,
                  "counts": {"records": len(records),
                             "events_this_run": len(events)}})
    append_events(jur, events)
    save_state(jur, state)
    return records, events, baseline


def report(jur, records, events, baseline):
    kinds = Counter(e["change"] for e in events)
    cov = Counter(fingerprint(r)["coverage"] for r in records.values())
    print(f"\n=== {jur} ===")
    print(f"  records {len(records)} | excipient coverage "
          f"full={cov['full']} "
          f"actives-only={cov['actives_only']} "
          f"confirmed-none={cov['actives_only_confirmed']}")
    if baseline:
        print(f"  baseline written: {kinds.get('new', 0)} products. "
              f"Changes are watched from the next run.")
        return []
    if not events:
        print("  no change")
        return []
    print(f"  events: {dict(kinds)}")
    material = [e for e in events if e["change"] == "reformulated"]
    for e in sorted(material, key=lambda x: -x.get("severity", 0))[:15]:
        c = e["changes"]
        bits = []
        for x in c["active_concentration_changed"]:
            bits.append(f"{x['filter']} {x['from']}%->{x['to']}%")
        for x in c["uv_filter_changed"]:
            bits.append(f"{'+' if x['from'] is None else '-'}{x['filter']}")
        if c["inactive_added"]:
            bits.append(f"+{len(c['inactive_added'])} excipient "
                        f"({', '.join(c['inactive_added'][:3])})")
        if c["inactive_removed"]:
            bits.append(f"-{len(c['inactive_removed'])} excipient "
                        f"({', '.join(c['inactive_removed'][:3])})")
        if c["inactive_reordered"]:
            bits.append("order changed")
        print(f"    [sev {e.get('severity')}] {e['id']} "
              f"{str(e.get('product_name'))[:40]} — {'; '.join(bits)}")
    return material


def write_review_queue(rows, today):
    if not rows:
        return
    EVENTS.mkdir(parents=True, exist_ok=True)
    p = EVENTS / "review_queue.md"
    with p.open("a") as f:
        f.write(f"\n## {today}\n\n")
        for e in sorted(rows, key=lambda x: -x.get("severity", 0)):
            c = e["changes"]
            f.write(f"- **[{e['jurisdiction']}] {e.get('product_name')}** "
                    f"({e['id']}, sev {e.get('severity')}) — "
                    f"{e.get('company')}\n")
            for x in c["active_concentration_changed"]:
                f.write(f"  - {x['filter']}: {x['from']}% → {x['to']}%\n")
            for x in c["uv_filter_changed"]:
                f.write(f"  - filter {'added' if x['from'] is None else 'removed'}"
                        f": {x['filter']}\n")
            if c["inactive_added"]:
                f.write(f"  - added: {', '.join(c['inactive_added'])}\n")
            if c["inactive_removed"]:
                f.write(f"  - removed: {', '.join(c['inactive_removed'])}\n")
            if e.get("source_url"):
                f.write(f"  - {e['source_url']}\n")
    print(f"\n[*] review queue -> {p}")


def main():
    today = datetime.date.today().isoformat()
    want = [a.upper() for a in sys.argv[1:]] or jurisdictions()
    if not want:
        sys.exit("[!] no data/canonical/*_ingredients.jsonl found")
    material = []
    for jur in want:
        records, events, baseline = run(jur, today)
        material += report(jur, records, events, baseline)
    write_review_queue(material, today)


if __name__ == "__main__":
    main()

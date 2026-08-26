"""
CA collector — Health Canada LNHPD ingredient register.

v2 (2026-08-21). The v1 run died at push time: it mirrored the WHOLE
Canadian natural-health register into the repo — productlicence.jsonl
149.99 MB, medicinalingredient.jsonl 110 MB — and GitHub hard-rejects any
blob over 100 MB. Vitamins, probiotics and toothpaste were being stored
forever so that a few hundred sunscreens could be found among them.

Two changes, and they are different changes:

  FETCH LESS. The API guide documents `medicinalingredient/?id=`, so the
  actives table does NOT have to be walked. v1 paged 8,269 pages (~4 h) to
  get it; v2 asks per product, only for products already known to be in
  scope. That walk is simply gone.

  STORE LESS. The two tables that must still be walked (purpose, licence)
  are filtered AS THEY STREAM, before anything is written, and pruned to
  the fields the adapter reads. Raw retention stays honest — we still keep
  the register's own rows verbatim — but only for products in scope.

Scope is decided by purpose text, which is safe here: in Canada a product
may only make a sun-protection claim if it carries a sun-protection
purpose, so a sunscreen cannot hide from a purpose-text filter. Product
name is used as a second net for skincare.

PHASE A  walk productpurpose  -> candidate ids   (filtered on write)
         walk productlicence  -> spine for those (filtered on write)
PHASE B  per-id, in-scope only: medicinalingredient, nonmedicinalingredient,
         productroute, productdose

Resumable and Actions-safe: state file records the last completed page of
each walked table and the ids already enriched; a per-run budget ends a
dispatch politely instead of timing out; checkpoints commit and push.

Run:  python collect_ca_lnhpd.py                # normal, budgeted
      BUDGET=999999 python collect_ca_lnhpd.py  # unlimited (first pass)
      CA_API_BASE=http://localhost:8000 ...     # point at a fake API
"""

import datetime
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

from adapters.ca_lnhpd import (build_record, scope_of,
                               SUNSCREEN_RE, SKINCARE_RE)

BASE = os.environ.get("CA_API_BASE",
                      "https://health-products.canada.ca/api/natural-licences")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.4 Safari/605.1.15")
HEADERS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
           "Accept-Language": "en-CA,en;q=0.9"}
TIMEOUT = 180
ROOT = Path(__file__).parent
OUT = ROOT / "data" / "canonical" / "ca_ingredients.jsonl"
HIST = ROOT / "data" / "canonical" / "ca_formulation_history.jsonl"
RAW = ROOT / "data" / "raw" / "ca_lnhpd"
STATE = ROOT / "data" / "ca_lnhpd_state.json"
SLEEP = 0.25
BUDGET = int(os.environ.get("BUDGET", "4000"))
# Which scopes get the expensive per-id enrichment. Default sunscreen only:
# that is the question this project exists to answer, and the skincare bucket
# in a natural-health register (diaper creams, balms, moisturisers) is an
# order of magnitude larger, at four API calls each. Widen deliberately:
#   CA_SCOPES=sunscreen,skincare python collect_ca_lnhpd.py
SCOPES = tuple(s.strip() for s in
               os.environ.get("CA_SCOPES", "sunscreen").split(",") if s.strip())

# ---- staying current -------------------------------------------------------
# LNHPD changes every day. A collector that walks once and then reads its own
# cache forever looks healthy while going stale: the store stops moving, the
# history file fills with nothing, and "no reformulations detected" becomes a
# statement about our pipeline rather than about the market.
#
# Two clocks prevent that, and they answer different questions:
#   REWALK_DAYS  — how old the LIST may get. After this, the bulk tables are
#                  walked again, which is the only way a product registered
#                  since the last walk can be discovered at all.
#   MAX_AGE_DAYS — how old any single product's FORMULATION may get. Products
#                  are re-fetched oldest-first until the budget runs out, so
#                  every record is re-verified within this window even if the
#                  register never flagged it as revised. Health Canada leaves
#                  revised_date empty on most licences (1,457 of 1,910 in our
#                  store), so a trigger-only design would miss silent edits.
REWALK_DAYS = int(os.environ.get("CA_REWALK_DAYS", "7"))
MAX_AGE_DAYS = int(os.environ.get("CA_MAX_AGE_DAYS", "30"))
# Escape hatch for "walk it all again now" — a corrected scope rule, or a
# suspicion that the cached listing missed something. Costs one full walk.
FORCE_REWALK = bool(os.environ.get("CA_FORCE_REWALK", "").strip())

# Bump when the collection plan changes shape. A state file written by an
# older plan describes pages of tables this version no longer walks, so it
# must not be trusted — v1 state would claim medicinalingredient was "done".
SCHEMA = 3

# Walked in this order: purpose decides who is in scope, licence is then
# kept only for those. Reversing them would mean keeping every licence.
WALK = ("productpurpose", "productlicence")

# Fields the adapter actually reads. Everything else in a register row is
# dropped before it is written — that is most of the 150 MB.
LICENCE_FIELDS = ("lnhpd_id", "licence_number", "product_name", "company_name",
                  "dosage_form", "licence_date", "revised_date",
                  "flag_product_status", "flag_attested_monograph")
PURPOSE_FIELDS = ("lnhpd_id", "purpose")

_calls = [0]
_stalled = []
_probed = set()


def get(path: str, tries: int = 4):
    """One GET with backoff. Returns (parsed_json_or_None, seconds)."""
    url = f"{BASE}/{path}"
    delay = 5
    for attempt in range(tries):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read().decode("utf-8", "replace")
            _calls[0] += 1
            return json.loads(body), round(time.time() - t0, 1)
        except Exception as e:
            print(f"    [retry {attempt+1}/{tries}] {path}: "
                  f"{type(e).__name__} {str(e)[:120]}", file=sys.stderr)
            if attempt == tries - 1:
                return None, round(time.time() - t0, 1)
            time.sleep(delay)
            delay *= 2
    return None, 0.0


def unwrap(data):
    """LNHPD mixes response shapes: some tables return {metadata, data},
    others a bare list. Normalise to (rows, pagination_meta)."""
    if data is None:
        return [], {}
    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict):
        rows = data.get("data")
        if rows is None:
            rows = []
        meta = (data.get("metadata") or {}).get("pagination") or {}
        return rows, meta
    return [], {}


def probe(table, data):
    """Log the actual shape of a per-id response the first time we see it.

    LNHPD has already changed shape between tables once (bare list vs
    wrapped object) and cost a run. Observe, then trust.
    """
    if table in _probed:
        return
    _probed.add(table)
    kind = type(data).__name__
    if isinstance(data, dict):
        detail = f"keys={sorted(data.keys())[:6]}"
    elif isinstance(data, list):
        first = data[0] if data else None
        detail = (f"len={len(data)} first_keys="
                  f"{sorted(first.keys())[:8] if isinstance(first, dict) else first}")
    else:
        detail = repr(data)[:120]
    print(f"  [probe] {table} per-id response: {kind} {detail}")


def prune(row, fields):
    return {k: row.get(k) for k in fields}


def keep_purpose(row):
    text = row.get("purpose") or ""
    return bool(SUNSCREEN_RE.search(text) or SKINCARE_RE.search(text))


def git_checkpoint(label):
    """Commit+push data/. Never crashes the run.

    Uses scripts/git_publish.sh when present (one tested implementation),
    and falls back to an inline version that carries the same three
    lessons: clear an interrupted rebase first, address the branch by name
    so a detached HEAD cannot strand the commit, and autostash so files a
    collector wrote after staging do not block the rebase.
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    import subprocess

    helper = ROOT / "scripts" / "git_publish.sh"
    if helper.exists():
        p = subprocess.run(["bash", str(helper), f"ca-lnhpd: {label}", "data/"],
                           capture_output=True, text=True)
        for line in ((p.stdout or "") + (p.stderr or "")).strip().splitlines():
            print(f"  {line}")
        return

    def sh(*c):
        p = subprocess.run(c, capture_output=True, text=True)
        return p.returncode, (p.stderr or p.stdout).strip()

    if (ROOT / ".git" / "rebase-merge").exists() or \
       (ROOT / ".git" / "rebase-apply").exists():
        sh("git", "rebase", "--abort")
    sh("git", "config", "user.name", "ingredients-bot")
    sh("git", "config", "user.email", "actions@users.noreply.github.com")
    sh("git", "add", "data/")
    if sh("git", "diff", "--cached", "--quiet")[0] == 0:
        return
    if sh("git", "commit", "-m", f"ca-lnhpd: {label}")[0] != 0:
        return
    branch = os.environ.get("GITHUB_REF_NAME") or "main"
    for attempt in range(4):
        rc, err = sh("git", "push", "origin", f"HEAD:{branch}")
        if rc == 0:
            print(f"  [*] checkpoint {label}: pushed")
            return
        print(f"  [!] checkpoint {label}: push attempt {attempt+1} failed: "
              f"{err[:300]}", file=sys.stderr)
        sh("git", "fetch", "origin", branch)
        rc2, err2 = sh("git", "rebase", "--autostash", f"origin/{branch}")
        if rc2 != 0:
            sh("git", "rebase", "--abort")
            print(f"  [!] rebase failed: {err2[:200]}", file=sys.stderr)
            break
        time.sleep(3)
    print(f"  [!] checkpoint {label}: could not push — the commit exists "
          f"locally and the workflow's final step retries", file=sys.stderr)


def _age_days(iso, today):
    if not iso:
        return 10 ** 6
    try:
        return (datetime.date.fromisoformat(today)
                - datetime.date.fromisoformat(str(iso)[:10])).days
    except ValueError:
        return 10 ** 6


def load_state():
    if STATE.exists():
        st = json.loads(STATE.read_text())
        if st.get("schema") == 2:
            # v2 kept `enriched` as a list of ids with no date, so nothing
            # could be re-checked. Carry the ids over with the date of that
            # collection: they stay known, and the rolling re-verification
            # picks them up oldest-first instead of trusting them forever.
            print("[*] migrating state v2 -> v3 (adding verification dates)")
            st = {"schema": SCHEMA, "pages": st.get("pages", {}),
                  "walked_at": "2026-08-21",
                  "verified": {str(i): "2026-08-21"
                               for i in st.get("enriched") or []},
                  "candidates": st.get("candidates") or []}
            save_state(st)
            return st
        if st.get("schema") == SCHEMA:
            return st
        print(f"[*] state file is schema {st.get('schema')}, this collector "
              f"is schema {SCHEMA} — starting the walk over. Old raw caches "
              f"describe tables this version no longer walks.")
        for stale in RAW.glob("*.jsonl"):
            stale.unlink()
    return {"schema": SCHEMA, "pages": {}, "walked_at": None,
            "verified": {}, "candidates": []}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def walk_bulk(table, state, keep, fields):
    """Page through one bulk table, writing ONLY rows that pass `keep`,
    pruned to `fields`. Resumes from state; returns the kept rows."""
    rows = []
    cache = RAW / f"{table}.jsonl"
    RAW.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        rows = [json.loads(l) for l in cache.open() if l.strip()]
    page = state["pages"].get(table, 0) + 1
    total_pages = None
    seen = scanned = 0
    with cache.open("a") as f:
        announced, last_sig = False, None
        while _calls[0] < BUDGET:
            data, secs = get(f"{table}/?lang=en&type=json&page={page}")
            if data is None:
                print(f"  [!] {table}: page {page} unreachable after retries "
                      f"— saving progress and stopping this table")
                _stalled.append(table)
                break
            batch, meta = unwrap(data)
            if total_pages is None and meta.get("total"):
                total_pages = -(-int(meta["total"]) // int(meta.get("limit") or 100))
                print(f"[{table}] total={meta['total']} pages={total_pages} "
                      f"(resuming at {page})")
                announced = True
            elif not announced:
                print(f"[{table}] bare-list response (no pagination metadata) "
                      f"— paging until empty, resuming at {page}")
                announced = True
            if not batch:
                state["pages"][table] = "done"
                break
            # Guard against an endpoint that ignores ?page= and keeps
            # replaying page 1 — that would loop forever. v1 fingerprinted
            # only the first 300 characters of the first row, which is
            # identical across pages whenever the row's alphabetically
            # first fields are long and constant; the walk then declared a
            # table "complete" after one page and nothing said otherwise.
            # Hash the whole page instead: exact, and just as cheap.
            sig = hashlib.sha256(
                json.dumps(batch, sort_keys=True).encode()).hexdigest()
            if sig == last_sig:
                state["pages"][table] = "done"
                print(f"[{table}] page {page} is byte-identical to page "
                      f"{page-1} — the endpoint ignores ?page=; treating "
                      f"what we have as the complete table")
                break
            last_sig = sig
            scanned += len(batch)
            for row in batch:
                if not keep(row):
                    continue
                slim = prune(row, fields)
                f.write(json.dumps(slim, ensure_ascii=False) + "\n")
                rows.append(slim)
                seen += 1
            state["pages"][table] = page
            if page % 100 == 0:
                f.flush()
                save_state(state)
                git_checkpoint(f"{table} page {page}")
                print(f"  [{table}] page {page}/{total_pages or '?'} "
                      f"scanned={scanned} kept={len(rows)}")
            if meta and not meta.get("next"):
                state["pages"][table] = "done"
                break
            page += 1
            time.sleep(SLEEP)
    if state["pages"].get(table) == "done":
        print(f"[{table}] complete: scanned {scanned} rows this run, "
              f"kept {len(rows)} in scope")
    save_state(state)
    return rows


def fetch_per_id(table, pid):
    """One per-id table for one product. Probes the shape on first use."""
    data, _ = get(f"{table}/?lang=en&type=json&id={pid}")
    probe(table, data)
    rows, _ = unwrap(data)
    return rows


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    state = load_state()
    today = datetime.date.today().isoformat()

    # ---- is the LIST still current? ---------------------------------------
    # Both bulk tables are cached once "done". That is what makes the daily
    # run cheap — and what would freeze the register's contents at the date
    # of the first walk. After REWALK_DAYS the caches are dropped so the
    # tables are walked again and newly registered products can appear.
    walk_age = _age_days(state.get("walked_at"), today)
    if state["pages"] and (FORCE_REWALK or walk_age >= REWALK_DAYS):
        print(f"[*] {'forced re-walk' if FORCE_REWALK else 'the register listing is ' + str(walk_age) + ' days old'} "
              f"(limit {REWALK_DAYS}) — walking productpurpose and "
              f"productlicence again to pick up new registrations")
        state["pages"] = {}
        for stale in RAW.glob("*.jsonl"):
            stale.unlink()
        save_state(state)
    elif state["pages"]:
        print(f"[*] register listing is {walk_age} day(s) old — using cache "
              f"(re-walks every {REWALK_DAYS} days)")

    # ---- Phase A1: purposes, filtered on write -----------------------------
    if state["pages"].get("productpurpose") == "done":
        cache = RAW / "productpurpose.jsonl"
        purpose_rows = [json.loads(l) for l in cache.open() if l.strip()]
        print(f"[productpurpose] already complete: {len(purpose_rows)} "
              f"in-scope rows (cached)")
    else:
        purpose_rows = walk_bulk("productpurpose", state,
                                 keep=keep_purpose, fields=PURPOSE_FIELDS)
        if state["pages"].get("productpurpose") != "done":
            why = ("the server stopped responding"
                   if "productpurpose" in _stalled
                   else "the per-run request budget ran out")
            print(f"[*] productpurpose incomplete — {why}. Progress saved; "
                  f"re-run to continue from page "
                  f"{state['pages'].get('productpurpose', 0) + 1}.")
            git_checkpoint("productpurpose partial")
            return

    purposes = {}
    for r in purpose_rows:
        purposes.setdefault(r["lnhpd_id"], []).append(r.get("purpose") or "")
    candidates = set(purposes)
    state["candidates"] = sorted(candidates)
    save_state(state)
    print(f"[*] candidate products from purpose text: {len(candidates)}")

    # ---- Phase A2: licences, kept only for candidates ----------------------
    def keep_licence(row):
        return (row.get("lnhpd_id") in candidates
                or bool(SUNSCREEN_RE.search(row.get("product_name") or "")))

    if state["pages"].get("productlicence") == "done":
        cache = RAW / "productlicence.jsonl"
        lic_rows = [json.loads(l) for l in cache.open() if l.strip()]
        print(f"[productlicence] already complete: {len(lic_rows)} "
              f"in-scope rows (cached)")
    else:
        lic_rows = walk_bulk("productlicence", state,
                             keep=keep_licence, fields=LICENCE_FIELDS)
        if state["pages"].get("productlicence") != "done":
            why = ("the server stopped responding"
                   if "productlicence" in _stalled
                   else "the per-run request budget ran out")
            print(f"[*] productlicence incomplete — {why}. Progress saved; "
                  f"re-run to continue from page "
                  f"{state['pages'].get('productlicence', 0) + 1}.")
            git_checkpoint("productlicence partial")
            return

    if all(state["pages"].get(t) == "done" for t in WALK):
        state["walked_at"] = today
        save_state(state)

    lics = {r["lnhpd_id"]: r for r in lic_rows}
    scoped = {pid: scope_of(purposes.get(pid, []), lic.get("product_name"),
                            lic.get("dosage_form"))
              for pid, lic in lics.items()}
    n_sun = sum(1 for v in scoped.values() if v == "sunscreen")
    n_skin = sum(1 for v in scoped.values() if v == "skincare")
    targets = [pid for pid, sc in scoped.items() if sc in SCOPES]
    print(f"[*] identified: sunscreen {n_sun}, skincare {n_skin}")
    print(f"[*] enriching scopes {SCOPES}: {len(targets)} products "
          f"= {len(targets) * 4} API calls "
          f"(set CA_SCOPES to widen)")

    # ---- Phase B: everything per-id, in-scope only -------------------------
    # medicinalingredient joins this phase in v2. The API documents ?id= on
    # it, which is what removes the 8,269-page walk.
    verified = {str(k): v for k, v in (state.get("verified") or {}).items()}
    store = {}
    if OUT.exists():
        for line in OUT.open():
            if line.strip():
                r = json.loads(line)
                store[r["id"]] = r

    # ---- what to fetch this run, in priority order -------------------------
    # 1 NEW        never fetched — a product we do not hold at all
    # 2 FLAGGED    the licence row moved (revised_date, status, name, sponsor,
    #              dosage form). The register is telling us to look again.
    # 3 ROLLING    everything else, oldest verification first, so a silent
    #              edit on a licence that never bumps revised_date is still
    #              caught within MAX_AGE_DAYS.
    # Budget is spent in that order, so a small daily budget always does the
    # informative work first and the audit sweep with what is left over.
    def licence_moved(pid):
        rec = store.get(f"CA:NPN-{lics[pid].get('licence_number')}")
        if not rec:
            return False
        lic = lics[pid]
        return (str(rec.get("revised_date") or "") != str(lic.get("revised_date") or "")
                or bool(rec.get("status_active")) != bool(lic.get("flag_product_status"))
                or (rec.get("product_name") or "") != (lic.get("product_name") or "")
                or (rec.get("company") or "") != (lic.get("company_name") or "")
                or (rec.get("dosage_form") or "") != (lic.get("dosage_form") or ""))

    fresh = [p for p in targets if str(p) not in verified]
    flagged = [p for p in targets if str(p) in verified and licence_moved(p)]
    rolling = sorted((p for p in targets
                      if str(p) in verified and p not in set(flagged)),
                     key=lambda p: verified.get(str(p), ""))
    stale_now = [p for p in rolling
                 if _age_days(verified.get(str(p)), today) >= MAX_AGE_DAYS]
    queue = fresh + flagged + rolling
    print(f"[*] fetch queue: new={len(fresh)} flagged-by-register={len(flagged)} "
          f"re-verify={len(rolling)} (of which past {MAX_AGE_DAYS}d: "
          f"{len(stale_now)}) | budget {BUDGET} calls = "
          f"~{BUDGET // 4} products this run")

    done_this_run = 0
    for pid in queue:
        if _calls[0] >= BUDGET:
            print(f"[*] budget reached — {len(queue) - done_this_run} "
                  f"products still queued; the next run continues from the "
                  f"oldest verification")
            break
        med = fetch_per_id("medicinalingredient", pid)
        non = fetch_per_id("nonmedicinalingredient", pid)
        rou = fetch_per_id("productroute", pid)
        dos = fetch_per_id("productdose", pid)
        rec = build_record(lics[pid], purposes.get(pid, []),
                           med, non, rou, dos)
        rec["verified_at"] = today
        rec["first_seen"] = (store.get(rec["id"]) or {}).get("first_seen", today)
        record_observation(rec, store.get(rec["id"]), today)
        store[rec["id"]] = rec
        verified[str(pid)] = today
        done_this_run += 1
        if done_this_run % 200 == 0:
            write_store(store)
            state["verified"] = verified
            save_state(state)
            git_checkpoint(f"verified {done_this_run} this run")
            print(f"  [enrich] {done_this_run}/{len(queue)} this run")
        time.sleep(SLEEP)

    write_store(store)
    state["verified"] = verified
    save_state(state)
    git_checkpoint(f"verified {done_this_run} this run")
    ages = sorted(_age_days(v, today) for v in verified.values())
    if ages:
        print(f"[*] verification age across {len(ages)} products: "
              f"median {ages[len(ages)//2]}d, oldest {ages[-1]}d "
              f"(target: everything under {MAX_AGE_DAYS}d)")

    sun = [r for r in store.values() if r.get("scope") == "sunscreen"]
    mineral = [r for r in sun if r.get("mineral_only")]
    baby = [r for r in store.values() if r.get("baby_flag_source")]
    baby_sun = [r for r in sun if r.get("baby_flag_source")]
    print(f"\n[*] store={len(store)} records -> {OUT}")
    print(f"[*] sunscreens={len(sun)}  mineral-only={len(mineral)}  "
          f"baby-flagged={len(baby)}  baby sunscreens={len(baby_sun)}  "
          f"(API calls this run: {_calls[0]})")
    # Formulation-depth report: this is the A-track deliverable, not a
    # product count. How rich is each formulation record we just captured?
    if baby_sun:
        depths = sorted(r.get("n_inactives", 0) for r in baby_sun)
        mid = depths[len(depths) // 2]
        zinc = [r for r in baby_sun
                if any("zinc" in str(a["name"]).lower() for a in r["actives"])]
        print(f"[*] baby sunscreen formulations: median inactives={mid}, "
              f"range {depths[0]}-{depths[-1]}, zinc-containing={len(zinc)}")
    if HIST.exists():
        changes = [json.loads(l) for l in HIST.open() if l.strip()]
        reform = [c for c in changes if c["change"] == "reformulated"]
        meta = [c for c in changes if c["change"] == "metadata"]
        print(f"[*] history: {len(changes)} observations "
              f"({len(reform)} reformulations, {len(meta)} metadata-only "
              f"changes) -> {HIST}")


# Fields whose change is worth logging even when the formulation is
# identical: a relabel, a company rename, a licence revision. These are NOT
# reformulations, but they are events — "this brand revised its label four
# times without touching the formula" is itself a finding.
META_TRACKED = ("revised_date", "product_name", "company", "dosage_form",
                "purposes", "populations", "status_active",
                "attested_monograph")


def record_observation(rec, previous, today):
    """Append an observation whenever ANYTHING we track changes.

    Two kinds of change, deliberately separated so neither hides the other:
      change="reformulated"  the ingredient fingerprint moved — the actives,
                             their amounts, the full inactive list, or the
                             dosage form is different. The A-track signal.
      change="metadata"      the formulation is byte-identical but a tracked
                             field moved (relabel, rename, licence revision,
                             status flip, age-range change).
    Nothing is discarded either way: every observation carries the FULL
    formulation snapshot plus the metadata diff, so the history file alone
    can reconstruct what a product looked like on any date we saw it.
    """
    reformulated = (not previous
                    or previous.get("formulation_hash") != rec["formulation_hash"])
    meta_diff = {}
    if previous:
        for k in META_TRACKED:
            if previous.get(k) != rec.get(k):
                meta_diff[k] = {"from": previous.get(k), "to": rec.get(k)}
    if not reformulated and not meta_diff:
        return  # genuinely nothing new to say about this product today
    entry = {
        "id": rec["id"],
        "observed": today,
        "change": ("new" if not previous
                   else "reformulated" if reformulated else "metadata"),
        "formulation_hash": rec["formulation_hash"],
        "previous_hash": (previous or {}).get("formulation_hash"),
        "meta_changed": meta_diff or None,
        # Full snapshot, every time — the point is to be able to replay a
        # product's formulation history without needing any other file.
        "product_name": rec.get("product_name"),
        "company": rec.get("company"),
        "dosage_form": rec.get("dosage_form"),
        "licence_date": rec.get("licence_date"),
        "revised_date": rec.get("revised_date"),
        "status_active": rec.get("status_active"),
        "attested_monograph": rec.get("attested_monograph"),
        "scope": rec.get("scope"),
        "purposes": rec.get("purposes"),
        "populations": rec.get("populations"),
        "uv_filters": rec.get("uv_filters"),
        "mineral_only": rec.get("mineral_only"),
        "actives": rec.get("actives"),
        "inactives": rec.get("inactives"),
        "n_actives": rec.get("n_actives"),
        "n_inactives": rec.get("n_inactives"),
    }
    HIST.parent.mkdir(parents=True, exist_ok=True)
    with HIST.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_store(store):
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w") as f:
        for r in sorted(store.values(), key=lambda x: x["id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(OUT)


if __name__ == "__main__":
    main()

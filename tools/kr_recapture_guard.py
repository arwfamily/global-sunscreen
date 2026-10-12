#!/usr/bin/env python3
"""
kr_recapture_guard.py — enforces the two KR rules around recapture.py,
independently of the script itself, and writes the run summary.

  snapshot <jsonl> <snap>        copy the DB before recapture runs
  check    <snap> <jsonl> <md> [recapture-log.json]
                                 compare, enforce, write markdown summary

Rules enforced (whatever recapture.py does):
  1. Records whose review status is `derived-needs-human-check` are never
     changed. If the run touched one, its original line is restored.
  2. `mineral_only` and UV-filter classification fields are never
     recalculated automatically. If the run changed them, the old values
     are restored and the product is listed for human reclassification.

Only patched lines are re-serialised; every other line is kept byte-for-byte
as recapture.py wrote it, so the git diff shows only real changes.
"""
import json, re, shutil, sys

STATUS_KEYS = ("review_status", "검수상태", "status")
ID_KEYS = ("id", "ID")
FROZEN_STATUS = "derived-needs-human-check"
PROTECTED = re.compile(r"^(mineral_?only|미네랄온리|uv_?filters?.*|uv필터.*)$", re.I)
# rewritten on every successful recapture even when nothing changed
NOISE = {"last_captured"}
LABEL_KEYS = (("brand", "브랜드"), ("product", "product_name", "제품명", "name"))


def load(path):
    rows = []  # (id, raw_line, obj)
    with open(path, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            obj = json.loads(raw)
            rid = next((obj[k] for k in ID_KEYS if k in obj), None)
            rows.append((rid, raw.rstrip("\n"), obj))
    return rows


def status(o):
    return next((o.get(k) for k in STATUS_KEYS if k in o), None)


def label(o):
    parts = [next((str(o[k]) for k in ks if o.get(k)), "") for ks in LABEL_KEYS]
    return " — ".join(p for p in parts if p) or "(no name)"


def protected_keys(o):
    return [k for k in o if PROTECTED.match(k)]


def dumps_like(raw, obj):
    # keep the writer's style: non-ASCII literal if the original line had it
    ascii_ = not any(ord(c) > 127 for c in raw)
    compact = '", "' not in raw and '": ' not in raw
    sep = (",", ":") if compact else (", ", ": ")
    return json.dumps(obj, ensure_ascii=ascii_, separators=sep)


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def check(snap, path, md, log=None):
    before = {rid: (raw, o) for rid, raw, o in load(snap)}
    after = load(path)
    after_ids = {rid for rid, _, _ in after}

    out, changed, added, restored_frozen, reclass = [], [], [], [], []
    for rid, raw, o in after:
        if rid not in before:
            added.append((rid, label(o)))
            out.append(raw)
            continue
        braw, bo = before[rid]
        if raw == braw or o == bo:
            out.append(raw)
            continue
        # Rule 1: frozen records are restored verbatim.
        if status(bo) == FROZEN_STATUS:
            restored_frozen.append((rid, label(bo)))
            out.append(braw)
            continue
        # Rule 2: protected classification fields keep their old values.
        patched = dict(o)
        moved = []
        for k in set(protected_keys(bo)) | set(protected_keys(o)):
            if bo.get(k) != o.get(k):
                moved.append(k)
                if k in bo:
                    patched[k] = bo[k]
                else:
                    patched.pop(k, None)
        if moved:
            reclass.append((rid, label(bo), moved))
        fields = sorted(k for k in set(bo) | set(patched)
                        if bo.get(k) != patched.get(k) and k not in NOISE)
        if fields:
            hist = patched.get("reformulation_history") or []
            note = hist[-1].get("summary", "") if len(hist) > len(bo.get("reformulation_history") or []) else ""
            changed.append((rid, label(patched), fields, note))
        out.append(dumps_like(raw, patched) if moved else raw)

    removed = [(rid, label(o)) for rid, (_, o) in before.items() if rid not in after_ids]
    if restored_frozen or reclass:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")

    frozen_total = sum(1 for _, o in before.values() if status(o) == FROZEN_STATUS)
    L = ["## KR weekly recapture", "",
         f"- Records before: **{len(before)}** · after: **{len(after)}**",
         f"- `{FROZEN_STATUS}` records held out: **{frozen_total}**",
         f"- Changed: **{len(changed)}** · added: **{len(added)}** · removed: **{len(removed)}**", ""]
    if changed:
        L += ["### Changed products", "", "| ID | Product | Change | Fields |", "|---|---|---|---|"]
        L += [f"| `{esc(i)}` | {esc(n)} | {esc(note)} | {esc(', '.join(fs))} |" for i, n, fs, note in changed]
        L.append("")
    if added:
        L += ["### Added", ""] + [f"- `{esc(i)}` {esc(n)}" for i, n in added] + [""]
    if removed:
        L += ["### Removed", ""] + [f"- `{esc(i)}` {esc(n)}" for i, n in removed] + [""]
    if reclass:
        L += ["### ⚠ Classification left unchanged — needs human check", "",
              "recapture.py tried to change these fields; old values were kept.", ""]
        L += [f"- `{esc(i)}` {esc(n)} — {esc(', '.join(ks))}" for i, n, ks in reclass] + [""]
    if restored_frozen:
        L += [f"### ⚠ `{FROZEN_STATUS}` records were touched and restored", ""]
        L += [f"- `{esc(i)}` {esc(n)}" for i, n in restored_frozen] + [""]
    if not (changed or added or removed):
        L += ["No reformulations detected this week.", ""]
    if log:
        try:
            res = json.load(open(log, encoding="utf-8"))
        except (OSError, ValueError):
            res = None
        if res is not None:
            from collections import Counter
            c = Counter(r.get("status") for r in res)
            L += ["### recapture.py run", "",
                  "- " + " · ".join(f"{k}: **{v}**" for k, v in sorted(c.items())), ""]
            bad = [r for r in res if r.get("status") in ("fetch-failed", "extract-failed")]
            if bad:
                L += ["#### Could not recapture (left as is)", ""]
                L += [f"- `{esc(r.get('id'))}` {esc(r.get('product', ''))} — {r.get('status')}: {esc(r.get('reason', ''))[:160]}" for r in bad]
                L.append("")
    with open(md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "snapshot":
        shutil.copyfile(sys.argv[2], sys.argv[3])
    elif cmd == "check":
        check(*sys.argv[2:6])
    else:
        sys.exit(__doc__)

"""
Jurisdiction-aware formulation fingerprints and change classification.

Why not one hash for everything: the registers do not publish the same
thing, so the same hash would mean different things in different countries
and a change would not be comparable across them.

    US  (DailyMed SPL)  actives with exact %, inactives in FORMULATION order
    CA  (LNHPD)         actives with exact %, inactives as an UNORDERED set
    AU  (ARTG)          actives with mg/g,   excipients ALPHABETICAL (unordered)
    KR  (label, 화장품법 10조)  no concentrations, inactives in ORDER

Two rules follow, and they are the whole design:

  1. Never compare on a signal the source does not carry. Australia prints
     excipients alphabetically, so an "order change" there is meaningless
     and must not raise an event. Korea prints no concentrations, so a
     concentration event can never fire for Korea — its absence is not
     evidence of stability.
  2. Never let OUR coverage changing look like the MARKET changing. When a
     hand-collected excipient list is added to a product that had none, the
     fingerprint moves, but nothing happened in the world. That is a
     coverage event, and it is kept in a separate class so no reformulation
     statistic is ever inflated by our own progress.

Fingerprints are computed over normalised names (core.normalize), so a
register re-typing "GLYCEROL" as "Glycerin" is not a reformulation.
"""

import hashlib
import json

from .normalize import normalize_name, normalize_list

# resolution profile per jurisdiction
PROFILES = {
    "US": {"inactive_order": True,  "actives_concentration": True,
           "source": "FDA DailyMed SPL"},
    "CA": {"inactive_order": False, "actives_concentration": True,
           "source": "Health Canada LNHPD"},
    "AU": {"inactive_order": False, "actives_concentration": True,
           "source": "TGA ARTG"},
    "KR": {"inactive_order": True,  "actives_concentration": False,
           "source": "화장품법 제10조 label"},
    "EU": {"inactive_order": True,  "actives_concentration": False,
           "source": "label / Open Beauty Facts"},
}
# Bump when anything that CHANGES A FINGERPRINT changes: a new synonym, a
# unit that now parses, a profile flip. Every stored fingerprint was
# computed under some version of these rules, so comparing across a rule
# change compares our code, not the market — detect_reformulations.py
# re-baselines instead of publishing hundreds of phantom reformulations.
RULE_VERSION = "2026-08-26.5"   # + grades, unspecified-form, plurals, PEG-n

DEFAULT_PROFILE = {"inactive_order": True, "actives_concentration": True,
                   "source": "unknown"}


def profile_for(jurisdiction):
    return PROFILES.get((jurisdiction or "").upper(), DEFAULT_PROFILE)


def _h(obj):
    return hashlib.sha1(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def _pct(active):
    """Concentration in % w/w, from whichever field the register used."""
    for key in ("percent_w_w", "percent", "concentration_percent"):
        v = active.get(key)
        if isinstance(v, (int, float)):
            return round(float(v), 4)
    qty = active.get("quantity")
    if qty is None:
        qty = active.get("strength_raw")
    unit = str(active.get("unit") or "").strip().lower()
    if qty is not None and not unit:
        # A strength whose unit the source never published (US SPLs, where
        # the upstream scraper reads <numerator value> but not its unit).
        # The number is still stable over time for that product, so it is a
        # valid basis for detecting a change — it is simply not a percentage,
        # and nothing downstream may print it as one.
        try:
            return round(float(qty), 4)
        except (TypeError, ValueError):
            return None
    if isinstance(qty, (int, float)) and qty:
        # One scale: percent w/w. LNHPD alone writes it four ways
        # ("%", "percent", "% (w/w)", "% p/p"), and a unit we fail to
        # recognise would return None — which compares unequal to a number
        # and would fire a concentration event on every single run.
        if unit in ("mg/g", "mg/ml"):
            return round(float(qty) / 10, 4)
        if unit == "ppm":
            return round(float(qty) / 10000, 4)
        if (unit.startswith("%") or unit in ("percent", "pourcent", "pct", "g")):
            return round(float(qty), 4)
    return None


def _ident(name, unii):
    """The identity we compare on.

    A UNII is a government-issued code for the substance itself, so where a
    record carries one it beats any name we could normalise: FDA re-typing
    ".ALPHA.-TOCOPHEROL ACETATE" as "ALPHA-TOCOPHEROL ACETATE" changes the
    string and not the molecule. Prefixed so a UNII can never collide with a
    name, and so a fingerprint says which kind of evidence it rests on.
    """
    if unii:
        return f"U:{unii}"
    n = normalize_name(name)
    return f"N:{n}" if n else ""


def actives_view(rec, profile):
    """[(normalised name, % or None)] sorted by name — order in an actives
    list is registration order, which carries no formulation meaning."""
    out = []
    for a in rec.get("actives") or []:
        ident = _ident(a.get("name"), a.get("unii"))
        if not ident:
            continue
        out.append([ident, _pct(a) if profile["actives_concentration"] else None])
    return sorted(out, key=lambda x: (x[0], str(x[1])))


def inactives_view(rec, profile):
    """Identity list; sorted when the source order is not data.

    `inactive_uniis`, when present, is parallel to `inactives` — same order,
    same length. Anything short or missing falls back to the name, so a
    partly-coded list degrades one ingredient at a time instead of failing.
    """
    names = rec.get("inactives") or rec.get("excipients") or []
    uniis = rec.get("inactive_uniis") or []
    idents = []
    for i, name in enumerate(names):
        ident = _ident(name, uniis[i] if i < len(uniis) else None)
        if ident:
            idents.append(ident)
    return idents if profile["inactive_order"] else sorted(set(idents))


def coverage_of(rec):
    """What we actually hold for this product right now.

    'none' means we have no inactive list at all — which is NOT the same as
    a product with no excipients, and the two must never share a value.
    """
    if rec.get("inactives") or rec.get("excipients"):
        return "full"
    status = str(rec.get("data_status") or "").lower()
    if "unavailable" in status or "not_published" in status:
        return "actives_only_confirmed"   # the register itself has no list
    return "actives_only"                 # we have not collected it yet


def fingerprint(rec):
    """Return the fingerprint block stored on a record and in the state."""
    prof = profile_for(rec.get("jurisdiction"))
    act, inact = actives_view(rec, prof), inactives_view(rec, prof)
    return {
        "actives": act,
        "inactives": inact,
        "fp_actives": _h(act),
        "fp_inactives": _h(inact),
        "fp_full": _h([act, inact]),
        "coverage": coverage_of(rec),
        "n_actives": len(act),
        "n_inactives": len(inact),
        "profile": {"inactive_order": prof["inactive_order"],
                    "actives_concentration": prof["actives_concentration"]},
    }


# Metadata worth logging even when the formulation is untouched: a relabel,
# a sponsor change, a licence revision. "Revised the label four times without
# touching the formula" is itself a finding — and, crucially, keeping these
# OUT of the reformulation class is what stops a date bump from faking one.
META_FIELDS = ("product_name", "company", "dosage_form", "spf_label",
               "status_active", "revised_date", "licence_date",
               "populations", "purposes", "attested_monograph",
               # US: a new SPL version with an identical formulation is a
               # relabel. Worth logging — "this brand revised its label four
               # times in a year and never touched the formula" is a
               # finding — and worth keeping out of the reformulation count.
               "spl_version", "published_date", "ndc")

SEVERITY = {
    "uv_filter_changed": 5,      # a different filter system = a new product
    "active_concentration_changed": 4,
    "inactive_added": 2,
    "inactive_removed": 2,
    "inactive_reordered": 1,     # only where order is data (US, KR)
}


def label(ident):
    """Human-readable form of an identity, for events and reports.

    Fingerprints compare on UNIIs; a person reading the review queue needs a
    substance name. The map is built from whatever the two records carried,
    so it is always the source's own wording, never one we invented.
    """
    if not isinstance(ident, str):
        return ident
    if ident.startswith("N:"):
        return ident[2:]
    return _UNII_LABELS.get(ident[2:], ident)


_UNII_LABELS = {}


def remember_labels(rec):
    """Record UNII -> name pairs seen on a record, for label()."""
    for a in rec.get("actives") or []:
        if a.get("unii") and a.get("name"):
            _UNII_LABELS.setdefault(a["unii"], normalize_name(a["name"]))
    names = rec.get("inactives") or []
    for i, u in enumerate(rec.get("inactive_uniis") or []):
        if u and i < len(names):
            _UNII_LABELS.setdefault(u, normalize_name(names[i]))


def diff_formulation(old_fp, new_fp, profile):
    """Structured difference between two fingerprints of the SAME product."""
    d = {"uv_filter_changed": [], "active_concentration_changed": [],
         "inactive_added": [], "inactive_removed": [],
         "inactive_reordered": False}

    old_a = {n: p for n, p in old_fp.get("actives", [])}
    new_a = {n: p for n, p in new_fp.get("actives", [])}
    for name in sorted(set(old_a) | set(new_a)):
        if name not in old_a:
            d["uv_filter_changed"].append({"filter": label(name), "from": None,
                                           "to": new_a[name]})
        elif name not in new_a:
            d["uv_filter_changed"].append({"filter": label(name),
                                           "from": old_a[name], "to": None})
        elif profile["actives_concentration"] and old_a[name] != new_a[name]:
            d["active_concentration_changed"].append(
                {"filter": label(name), "from": old_a[name],
                 "to": new_a[name]})

    old_i, new_i = old_fp.get("inactives", []), new_fp.get("inactives", [])
    old_s, new_s = set(old_i), set(new_i)
    d["inactive_added"] = sorted(label(i) for i in new_s - old_s)
    d["inactive_removed"] = sorted(label(i) for i in old_s - new_s)
    if profile["inactive_order"] and old_s == new_s and old_i != new_i:
        d["inactive_reordered"] = True
    return d


def classify(old_rec, old_fp, new_rec, new_fp):
    """(docstring below)"""
    """Turn a before/after pair into zero or more events.

    Event kinds:
      new                    first time we have seen this registration
      reformulated           the formulation moved (see `changes` for what)
      metadata               formulation identical, tracked metadata moved
      coverage_gain / loss   OUR data got better or worse — not a market event
      delisted / relisted    the registration left or returned to the register
    """
    events = []
    prof = profile_for(new_rec.get("jurisdiction"))

    cov_old, cov_new = old_fp.get("coverage"), new_fp.get("coverage")
    coverage_moved = cov_old != cov_new
    if coverage_moved:
        kind = ("coverage_gain" if cov_old in ("actives_only", None)
                and cov_new == "full" else
                "coverage_loss" if cov_new in ("actives_only", None)
                and cov_old == "full" else "coverage_change")
        events.append({"change": kind, "coverage_from": cov_old,
                       "coverage_to": cov_new,
                       "note": "our collection changed, not the product"})

    if old_fp.get("fp_full") != new_fp.get("fp_full"):
        d = diff_formulation(old_fp, new_fp, prof)
        # An inactive list appearing for the first time is coverage, not a
        # reformulation. The actives can still be compared — they came from
        # the same source in both snapshots.
        # Either direction: a list arriving, and a list going missing, are
        # both facts about our pipeline. The excipient diff is meaningless
        # when one of the two snapshots never had a list to compare.
        if coverage_moved and (cov_old != "full" or cov_new != "full"):
            d["inactive_added"], d["inactive_removed"] = [], []
            d["inactive_reordered"] = False
        material = (d["uv_filter_changed"] or d["active_concentration_changed"]
                    or d["inactive_added"] or d["inactive_removed"]
                    or d["inactive_reordered"])
        if material:
            sev = max([SEVERITY[k] for k in
                       ("uv_filter_changed", "active_concentration_changed",
                        "inactive_added", "inactive_removed")
                       if d[k]] + ([SEVERITY["inactive_reordered"]]
                                   if d["inactive_reordered"] else []))
            ev = {"change": "reformulated", "severity": sev, "changes": d}
            # Where the ingredient list was typed in by hand (Australia's
            # PDFs, Korea's labels), a difference between two transcriptions
            # can be a transcription slip rather than a reformulation. Say so
            # on the event instead of publishing it as a market finding.
            if (new_rec.get("excipient_source") or "").startswith("curated") \
                    or new_rec.get("collection_method") == "manual":
                ev["needs_confirmation"] = True
                ev["confirm_note"] = ("hand-transcribed source — re-read the "
                                      "original before publishing")
            events.append(ev)

    meta = {}
    for f in META_FIELDS:
        if f in old_rec or f in new_rec:
            a, b = old_rec.get(f), new_rec.get(f)
            if a != b:
                meta[f] = {"from": a, "to": b}
    if meta and not any(e["change"] == "reformulated" for e in events):
        events.append({"change": "metadata", "fields": meta})
    elif meta:
        for e in events:
            if e["change"] == "reformulated":
                e["metadata"] = meta
    return events

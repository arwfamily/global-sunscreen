# Upstream fix — the SPL strength unit is being discarded

**Repo:** `arwfamily/tinysafe-dailymed-scraper-v2`
**File:** `scripts/dailymed_scraper.py`, `_parse_ingredients_xml()`
**Impact:** 2,555 of 6,516 in-scope sunscreens (39%) carry a concentration
that cannot be read. Every percentage statistic from the corpus — zinc
median, filter loading, US-vs-AU comparisons — is blocked until this lands.

## What is happening

The parser takes the numerator's *value* and drops everything that says what
scale it is on:

```python
sm = re.search(r'<numerator[^>]*value="([^"]+)"', b, re.IGNORECASE)
if sm:
    rec["strength"] = sm.group(1)
```

An SPL quantity is a ratio, and both halves carry a unit:

```xml
<quantity>
  <numerator value="50" unit="mg"/>
  <denominator value="1" unit="g"/>
</quantity>
```

That product is **5% octisalate**. The corpus records `"strength": "50"`.
Read as a percentage it becomes 50% — twice the legal ceiling for any
monographed filter.

How we found it: 43% of in-scope products failed a plausibility check
(0.5–30%), and the failures cluster exactly where mg/g would put them —
octisalate 50 (=5%), homosalate 100 and 150 (=10%, 15%), zinc oxide 200
(=20%). Those are all normal formulations wearing the wrong scale.

The ambiguity is not recoverable afterwards. A zinc oxide filed as `20` may
be 20% or 20 mg/g (2%), and nothing left in the file distinguishes them. It
has to be captured at parse time.

## The patch

```python
        if want_active:
            q = re.search(
                r'<quantity>(.*?)</quantity>', b,
                re.IGNORECASE | re.DOTALL)
            block = q.group(1) if q else b
            num = re.search(
                r'<numerator[^>]*value="([^"]+)"[^>]*?(?:unit="([^"]*)")?',
                block, re.IGNORECASE)
            den = re.search(
                r'<denominator[^>]*value="([^"]+)"[^>]*?(?:unit="([^"]*)")?',
                block, re.IGNORECASE)
            if num:
                rec["strength"] = num.group(1)              # unchanged, for
                rec["strength_value"] = _num(num.group(1))  # compatibility
                rec["strength_unit"] = (num.group(2) or "").strip()
                rec["denominator_value"] = _num(den.group(1)) if den else None
                rec["denominator_unit"] = ((den.group(2) or "").strip()
                                           if den else "")
                rec["percent_w_w"] = to_percent(
                    rec["strength_value"], rec["strength_unit"],
                    rec["denominator_value"], rec["denominator_unit"])
```

with two helpers:

```python
def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


# SPL numerator/denominator pairs seen on sunscreen labels, in order of how
# often they appear. Anything not listed returns None — an unrecognised unit
# must not silently become a percentage.
_MASS = {"mg": 0.001, "g": 1.0, "ug": 1e-6, "mcg": 1e-6, "kg": 1000.0}


def to_percent(value, unit, den_value, den_unit):
    """Percent w/w, or None when the pair cannot be converted.

    mg/g and mg/mL are treated the same: a sunscreen is not dilute enough for
    the density difference to matter at label resolution, and the alternative
    is discarding the number. Flag it if you want to be stricter.
    """
    if value is None:
        return None
    u, du = (unit or "").lower(), (den_unit or "").lower()
    den = den_value or 1.0
    if u in ("%", "pct"):
        return round(value, 4)
    if u in _MASS and du in _MASS:                    # mg / g
        return round(value * _MASS[u] / (den * _MASS[du]) * 100, 4)
    if u in _MASS and du in ("ml", "l"):              # mg / mL, assume 1 g/mL
        ml = den * (1000.0 if du == "l" else 1.0)
        return round(value * _MASS[u] / ml * 100, 4)
    return None
```

## What to check after the run

The plausibility test that found the bug is the acceptance test for the fix:

```python
bad = [(r["product_name"], a["name"], a.get("percent_w_w"))
       for r in records for a in r["active_ingredients"]
       if a.get("percent_w_w") is not None
       and not 0.5 <= a["percent_w_w"] <= 30]
```

Expect **near zero**. Anything left is a genuinely odd SPL worth reading by
hand, not a parsing artefact. Two specific numbers to eyeball, because we
already know what they should be: zinc oxide should land at a **20%
median**, and no monographed filter should exceed **25%**.

Also worth adding to the record, since the fix is already in that function:

- `strength_source: "spl_xml_quantity"` — so a later change of method is
  visible rather than silent.
- keep `strength` exactly as it is. `global-sunscreen` compares the raw filed
  number to detect changes, and rewriting history in place would make every
  product look reformulated on the day of the fix.

## On the global-sunscreen side

Nothing needs to change there when this lands. The adapter already reads
`percent_w_w` first and falls back to the estimate, so the day the corpus
carries real percentages, `percent_w_w` stops being null and
`concentration_status` can be dropped from the records. Until then:

- `percent_w_w` is **null** on every US record — no invented numbers.
- `percent_estimate` + `estimate_basis` (`assumed_percent` /
  `assumed_mg_per_g`) carry a documented reading for exploratory work only.
- reformulation detection is **unaffected**: it compares the raw filed
  number, which is on a consistent scale for a given product over time.

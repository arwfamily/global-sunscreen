# global-sunscreen

Every sunscreen a government register will tell us about, its full
ingredient list where that is published, and a daily check on whether any
of those formulations moved.

Two questions this repo exists to answer:

1. **What is actually in the sunscreens on sale in each country?**
   Not what a brand says. What is filed with, or legally printed for, the
   regulator.
2. **Did it change?** Registers publish today's truth and overwrite
   yesterday's. Nobody keeps the diff. From the day we start watching, we
   do — and a reformulation history is the one asset a competitor cannot
   buy later, because the past is gone.

---

## Coverage today

| | Register | Products | Full ingredient list | Concentrations | Updates |
|---|---|---|---|---|---|
| 🇺🇸 US | FDA DailyMed (SPL) | 6,516¹ | 6,467 | filed **without units** ⚠ | weekly upstream |
| 🇨🇦 CA | Health Canada LNHPD | 1,910 | 1,896 | exact %, actives | daily API |
| 🇦🇺 AU | TGA ARTG | 501 | 500 | mg/g, actives | manual export + PDFs |
| 🇰🇷 KR | product labels (화장품법 10조) | *your sheet* | all | none¹ | manual |

¹ From the 13,285-SPL corpus in `tinysafe-dailymed-scraper-v2`, scoped to
the sunscreen category; 6,769 makeup / lip balm / diaper cream / calamine
records that the UV-filter net also caught are kept in `us_excluded.jsonl`
with their reason. **Every US ingredient carries a UNII** — FDA's substance
code — so US records are compared on a government identifier rather than on
a name.

⚠ US concentrations are **not publishable**: the upstream scraper reads
`<numerator value>` without its unit, so a strength of 50 may be 5% or 50%.
`percent_w_w` is null on every US record and `percent_estimate` carries a
documented assumption. Change detection is unaffected — it compares the raw
filed number. Fix: `docs/upstream_unit_patch.md`.

² Korea publishes no concentration, but the list is in legally-mandated
descending order, so **position is the concentration signal** — a zinc oxide
at position 2 is a high load. A handful of brands volunteer ppm and that is
parsed into a real percentage.

**What is not covered, and why** — a coverage table that hides its holes is
worse than no table:

- **Canada holds mineral sunscreens only.** With mineral filters a sunscreen
  is a Natural Health Product (NPN) and lands in LNHPD. With chemical filters
  it is a drug (DIN) and lands in the Drug Product Database, which publishes
  active ingredients but **no excipients**, with up to a six-month delay for
  sunscreens.
- **The US net is cast on 19 UV-filter UNIIs.** A sunscreen whose actives are
  all outside that set is not collected. That is a far better net than the
  520-product pre-filtered feed it replaced — which had been filtered to
  100%-mineral baby products, making every "does the US market use X"
  question circular — but it is still a net, not a census.
- **EU/UK have no product-level government source at all.** Cosmetic
  notifications (CPNP) are authority-only. What the EU does publish is the
  regulation itself — `eu_annex_vi.jsonl`, 33 UV filters with legal maxima.
- **Australia is hand-collected on purpose.** tga.gov.au disallows automated
  access, and excipients exist only in per-product PDFs. The official bulk
  export is the spine; excipients are transcribed into
  `data/raw/au/au_sunscreens.json`, which is the file to keep updating.

---

## The shape

```
data/raw/<country>/          L0. Exactly what the source gave us.
        ↓  adapters/         one file per register, no rules of its own
data/canonical/<c>_ingredients.jsonl    today's truth, one shape
        ↓  detect_reformulations.py     the ONLY place a change is declared
data/events/<c>_events.jsonl            append-only. never rewritten.
data/events/review_queue.md             what a human should look at
        ↓  build_global.py
data/canonical/global_sunscreens.jsonl  every country, one vocabulary
data/canonical/global_summary.json
```

Collection and judgement are separate on purpose. A collector that decides
what "changed" writes its opinion into the record and cannot be corrected
afterwards. Keeping detection in one place means one rule set for every
country, and a corrected rule can be re-run over data already held.

---

## The monitor's rules

A register moving is not the same as a formulation moving. These are the
rules that keep the two apart — all of them are in
`tests/test_detection.py`, which CI runs before anything is collected.

**Resolution differs by country, so the comparison must too.**

| | actives | inactive order |
|---|---|---|
| US | filed without units (raw number compared) | **is data** — a reorder is a ratio change |
| CA | exact % | names only — order ignored |
| AU | mg/g | alphabetical — order ignored, always |
| KR | none | **is data** (legal descending order) |

Australia's excipients are printed alphabetically; treating a reorder there
as a reformulation would generate a wall of noise. Korea's order *is* the
only concentration signal it gives; ignoring it there would silence the
country's most useful signal.

**Never let our own coverage look like the market moving.** An excipient
list arriving for the first time is `coverage_gain`, not a reformulation. A
list going missing is `coverage_loss` — a pipeline alarm, never published as
a market event. "The register publishes no list" (`actives_only_confirmed`)
and "we have not collected it yet" (`actives_only`) are different values and
never share one.

**Compare on an identifier where one exists.** US records carry a UNII on
every ingredient, so the fingerprint uses `U:<unii>` and falls back to
`N:<normalised name>` only where there is none. FDA re-typing
`.ALPHA.-TOCOPHEROL ACETATE` as `ALPHA-TOCOPHEROL ACETATE` cannot look like
a reformulation; a different substance under an unchanged name still can.

**Never let a name change look like a formula change.** `core/normalize.py`
folds GLYCEROL / Glycerin / 글리세린 into one ingredient, mg/g into %, and
`20` / `20.0` / `"percent"` / `"% (w/w)"` into one number.

**Never publish our own rule change as market movement.** Every fingerprint
records the `RULE_VERSION` it was computed under. Bump it and the next run
re-baselines silently, logging one `rebaselined` event instead of thousands
of phantom reformulations.

**Flag what a human should confirm.** A difference between two
hand-transcribed lists (AU PDFs, KR labels) may be a transcription slip, so
those events carry `needs_confirmation: true` and land in
`data/events/review_queue.md` rather than in a published statistic.

Event kinds: `new` · `reformulated` (severity 1–5) · `metadata` ·
`coverage_gain` / `coverage_loss` · `delisted` / `relisted` · `rebaselined`.

Severity: filter added or removed = 5, concentration changed = 4, excipient
added or removed = 2, order changed = 1.

---

## Running it

```bash
python collect_au_artg.py        # offline: ARTG export + curated JSON
python collect_us_dailymed.py    # one HTTP GET
python collect_kr_labels.py      # offline: data/raw/kr/*.csv
python collect_ca_lnhpd.py       # networked, ~2h cold start, resumable
python detect_reformulations.py  # every country, or: ... AU CA
python build_global.py
python tests/test_detection.py   # before touching core/ or an adapter
```

CI runs all of it daily (`.github/workflows/collect.yml`), fast collectors
first, Canada second, detection last. `.github/publish.sh` is the only place
this repo talks to git.

Canada's two clocks, both env-tunable: `CA_REWALK_DAYS` (default 7) is how
stale the product *list* may get before the bulk tables are walked again —
the only way a newly registered product is ever discovered.
`CA_MAX_AGE_DAYS` (default 30) is how stale any one product's *formulation*
may get; products are re-fetched oldest-first, because Health Canada leaves
`revised_date` empty on most licences and a trigger-only design would miss
silent edits. `CA_FORCE_REWALK=1` walks everything now.

---

## Adding a country

1. `adapters/<xx>_<register>.py` — map the register's fields onto the
   canonical record. No judgement, no change detection.
2. `collect_<xx>_*.py` — write `data/raw/<xx>/` and
   `data/canonical/<xx>_ingredients.jsonl`.
3. Add the jurisdiction's resolution profile to `PROFILES` in
   `core/fingerprint.py` — does the register publish concentrations, and is
   the inactive order data?
4. Add a line to the coverage table above, including what it does *not*
   cover.

Detection, the global merge and the CI step need no changes: they discover
`data/canonical/*_ingredients.jsonl` on their own.

Queued: Japan (薬用化粧品, product-level bulk still unconfirmed), China NMPA
(1.8M cosmetic filings, ingredient data public but behind a captcha), EU/UK
(regulatory axis only — no product register exists).

---

## Reading a number out of this repo

`global_summary.json` carries a `publishes` line per country and a
`caveats` list. Both exist because the honest version of a cross-country
statistic always needs them:

- Canada's mineral share is ~99% **because the register only holds mineral
  products**, not because Canada sells almost no chemical sunscreen.
- A US ingredient frequency from the current feed describes baby mineral
  sunscreens, not the US market. We have already been burned by this once:
  a "0% use butyloctyl salicylate" figure was an artefact of the filter.
- Australia's excipient lists carry no concentration, so a shared excipient
  set means a shared formulation *base*, not a chemically identical product.

`build_global.py` also clusters products whose full excipient set is
identical and marks a cluster `cross_company` when its members belong to
different companies — the measurement behind "Same Formula, Different
Label". It runs per country, never across borders: US and AU formulation
fingerprints overlap in zero pairs, which is itself the finding.

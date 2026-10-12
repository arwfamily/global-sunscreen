# kr/ — Korean baby sunscreen DB (moved from Muse `~/workspace/kr-data/`)

```
kr/kr_ingredients.jsonl        149 records
kr/recapture/recapture.py      re-fetches text sources, diffs ingredients_ko
kr/recapture/diff.py
kr/recapture/extractors.py     per-site extractors (stdlib only)
kr/recapture/logs/             recapture-YYYY-MM-DD.json per run
```

`.github/workflows/weekly-recapture.yml` runs `recapture.py --apply` every
Monday 09:16 America/New_York (replaces Muse cron `kr-recapture-monthly`),
then `tools/kr_recapture_guard.py`:

- `derived-needs-human-check` records are restored verbatim if touched
  (recapture.py already skips them: their source is `derived-same-formula`)
- `mineral_only` / `uv_filters_ko` are never recalculated — old values are
  kept and the product is listed for human check
- the run summary lists reformulated products and every fetch/extract failure

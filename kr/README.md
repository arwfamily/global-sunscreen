# kr/ — Korean baby sunscreen DB (moved from Muse `~/workspace/kr-data/`)

Upload Muse's folder here as-is:

```
kr/kr_ingredients.jsonl
kr/recapture/recapture.py   (+ requirements.txt if it has one)
kr/recapture/logs/
```

`.github/workflows/weekly-recapture.yml` runs `recapture.py --apply` every
Monday 09:16 America/New_York, then `tools/kr_recapture_guard.py`:

- `derived-needs-human-check` records are restored verbatim if touched
- `mineral_only` / UV-filter fields are never recalculated — old values are
  kept and the product is listed for human check in the run summary

`~/workspace/kr-data` is symlinked to this folder on the runner, so
hard-coded Muse paths keep working.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

US-stock **volume-surge scanner**: finds tickers whose latest-day trading volume spiked
many times above their recent baseline (small-cap/penny focus), then **cross-validates**
each candidate across independent free data sources before market open. Output is a
*candidate list*, never a trade signal — surfaced numbers must survive cross-validation
before being trusted, and the tool deliberately never places orders.

## Commands

```powershell
python -m pip install -r requirements.txt   # deps: requests, pandas, yfinance
python scanner.py                            # scan → output/surge_<date>.csv
python verify.py                             # cross-validate latest surge CSV → output/verified_<date>.csv
.\run_scan.ps1                               # runs scanner.py then verify.py, logs to logs/
```

Scheduling (Windows Task Scheduler, runs `run_scan.ps1` daily 22:00 KST = pre-market):
```powershell
powershell -ExecutionPolicy Bypass -File .\register_task.ps1   # register
Start-ScheduledTask -TaskName VolumeSurgeScanner               # run now
Unregister-ScheduledTask -TaskName VolumeSurgeScanner -Confirm:$false
```

There is no build/lint/test setup — it's a two-script project. Validate changes by running
`scanner.py` / `verify.py` against live data.

## Architecture

Two-stage pipeline, file-coupled via `output/surge_<date>.csv`:

1. **scanner.py** — single source (Polygon). Pulls the `grouped daily` endpoint
   (`/v2/aggs/grouped/...`) which returns *every* US ticker's OHLCV for one date in **one
   call**, iterating backward over calendar days (skipping weekends/empty responses) until
   N trading days are collected. Surge ratio = `latest_volume / median(prior days' volume)`.
   Noise filters (price band, min baseline/latest/dollar volume) run in `compute_surge`.

2. **verify.py** — multi-channel cross-check of scanner's top-N. Independently recomputes
   the surge ratio from **Yahoo (yfinance)** and compares against Polygon; Polygon↔Yahoo
   volume deviation beyond `vol_tolerance_pct` → `⚠ CHECK`. Also pulls **Stooq** (best-effort;
   micro-caps often 404 → skipped) and **Finnhub** (only if key present). Verdict logic lives
   in `main()`: `✅ CONFIRMED` requires Yahoo to independently confirm the surge AND channel
   agreement. This stage exists specifically to kill single-source false positives.

**Polygon free tier = 5 calls/min**, so `scanner.py` sleeps `rate_sleep_seconds` (default 13)
between grouped-daily calls — a 7-day scan takes ~90s. A paid key should set
`"rate_sleep_seconds": 1` in config.

## Config & conventions

- **config.json** (gitignore-worthy, holds plaintext API keys) is required; copy from
  `config.example.json`. Keys: `polygon_api_key` (required), `finnhub_api_key` (optional).
  Both are overridable by env vars `POLYGON_API_KEY` / `FINNHUB_API_KEY` (env wins).
- `config.json["scan"]` tunes the scanner; `config.json["verify"]` tunes cross-validation
  (defaults are filled in code via `setdefault` in `verify.load_config`, so the section is optional).
- **50x surge is rare** — `volume_surge_threshold` is the headline filter but expect 0–2 hits
  most days; `watch_threshold` (10x) is the practical working set.
- Both scripts call `sys.stdout.reconfigure(encoding="utf-8")` at import — required for Korean
  console output on Windows. Keep this when editing. CSVs are written `utf-8-sig` for Excel.
- `verify.py`'s `premkt_chg_%` is meaningful only when run during US pre-market hours
  (~17:00–22:30 KST); outside those hours yfinance `fast_info` reports the last *regular*
  session, not live pre-market.

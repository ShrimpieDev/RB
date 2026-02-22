# BTC Reya vs Binance 1m Price Tracker (5m Updates)

This repository tracks and compares **Binance Futures BTCUSDT mark price** vs **Reya BTC market price** every 5 minutes using GitHub Actions.

## What it tracks

On each run, the script fetches 1-minute candles and builds a merged minute-by-minute dataset:

- Binance Futures mark price candles (`BTCUSDT`) from:
  - `GET https://fapi.binance.com/fapi/v1/markPriceKlines`
- Reya market candle history (`BTCRUSDPERP`) from:
  - `GET https://api.reya.xyz/v2/candleHistory/{symbol}/{resolution}`

For each minute, the output includes:

- `ts_utc`
- `binance_mark_close`
- `reya_close`
- `abs_diff` = `reya - binance`
- `diff_pct` = `(reya - binance) / binance * 100`
- `updated_at_utc`

## Output data

Updated on every run:

- `data/btc_reya_vs_binance_1m.csv`
- `data/btc_reya_vs_binance_1m.json`

The dataset always keeps a **rolling last 24 hours** by default (`1440` rows).

## Scheduler

GitHub Actions workflow:

- Cron: every 5 minutes (`*/5 * * * *`)
- Manual: `workflow_dispatch`

Workflow file:

- `.github/workflows/track-btc-5m.yml`

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/compare_prices_5m.py
```

## Configuration (environment variables)

- `REYA_SYMBOL` (default: `BTCRUSDPERP`)
- `ROWS` (default: `1440`)
- `OUT_DIR` (default: `data`)

Optional:

- `BINANCE_SYMBOL` (default: `BTCUSDT`)
- `RESOLUTION` (default: `1m`)
- `REQUEST_TIMEOUT_SECONDS` (default: `20`)
- `MAX_RETRIES` (default: `3`)
- `BACKOFF_SECONDS` (default: `1.5`)
- `BINANCE_BASE_URL` (default: `https://fapi.binance.com`)

### Examples

```bash
REYA_SYMBOL=BTCRUSDPERP ROWS=1440 OUT_DIR=data python scripts/compare_prices_5m.py
```

```bash
REYA_SYMBOL=BTCRUSDPERP ROWS=720 python scripts/compare_prices_5m.py
```

## Notes on robustness

- Uses UTC timestamps everywhere.
- Normalizes candles to exact minute boundaries.
- Keeps rows even when one source is missing (`null` close and diffs).
- Includes retry logic with backoff for transient HTTP failures.
- Provides clear parser errors if API response shape changes.

## GitHub Actions 451 error (Binance)

If your workflow fails with HTTP `451` from `fapi.binance.com`, your runner region is blocked by Binance for futures endpoints.

This repo now handles that gracefully: the run still succeeds and writes rows with `binance_mark_close=null` while Reya data continues to update.

If you want to try another Binance host, set a repository variable:

- `BINANCE_BASE_URL` (for example, a region-allowed Binance futures API base URL)

Then add it to workflow env (already supported in script via env var).

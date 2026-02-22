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
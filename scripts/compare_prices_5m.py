#!/usr/bin/env python3
"""Fetch and compare Binance Futures BTCUSDT mark price vs Reya BTC candles."""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import requests  # type: ignore
except ImportError:
    requests = None

from urllib.parse import urlencode
from urllib.request import Request, urlopen


BINANCE_BASE_URL = os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com")
BINANCE_URL = f"{BINANCE_BASE_URL.rstrip('/')}/fapi/v1/markPriceKlines"

REYA_URL_TEMPLATE = "https://api.reya.xyz/v2/candleHistory/{symbol}/{resolution}"
BINANCE_SYMBOL = os.getenv("BINANCE_SYMBOL", "BTCUSDT")
REYA_SYMBOL = os.getenv("REYA_SYMBOL", "BTCRUSDPERP")
RESOLUTION = os.getenv("RESOLUTION", "1m")
ROWS = int(os.getenv("ROWS", "1440"))
OUT_DIR = Path(os.getenv("OUT_DIR", "data"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
BACKOFF_SECONDS = float(os.getenv("BACKOFF_SECONDS", "1.5"))


class FetchError(RuntimeError):
    pass


@dataclass
class CandlePoint:
    ts_ms: int
    close: Optional[float]


def floor_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def iso_utc_from_ms(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%SZ")


def build_row(ts_ms: int, binance_close: Optional[float], reya_close: Optional[float], updated_at: str) -> Dict[str, Any]:
    abs_diff: Optional[float] = None
    diff_pct: Optional[float] = None

    if binance_close is not None and reya_close is not None:
        abs_diff = reya_close - binance_close
        if binance_close != 0:
            diff_pct = (abs_diff / binance_close) * 100

    return {
        "ts_utc": iso_utc_from_ms(ts_ms),
        "binance_mark_close": binance_close,
        "reya_close": reya_close,
        "abs_diff": abs_diff,
        "diff_pct": diff_pct,
        "updated_at_utc": updated_at,
    }


def request_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if requests is not None:
                response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.json()

            query = f"?{urlencode(params)}" if params else ""
            req = Request(url + query, headers={"User-Agent": "btc-compare-bot/1.0"})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)

        except Exception as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            sleep_seconds = BACKOFF_SECONDS * attempt
            print(f"Retry {attempt}/{MAX_RETRIES} for {url} after error: {exc}", file=sys.stderr)
            time.sleep(sleep_seconds)

    raise FetchError(f"Failed to fetch {url}: {last_error}")


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_to_minute_ms(ts_ms: int) -> int:
    return (ts_ms // 60000) * 60000


def parse_binance_payload(payload: Any) -> List[CandlePoint]:
    if not isinstance(payload, list):
        raise FetchError("Unexpected Binance response")

    points: List[CandlePoint] = []
    for item in payload:
        if not isinstance(item, list) or len(item) < 5:
            continue
        ts_ms = normalize_to_minute_ms(int(item[0]))
        close = to_float(item[4])
        points.append(CandlePoint(ts_ms=ts_ms, close=close))

    return points


def parse_reya_payload(payload: Any) -> List[CandlePoint]:
    candles: Optional[Iterable[Any]] = None

    if isinstance(payload, list):
        candles = payload
    elif isinstance(payload, dict):
        for key in ("candles", "data", "result", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                candles = value
                break

    if candles is None:
        raise FetchError("Unexpected Reya response")

    points: List[CandlePoint] = []

    for candle in candles:
        ts_ms: Optional[int] = None
        close: Optional[float] = None

        if isinstance(candle, list) and len(candle) >= 5:
            ts_ms = int(candle[0])
            close = to_float(candle[4])

        elif isinstance(candle, dict):
            ts_raw = next((candle.get(k) for k in ("timestamp", "time", "t", "openTime", "open_time") if k in candle), None)
            if ts_raw is not None:
                ts_int = int(float(ts_raw))
                if ts_int < 10**12:
                    ts_int *= 1000
                ts_ms = ts_int

            close = next((to_float(candle.get(k)) for k in ("close", "c", "closePrice", "close_price") if k in candle), None)

        if ts_ms is not None:
            points.append(CandlePoint(ts_ms=normalize_to_minute_ms(ts_ms), close=close))

    if not points:
        raise FetchError("No Reya candle points found")

    return points


def fetch_binance(window_start_ms: int, now_ms: int) -> Dict[int, Optional[float]]:
    params = {
        "symbol": BINANCE_SYMBOL,
        "interval": RESOLUTION,
        "limit": max(ROWS + 60, 1500),
        "startTime": window_start_ms,
        "endTime": now_ms,
    }
    payload = request_json(BINANCE_URL, params=params)
    points = parse_binance_payload(payload)
    return {p.ts_ms: p.close for p in points}


def fetch_reya(window_start_ms: int, now_ms: int) -> Dict[int, Optional[float]]:
    url = REYA_URL_TEMPLATE.format(symbol=REYA_SYMBOL, resolution=RESOLUTION)

    payload = request_json(url, params={
        "startTime": window_start_ms,
        "endTime": now_ms,
        "limit": max(ROWS + 60, 1500),
    })

    points = parse_reya_payload(payload)
    return {p.ts_ms: p.close for p in points}


def write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "ts_utc",
        "binance_mark_close",
        "reya_close",
        "abs_diff",
        "diff_pct",
        "updated_at_utc",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: List[Dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
        f.write("\n")


def main() -> int:
    now = floor_to_minute(datetime.now(timezone.utc))
    latest_minute = now - timedelta(minutes=1)
    first_minute = latest_minute - timedelta(minutes=ROWS - 1)

    window_start_ms = int(first_minute.timestamp() * 1000)
    now_ms = int(now.timestamp() * 1000)
    updated_at = now.strftime("%Y-%m-%d %H:%M:%SZ")

    binance_map: Dict[int, Optional[float]] = {}
    reya_map: Dict[int, Optional[float]] = {}

    binance_error: Optional[Exception] = None
    reya_error: Optional[Exception] = None

    try:
        binance_map = fetch_binance(window_start_ms, now_ms)
    except FetchError as exc:
        binance_error = exc
        print(f"WARN: Binance fetch failed — continuing with null Binance values. {exc}", file=sys.stderr)

    try:
        reya_map = fetch_reya(window_start_ms, now_ms)
    except FetchError as exc:
        reya_error = exc
        print(f"WARN: Reya fetch failed — continuing with null Reya values. {exc}", file=sys.stderr)

    if binance_error and reya_error:
        raise FetchError(f"Both sources failed. Binance: {binance_error}; Reya: {reya_error}")

    minute_timestamps = [window_start_ms + i * 60000 for i in range(ROWS)]

    rows = [
        build_row(ts, binance_map.get(ts), reya_map.get(ts), updated_at)
        for ts in minute_timestamps
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(rows, OUT_DIR / "btc_reya_vs_binance_1m.csv")
    write_json(rows, OUT_DIR / "btc_reya_vs_binance_1m.json")

    print(f"Wrote {len(rows)} rows successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
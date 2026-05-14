#!/usr/bin/env python3
"""Download Alpaca historical quotes into the HFT simulator CSV format."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo


HEADER = ["timestamp_ns", "symbol", "bid_price", "ask_price", "bid_size", "ask_size"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--window-minutes", type=int, default=60)
    parser.add_argument(
        "--chunk-minutes",
        type=int,
        default=0,
        help="Split each market window into smaller API windows; 0 downloads the full day in one API window.",
    )
    parser.add_argument("--output-dir", default="Portfolio Quotes/SPY_open60")
    parser.add_argument("--feed", default="iex", choices=["iex", "sip", "otc"])
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--request-retries", type=int, default=5)
    parser.add_argument("--retry-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--max-retry-sleep-seconds", type=float, default=30.0)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--progress-pages", type=int, default=0)
    parser.add_argument(
        "--fixed-1330-utc",
        action="store_true",
        help="Use the legacy fixed 13:30 UTC window instead of the actual NYSE open.",
    )
    return parser.parse_args()


def parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def business_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    dates: list[dt.date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current)
        current += dt.timedelta(days=1)
    return dates


def market_window_start_utc(day: dt.date, fixed_1330_utc: bool) -> dt.datetime:
    if fixed_1330_utc:
        return dt.datetime.combine(day, dt.time(13, 30), tzinfo=dt.timezone.utc)
    start = dt.datetime.combine(day, dt.time(9, 30), tzinfo=ZoneInfo("America/New_York"))
    return start.astimezone(dt.timezone.utc)


def datetime_to_api(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def market_window_utc(day: dt.date, minutes: int, fixed_1330_utc: bool) -> tuple[str, str]:
    start = market_window_start_utc(day, fixed_1330_utc)
    end = start + dt.timedelta(minutes=minutes)
    return datetime_to_api(start), datetime_to_api(end)


def chunked_market_windows_utc(
    day: dt.date,
    window_minutes: int,
    chunk_minutes: int,
    fixed_1330_utc: bool,
) -> list[tuple[str, str]]:
    start = market_window_start_utc(day, fixed_1330_utc)
    end = start + dt.timedelta(minutes=window_minutes)
    if chunk_minutes <= 0 or chunk_minutes >= window_minutes:
        return [(datetime_to_api(start), datetime_to_api(end))]

    windows: list[tuple[str, str]] = []
    chunk_start = start
    chunk_delta = dt.timedelta(minutes=chunk_minutes)
    while chunk_start < end:
        chunk_end = min(chunk_start + chunk_delta, end)
        windows.append((datetime_to_api(chunk_start), datetime_to_api(chunk_end)))
        chunk_start = chunk_end
    return windows


def timestamp_to_ns(value: str) -> int:
    text = value.rstrip("Z")
    if "." in text:
        main, frac = text.split(".", 1)
    else:
        main, frac = text, ""
    stamp = dt.datetime.strptime(main, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    frac = (frac + "0" * 9)[:9]
    return int(stamp.timestamp()) * 1_000_000_000 + int(frac or "0")


def request_json(
    url: str,
    key: str,
    secret: str,
    retries: int,
    retry_sleep_seconds: float,
    max_retry_sleep_seconds: float,
    timeout_seconds: float,
) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    retryable_http_statuses = {429, 500, 502, 503, 504}
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in retryable_http_statuses or attempt >= retries:
                raise
        except (
            ConnectionResetError,
            http.client.RemoteDisconnected,
            socket.timeout,
            TimeoutError,
            urllib.error.URLError,
        ):
            if attempt >= retries:
                raise
        time.sleep(min(retry_sleep_seconds * (2**attempt), max_retry_sleep_seconds))
    raise RuntimeError("unreachable retry loop")


def download_day(
    symbol: str,
    day: dt.date,
    output_path: Path,
    key: str,
    secret: str,
    feed: str,
    limit: int,
    window_minutes: int,
    chunk_minutes: int,
    fixed_1330_utc: bool,
    sleep_seconds: float,
    request_retries: int,
    retry_sleep_seconds: float,
    max_retry_sleep_seconds: float,
    timeout_seconds: float,
    progress_pages: int,
) -> int:
    windows = chunked_market_windows_utc(day, window_minutes, chunk_minutes, fixed_1330_utc)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_pages = 0
    row_count = 0
    last_written_timestamp_ns = -1
    temp_path = output_path.with_name(f"{output_path.name}.tmp")
    try:
        with temp_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADER)
            for window_index, (start_iso, end_iso) in enumerate(windows, start=1):
                page_token = ""
                while True:
                    params = {
                        "symbols": symbol,
                        "start": start_iso,
                        "end": end_iso,
                        "feed": feed,
                        "limit": str(limit),
                        "sort": "asc",
                    }
                    if page_token:
                        params["page_token"] = page_token
                    url = "https://data.alpaca.markets/v2/stocks/quotes?" + urllib.parse.urlencode(params)
                    payload = request_json(
                        url=url,
                        key=key,
                        secret=secret,
                        retries=request_retries,
                        retry_sleep_seconds=retry_sleep_seconds,
                        max_retry_sleep_seconds=max_retry_sleep_seconds,
                        timeout_seconds=timeout_seconds,
                    )
                    total_pages += 1
                    quotes = payload.get("quotes", {}).get(symbol, [])
                    for quote in quotes:
                        bid = float(quote.get("bp") or 0.0)
                        ask = float(quote.get("ap") or 0.0)
                        if bid <= 0.0 or ask <= bid:
                            continue
                        timestamp_ns = timestamp_to_ns(str(quote["t"]))
                        if timestamp_ns <= last_written_timestamp_ns:
                            continue
                        writer.writerow(
                            [
                                timestamp_ns,
                                symbol,
                                f"{bid:.6f}",
                                f"{ask:.6f}",
                                float(quote.get("bs") or 0.0),
                                float(quote.get("as") or 0.0),
                            ]
                        )
                        last_written_timestamp_ns = timestamp_ns
                        row_count += 1

                    page_token = payload.get("next_page_token") or ""
                    if progress_pages > 0 and total_pages % progress_pages == 0:
                        print(
                            (
                                f"progress date={day} window={window_index}/{len(windows)} "
                                f"pages={total_pages} rows={row_count}"
                            ),
                            flush=True,
                        )
                    if not page_token:
                        print(
                            (
                                f"chunk_done date={day} window={window_index}/{len(windows)} "
                                f"rows={row_count}"
                            ),
                            flush=True,
                        )
                        break
                    time.sleep(sleep_seconds)
        temp_path.replace(output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return row_count


def main() -> int:
    args = parse_args()
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in the environment.")

    symbol = args.symbol.upper()
    output_dir = Path(args.output_dir)
    for day in business_dates(parse_date(args.start_date), parse_date(args.end_date)):
        path = output_dir / f"{symbol.lower()}_{day:%Y_%m_%d}.csv"
        if args.skip_existing and path.exists() and path.stat().st_size > 200:
            print(f"skip_existing date={day} path={path}", flush=True)
            continue
        try:
            rows = download_day(
                symbol=symbol,
                day=day,
                output_path=path,
                key=key,
                secret=secret,
                feed=args.feed,
                limit=args.limit,
                window_minutes=args.window_minutes,
                chunk_minutes=args.chunk_minutes,
                fixed_1330_utc=args.fixed_1330_utc,
                sleep_seconds=args.sleep_seconds,
                request_retries=args.request_retries,
                retry_sleep_seconds=args.retry_sleep_seconds,
                max_retry_sleep_seconds=args.max_retry_sleep_seconds,
                timeout_seconds=args.timeout_seconds,
                progress_pages=args.progress_pages,
            )
            print(f"downloaded date={day} rows={rows} path={path}", flush=True)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"failed date={day} http_status={exc.code} reason={body[:300]}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"failed date={day} error={exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

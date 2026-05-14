#!/usr/bin/env python3
"""Repair real quote datasets by downloading only missing or non-ok sessions."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMD,TSLA")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--window-minutes", type=int, default=60)
    parser.add_argument("--chunk-minutes", type=int, default=5)
    parser.add_argument("--feed", default="iex")
    parser.add_argument("--quote-base-dir", default="Portfolio Quotes")
    parser.add_argument("--results-dir", default="hft_microstructure/Results")
    parser.add_argument("--download-script", default="scripts/download_alpaca_quotes.py")
    parser.add_argument("--manifest-script", default="scripts/build_quote_manifest.py")
    parser.add_argument("--min-duration-minutes", type=float, default=55.0)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--request-retries", type=int, default=15)
    parser.add_argument("--retry-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--max-retry-sleep-seconds", type=float, default=30.0)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--progress-pages", type=int, default=20)
    parser.add_argument(
        "--max-downloads-per-symbol",
        type=int,
        default=0,
        help="Safety valve for incremental runs; 0 means no cap.",
    )
    parser.add_argument(
        "--target-ok-sessions",
        type=int,
        default=0,
        help="Stop repairing a symbol once this many ok sessions exist; 0 means repair the full range.",
    )
    parser.add_argument(
        "--target-buffer-days",
        type=int,
        default=5,
        help="Extra candidate days to try when targeting a minimum ok-session count.",
    )
    parser.add_argument(
        "--exclude-dates",
        default="2026-04-03",
        help="Comma-separated dates to skip, useful for market holidays in the requested range.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def split_csv(value: str) -> list[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def split_dates(value: str) -> set[dt.date]:
    return {parse_date(item.strip()) for item in value.split(",") if item.strip()}


def business_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    dates: list[dt.date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current)
        current += dt.timedelta(days=1)
    return dates


def run(command: list[str], env: dict[str, str] | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        env=env,
        capture_output=capture,
        text=True,
    )


def stream_run(command: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    completed = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    captured: list[str] = []
    assert completed.stdout is not None
    for line in completed.stdout:
        captured.append(line)
        print(line, end="", flush=True)
    return_code = completed.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command, output="".join(captured))
    return return_code, "".join(captured)


def manifest_path(results_dir: Path, symbol: str) -> Path:
    return results_dir / f"alpaca_{symbol.lower()}_quote_manifest.csv"


def quote_dir(base_dir: Path, symbol: str, window_minutes: int) -> Path:
    return base_dir / f"{symbol}_open{window_minutes}"


def quote_path(directory: Path, symbol: str, day: dt.date) -> Path:
    return directory / f"{symbol.lower()}_{day:%Y_%m_%d}.csv"


def build_manifest(args: argparse.Namespace, symbol: str) -> Path:
    results_dir = Path(args.results_dir)
    path = manifest_path(results_dir, symbol)
    run(
        [
            "python3",
            args.manifest_script,
            "--quote-dir",
            str(quote_dir(Path(args.quote_base_dir), symbol, args.window_minutes)),
            "--output-path",
            str(path),
            "--min-duration-minutes",
            str(args.min_duration_minutes),
        ]
    )
    return path


def read_statuses(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(newline="") as handle:
        return {row["date"]: row["status"].strip() for row in csv.DictReader(handle)}


def ok_dates(statuses: dict[str, str]) -> set[str]:
    return {date for date, status in statuses.items() if status == "ok"}


def target_limited_repair_days(
    repair_days: list[dt.date],
    current_ok_count: int,
    target_ok_sessions: int,
    target_buffer_days: int,
) -> list[dt.date]:
    if target_ok_sessions <= 0:
        return repair_days
    needed = max(target_ok_sessions - current_ok_count, 0)
    return [] if needed == 0 else repair_days[: needed + target_buffer_days]


def download_day(args: argparse.Namespace, symbol: str, day: dt.date) -> bool:
    env = os.environ.copy()
    command = [
        "python3",
        args.download_script,
        "--symbol",
        symbol,
        "--start-date",
        f"{day:%Y-%m-%d}",
        "--end-date",
        f"{day:%Y-%m-%d}",
        "--window-minutes",
        str(args.window_minutes),
        "--chunk-minutes",
        str(args.chunk_minutes),
        "--output-dir",
        str(quote_dir(Path(args.quote_base_dir), symbol, args.window_minutes)),
        "--feed",
        args.feed,
        "--limit",
        str(args.limit),
        "--request-retries",
        str(args.request_retries),
        "--retry-sleep-seconds",
        str(args.retry_sleep_seconds),
        "--max-retry-sleep-seconds",
        str(args.max_retry_sleep_seconds),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--progress-pages",
        str(args.progress_pages),
    ]
    _, output = stream_run(command, env=env)
    return f"downloaded date={day:%Y-%m-%d}" in output


def write_coverage(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    excluded_dates = split_dates(args.exclude_dates)
    expected_days = [day for day in business_dates(start, end) if day not in excluded_dates]
    coverage_rows: list[dict[str, object]] = []

    for symbol in split_csv(args.symbols):
        print(f"repair_symbol symbol={symbol}", flush=True)
        qdir = quote_dir(Path(args.quote_base_dir), symbol, args.window_minutes)
        qdir.mkdir(parents=True, exist_ok=True)
        current_manifest = build_manifest(args, symbol)
        statuses = read_statuses(current_manifest)
        current_ok = ok_dates(statuses)

        repair_days: list[dt.date] = []
        for day in expected_days:
            date_text = f"{day:%Y-%m-%d}"
            file_exists = quote_path(qdir, symbol, day).exists()
            if statuses.get(date_text) == "ok" and file_exists:
                continue
            repair_days.append(day)

        if args.target_ok_sessions > 0:
            repair_days = target_limited_repair_days(
                repair_days,
                current_ok_count=len(current_ok),
                target_ok_sessions=args.target_ok_sessions,
                target_buffer_days=args.target_buffer_days,
            )
        if args.max_downloads_per_symbol > 0:
            repair_days = repair_days[: args.max_downloads_per_symbol]

        print(
            (
                f"repair_plan symbol={symbol} expected={len(expected_days)} "
                f"ok_before={len(current_ok)} repair_days={len(repair_days)}"
            ),
            flush=True,
        )

        attempted = 0
        downloaded = 0
        failed: list[str] = []
        for day in repair_days:
            if args.target_ok_sessions > 0 and len(current_ok) + downloaded >= args.target_ok_sessions:
                break
            print(f"repair_day symbol={symbol} date={day:%Y-%m-%d}", flush=True)
            if args.dry_run:
                continue
            attempted += 1
            if download_day(args, symbol, day):
                downloaded += 1
            else:
                failed.append(f"{day:%Y-%m-%d}")

        final_manifest = build_manifest(args, symbol)
        final_statuses = read_statuses(final_manifest)
        final_ok = ok_dates(final_statuses)
        coverage_rows.append(
            {
                "symbol": symbol,
                "start_date": f"{start:%Y-%m-%d}",
                "end_date": f"{end:%Y-%m-%d}",
                "expected_weekdays": len(expected_days),
                "ok_before": len(current_ok),
                "ok_after": len(final_ok),
                "repair_candidates": len(repair_days),
                "attempted_downloads": attempted,
                "successful_downloads": downloaded,
                "failed_dates": ";".join(failed),
                "manifest": str(final_manifest),
                "quote_dir": str(qdir),
            }
        )
        print(
            (
                f"repair_done symbol={symbol} ok_after={len(final_ok)} "
                f"attempted={attempted} downloaded={downloaded}"
            ),
            flush=True,
        )

    coverage_path = Path(args.results_dir) / "alpaca_real_quote_coverage_summary.csv"
    write_coverage(coverage_path, coverage_rows)
    print(f"coverage_summary={coverage_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a quote-data quality manifest for simulator input CSVs."""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path


EXPECTED_HEADER = ["timestamp_ns", "symbol", "bid_price", "ask_price", "bid_size", "ask_size"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-dir", default="Portfolio Quotes/SPY_open60")
    parser.add_argument("--output-path", default="build/alpaca_verification/quote_manifest.csv")
    parser.add_argument("--min-duration-minutes", type=float, default=55.0)
    return parser.parse_args()


def date_from_path(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) >= 4 and all(part.isdigit() for part in parts[-3:]):
        return "-".join(parts[-3:])
    return ""


def symbol_from_path(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) >= 4 and all(part.isdigit() for part in parts[-3:]):
        return "_".join(parts[:-3]).upper()
    return ""


def quote_stats(path: Path) -> dict[str, object]:
    invalid_rows = 0
    row_count = 0
    first_ts = ""
    last_ts = ""
    min_bid = float("inf")
    max_ask = float("-inf")
    spreads: list[float] = []

    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        header_ok = header == EXPECTED_HEADER
        for row in reader:
            if len(row) != 6:
                invalid_rows += 1
                continue
            try:
                ts = row[0]
                bid = float(row[2])
                ask = float(row[3])
            except ValueError:
                invalid_rows += 1
                continue
            if bid <= 0.0 or ask <= bid:
                invalid_rows += 1
                continue
            if row_count == 0:
                first_ts = ts
            last_ts = ts
            row_count += 1
            min_bid = min(min_bid, bid)
            max_ask = max(max_ask, ask)
            spreads.append(((ask - bid) / ((ask + bid) * 0.5)) * 10000.0)

    status_parts: list[str] = []
    if not header_ok:
        status_parts.append("bad_header")
    if row_count == 0:
        status_parts.append("empty")
    elif row_count <= 100:
        status_parts.append("thin")
    if invalid_rows:
        status_parts.append(f"invalid_rows={invalid_rows}")

    return {
        "row_count": row_count,
        "first_timestamp_ns": first_ts,
        "last_timestamp_ns": last_ts,
        "duration_minutes": ((int(last_ts) - int(first_ts)) / 60_000_000_000.0) if first_ts and last_ts else 0.0,
        "min_bid": min_bid if row_count else 0.0,
        "max_ask": max_ask if row_count else 0.0,
        "mean_spread": statistics.fmean(spreads) if spreads else 0.0,
        "median_spread": statistics.median(spreads) if spreads else 0.0,
        "min_spread": min(spreads) if spreads else 0.0,
        "max_spread": max(spreads) if spreads else 0.0,
        "status": "ok" if not status_parts else ";".join(status_parts),
    }


def status_with_duration(base_status: str, duration_minutes: float, min_duration_minutes: float) -> str:
    parts = [] if base_status == "ok" else base_status.split(";")
    if base_status != "empty" and duration_minutes < min_duration_minutes:
        parts.append(f"partial_window={duration_minutes:.2f}m")
    return "ok" if not parts else ";".join(parts)


def main() -> int:
    args = parse_args()
    quote_dir = Path(args.quote_dir)
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for path in sorted(quote_dir.glob("*.csv")):
        try:
            stats = quote_stats(path)
        except Exception as exc:  # noqa: BLE001
            stats = {
                "row_count": 0,
                "first_timestamp_ns": "",
                "last_timestamp_ns": "",
                "duration_minutes": 0.0,
                "min_bid": 0.0,
                "max_ask": 0.0,
                "mean_spread": 0.0,
                "median_spread": 0.0,
                "min_spread": 0.0,
                "max_spread": 0.0,
                "status": f"read_error: {exc}",
            }
        rows.append(
            {
                "date": date_from_path(path),
                "symbol": symbol_from_path(path),
                "file_path": str(path.resolve()),
                "row_count": stats["row_count"],
                "first_timestamp_ns": stats["first_timestamp_ns"],
                "last_timestamp_ns": stats["last_timestamp_ns"],
                "duration_minutes": f"{float(stats['duration_minutes']):.4f}",
                "min_bid": f"{float(stats['min_bid']):.6f}",
                "max_ask": f"{float(stats['max_ask']):.6f}",
                "mean_spread": f"{float(stats['mean_spread']):.8f}",
                "median_spread": f"{float(stats['median_spread']):.8f}",
                "min_spread": f"{float(stats['min_spread']):.8f}",
                "max_spread": f"{float(stats['max_spread']):.8f}",
                "status": status_with_duration(
                    str(stats["status"]),
                    float(stats["duration_minutes"]),
                    args.min_duration_minutes,
                ),
            }
        )

    with output_path.open("w", newline="") as handle:
        fieldnames = [
            "date",
            "symbol",
            "file_path",
            "row_count",
            "first_timestamp_ns",
            "last_timestamp_ns",
            "duration_minutes",
            "min_bid",
            "max_ask",
            "mean_spread",
            "median_spread",
            "min_spread",
            "max_spread",
            "status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"manifest={output_path} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

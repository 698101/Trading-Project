#!/usr/bin/env python3
"""One-command real-quote evidence workflow for the HFT microstructure project."""

from __future__ import annotations

import argparse
import subprocess


DEFAULT_SYMBOLS = "SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMD,TSLA"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--window-minutes", type=int, default=60)
    parser.add_argument("--chunk-minutes", type=int, default=5)
    parser.add_argument("--feed", default="iex")
    parser.add_argument("--quote-base-dir", default="Portfolio Quotes")
    parser.add_argument("--results-dir", default="hft_microstructure/Results")
    parser.add_argument("--work-dir", default="build/real_quote_symbol_suite")
    parser.add_argument("--exe", default="hft_microstructure/hft_portfolio")
    parser.add_argument("--max-sessions", type=int, default=51)
    parser.add_argument("--target-ok-sessions", type=int, default=0)
    parser.add_argument("--target-buffer-days", type=int, default=5)
    parser.add_argument("--exclude-dates", default="2026-04-03")
    parser.add_argument("--max-downloads-per-symbol", type=int, default=0)
    parser.add_argument("--run-stress", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--run-latency", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--seeds", default="1337,2027,9001")
    parser.add_argument("--adverse-selection-bps", default="0,0.25,0.5,1,2")
    parser.add_argument("--latencies-us", default="0,1000,10000,100000")
    parser.add_argument("--skip-repair", action="store_true")
    parser.add_argument("--repair-only", action="store_true")
    return parser.parse_args()


def run(command: list[str]) -> None:
    print("run " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    args = parse_args()
    if not args.skip_repair:
        run(
            [
                "python3",
                "scripts/repair_real_quote_data.py",
                "--symbols",
                args.symbols,
                "--start-date",
                args.start_date,
                "--end-date",
                args.end_date,
                "--window-minutes",
                str(args.window_minutes),
                "--chunk-minutes",
                str(args.chunk_minutes),
                "--feed",
                args.feed,
                "--quote-base-dir",
                args.quote_base_dir,
                "--results-dir",
                args.results_dir,
                "--target-ok-sessions",
                str(args.target_ok_sessions),
                "--target-buffer-days",
                str(args.target_buffer_days),
                "--exclude-dates",
                args.exclude_dates,
                "--max-downloads-per-symbol",
                str(args.max_downloads_per_symbol),
            ]
        )
    if args.repair_only:
        return 0

    suite_command = [
        "python3",
        "scripts/run_real_quote_symbol_suite.py",
        "--symbols",
        args.symbols,
        "--start-date",
        args.start_date,
        "--end-date",
        args.end_date,
        "--window-minutes",
        str(args.window_minutes),
        "--feed",
        args.feed,
        "--quote-base-dir",
        args.quote_base_dir,
        "--results-dir",
        args.results_dir,
        "--work-dir",
        args.work_dir,
        "--exe",
        args.exe,
        "--max-sessions",
        str(args.max_sessions),
        "--skip-download",
        "--seeds",
        args.seeds,
        "--adverse-selection-bps",
        args.adverse_selection_bps,
        "--latencies-us",
        args.latencies_us,
    ]
    suite_command.append("--run-stress" if args.run_stress else "--no-run-stress")
    suite_command.append("--run-latency" if args.run_latency else "--no-run-latency")
    run(suite_command)

    run(
        [
            "python3",
            "scripts/analyze_real_quote_evidence.py",
            "--symbols",
            args.symbols,
            "--results-dir",
            args.results_dir,
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

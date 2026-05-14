#!/usr/bin/env python3
"""Download, validate, and backtest real quote data across multiple symbols.

This is a thin orchestrator around the existing download, manifest, backtest,
stress, and latency scripts. It keeps the evidence collection repeatable and
symbol-agnostic without changing simulator behavior.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
from pathlib import Path


DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "TSLA"]
SUMMARY_FIELDNAMES = [
    "symbol",
    "quote_dir",
    "manifest",
    "ok_sessions",
    "backtest_sessions",
    "full_total_pnl_bps",
    "full_minute_sharpe",
    "full_worst_drawdown_bps",
    "full_trade_count",
    "full_latency_expired_signals",
    "mm_total_pnl_bps",
    "mm_minute_sharpe",
    "mm_worst_drawdown_bps",
    "mm_trade_count",
    "mm_latency_expired_signals",
    "status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--start-date", default="2026-03-01")
    parser.add_argument("--end-date", default="2026-05-12")
    parser.add_argument("--window-minutes", type=int, default=60)
    parser.add_argument("--chunk-minutes", type=int, default=5)
    parser.add_argument("--feed", default="iex")
    parser.add_argument("--quote-base-dir", default="Portfolio Quotes")
    parser.add_argument("--work-dir", default="build/real_quote_symbol_suite")
    parser.add_argument("--results-dir", default="hft_microstructure/Results")
    parser.add_argument("--exe", default="hft_microstructure/hft_portfolio")
    parser.add_argument("--download-script", default="scripts/download_alpaca_quotes.py")
    parser.add_argument("--manifest-script", default="scripts/build_quote_manifest.py")
    parser.add_argument("--backtest-script", default="scripts/run_hft_quote_backtests.py")
    parser.add_argument("--stress-script", default="scripts/run_hft_stress_grid.py")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--max-sessions", type=int, default=51)
    parser.add_argument("--min-duration-minutes", type=float, default=55.0)
    parser.add_argument("--run-stress", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--run-latency", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--seeds", default="1337,2027,9001")
    parser.add_argument("--adverse-selection-bps", default="0,0.25,0.5,1,2")
    parser.add_argument("--portfolio-modes", default="full,mm-only")
    parser.add_argument("--latencies-us", default="0,1000,10000,100000")
    parser.add_argument("--request-retries", type=int, default=15)
    parser.add_argument("--retry-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--max-retry-sleep-seconds", type=float, default=30.0)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--progress-pages", type=int, default=20)
    return parser.parse_args()


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def read_summary_row(path: Path) -> dict[str, str]:
    with path.open(newline="") as handle:
        return next(csv.DictReader(handle))


def count_ok_sessions(path: Path) -> int:
    with path.open(newline="") as handle:
        return sum(1 for row in csv.DictReader(handle) if row.get("status") == "ok")


def empty_summary_row(symbol: str, quote_dir: Path, manifest_path: Path, status: str) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in SUMMARY_FIELDNAMES}
    row.update(
        {
            "symbol": symbol,
            "quote_dir": str(quote_dir),
            "manifest": str(manifest_path),
            "ok_sessions": 0,
            "status": status,
        }
    )
    return row


def write_summary(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"summary={path}")


def copy_result(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_latency_sensitivity(
    results_dir: Path,
    work_dir: Path,
    symbol: str,
    latencies_us: list[str],
) -> None:
    rows: list[dict[str, object]] = []
    for latency in latencies_us:
        for portfolio_mode, suffix in [("full", ""), ("mm-only", "_mm_only")]:
            path = work_dir / f"latency_{latency}us{suffix}" / "results_summary.csv"
            if not path.exists():
                continue
            source_row = read_summary_row(path)
            rows.append(
                {
                    "symbol": symbol,
                    "portfolio_mode": portfolio_mode,
                    "signal_latency_us": latency,
                    "sessions": source_row.get("sessions", ""),
                    "total_pnl_bps": source_row.get("total_pnl_bps", ""),
                    "avg_daily_return_bps": source_row.get("avg_daily_return_bps", ""),
                    "minute_sharpe": source_row.get("minute_sharpe", ""),
                    "worst_drawdown_bps": source_row.get("worst_drawdown_bps", ""),
                    "trade_count": source_row.get("trade_count", ""),
                    "latency_expired_signals": source_row.get("latency_expired_signals", ""),
                    "quote_source": source_row.get("quote_source", ""),
                }
            )

    if not rows:
        return
    output_path = results_dir / f"alpaca_{symbol.lower()}_real_quote_latency_sensitivity.csv"
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def copy_latency_results(
    results_dir: Path,
    work_dir: Path,
    symbol: str,
    latencies_us: list[str],
) -> None:
    for latency in latencies_us:
        for suffix in ["", "_mm_only"]:
            source_dir = work_dir / f"latency_{latency}us{suffix}"
            result_suffix = f"latency_{latency}us{suffix}"
            summary_path = source_dir / "results_summary.csv"
            daily_path = source_dir / "daily_results.csv"
            if summary_path.exists():
                copy_result(
                    summary_path,
                    results_dir / f"alpaca_{symbol.lower()}_real_quote_{result_suffix}_summary.csv",
                )
            if daily_path.exists():
                copy_result(
                    daily_path,
                    results_dir / f"alpaca_{symbol.lower()}_real_quote_{result_suffix}_daily_results.csv",
                )


def main() -> int:
    args = parse_args()
    symbols = [symbol.upper() for symbol in split_csv(args.symbols)]
    results_dir = Path(args.results_dir)
    work_dir = Path(args.work_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    for symbol in symbols:
        quote_dir = Path(args.quote_base_dir) / f"{symbol}_open{args.window_minutes}"
        manifest_path = results_dir / f"alpaca_{symbol.lower()}_quote_manifest.csv"
        symbol_work_dir = work_dir / symbol.lower()
        backtest_dir = symbol_work_dir / "real_quote_backtest"
        mm_dir = symbol_work_dir / "real_quote_backtest_mm_only"
        stress_dir = symbol_work_dir / "real_quote_stress"

        if not args.skip_download:
            run(
                [
                    "python3",
                    args.download_script,
                    "--symbol",
                    symbol,
                    "--start-date",
                    args.start_date,
                    "--end-date",
                    args.end_date,
                    "--window-minutes",
                    str(args.window_minutes),
                    "--chunk-minutes",
                    str(args.chunk_minutes),
                    "--output-dir",
                    str(quote_dir),
                    "--feed",
                    args.feed,
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
                    "--skip-existing",
                ]
            )

        run(
            [
                "python3",
                args.manifest_script,
                "--quote-dir",
                str(quote_dir),
                "--output-path",
                str(manifest_path),
                "--min-duration-minutes",
                str(args.min_duration_minutes),
            ]
        )

        ok_sessions = count_ok_sessions(manifest_path)
        manifest_row = empty_summary_row(symbol, quote_dir, manifest_path, "manifest_only")
        manifest_row["ok_sessions"] = ok_sessions
        manifest_rows.append(manifest_row)
        if args.manifest_only:
            continue

        if ok_sessions == 0:
            summary_rows.append(empty_summary_row(symbol, quote_dir, manifest_path, "no_complete_sessions"))
            continue

        max_sessions = min(args.max_sessions, ok_sessions)

        run(
            [
                "python3",
                args.backtest_script,
                "--manifest",
                str(manifest_path),
                "--exe",
                args.exe,
                "--output-dir",
                str(backtest_dir),
                "--max-sessions",
                str(max_sessions),
            ]
        )
        run(
            [
                "python3",
                args.backtest_script,
                "--manifest",
                str(manifest_path),
                "--exe",
                args.exe,
                "--output-dir",
                str(mm_dir),
                "--max-sessions",
                str(max_sessions),
                "--portfolio-mode",
                "mm-only",
            ]
        )

        if args.run_stress:
            run(
                [
                    "python3",
                    args.stress_script,
                    "--manifest",
                    str(manifest_path),
                    "--exe",
                    args.exe,
                    "--output-dir",
                    str(stress_dir),
                    "--max-sessions",
                    str(max_sessions),
                    "--seeds",
                    args.seeds,
                    "--adverse-selection-bps",
                    args.adverse_selection_bps,
                    "--portfolio-modes",
                    args.portfolio_modes,
                ]
            )

        if args.run_latency:
            for latency in split_csv(args.latencies_us):
                run(
                    [
                        "python3",
                        args.backtest_script,
                        "--manifest",
                        str(manifest_path),
                        "--exe",
                        args.exe,
                        "--output-dir",
                        str(symbol_work_dir / f"latency_{latency}us"),
                        "--max-sessions",
                        str(max_sessions),
                        "--signal-latency-us",
                        latency,
                    ]
                )
                run(
                    [
                        "python3",
                        args.backtest_script,
                        "--manifest",
                        str(manifest_path),
                        "--exe",
                        args.exe,
                        "--output-dir",
                        str(symbol_work_dir / f"latency_{latency}us_mm_only"),
                        "--max-sessions",
                        str(max_sessions),
                        "--portfolio-mode",
                        "mm-only",
                        "--signal-latency-us",
                        latency,
                    ]
                )

        full_summary = read_summary_row(backtest_dir / "results_summary.csv")
        mm_summary = read_summary_row(mm_dir / "results_summary.csv")
        copy_result(
            backtest_dir / "results_summary.csv",
            results_dir / f"alpaca_{symbol.lower()}_real_quote_results_summary.csv",
        )
        copy_result(
            backtest_dir / "daily_results.csv",
            results_dir / f"alpaca_{symbol.lower()}_real_quote_daily_results.csv",
        )
        copy_result(
            mm_dir / "results_summary.csv",
            results_dir / f"alpaca_{symbol.lower()}_real_quote_mm_only_summary.csv",
        )
        copy_result(
            mm_dir / "daily_results.csv",
            results_dir / f"alpaca_{symbol.lower()}_real_quote_mm_only_daily_results.csv",
        )
        if args.run_stress:
            copy_result(
                stress_dir / "stress_combo_results.csv",
                results_dir / f"alpaca_{symbol.lower()}_real_quote_stress_combo_results.csv",
            )
            copy_result(
                stress_dir / "stress_distribution_summary.csv",
                results_dir / f"alpaca_{symbol.lower()}_real_quote_stress_distribution_summary.csv",
            )
        if args.run_latency:
            latencies_us = split_csv(args.latencies_us)
            copy_latency_results(results_dir, symbol_work_dir, symbol, latencies_us)
            write_latency_sensitivity(results_dir, symbol_work_dir, symbol, latencies_us)
        summary_rows.append(
            {
                "symbol": symbol,
                "quote_dir": str(quote_dir),
                "manifest": str(manifest_path),
                "ok_sessions": ok_sessions,
                "backtest_sessions": full_summary.get("sessions", ""),
                "full_total_pnl_bps": full_summary.get("total_pnl_bps", ""),
                "full_minute_sharpe": full_summary.get("minute_sharpe", ""),
                "full_worst_drawdown_bps": full_summary.get("worst_drawdown_bps", ""),
                "full_trade_count": full_summary.get("trade_count", ""),
                "full_latency_expired_signals": full_summary.get("latency_expired_signals", ""),
                "mm_total_pnl_bps": mm_summary.get("total_pnl_bps", ""),
                "mm_minute_sharpe": mm_summary.get("minute_sharpe", ""),
                "mm_worst_drawdown_bps": mm_summary.get("worst_drawdown_bps", ""),
                "mm_trade_count": mm_summary.get("trade_count", ""),
                "mm_latency_expired_signals": mm_summary.get("latency_expired_signals", ""),
                "status": "ok",
            }
        )

    manifest_summary_path = results_dir / "alpaca_real_quote_cross_symbol_manifest_summary.csv"
    if args.manifest_only:
        write_summary(manifest_summary_path, manifest_rows)
        return 0

    write_summary(
        results_dir / "alpaca_real_quote_cross_symbol_summary.csv",
        summary_rows,
    )
    write_summary(manifest_summary_path, manifest_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

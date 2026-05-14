#!/usr/bin/env python3
"""Run real-quote HFT stress tests across seeds, penalties, and portfolio modes."""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="build/alpaca_verification/quote_manifest.csv")
    parser.add_argument("--exe", default="hft_microstructure/hft_portfolio")
    parser.add_argument("--output-dir", default="build/alpaca_verification/real_quote_stress")
    parser.add_argument("--max-sessions", type=int, default=30)
    parser.add_argument("--seeds", default="1337,2027,9001")
    parser.add_argument("--adverse-selection-bps", default="0,0.25,0.5,1,2")
    parser.add_argument("--portfolio-modes", default="full,mm-only")
    parser.add_argument("--rolling-window", type=int, default=75)
    parser.add_argument("--min-edge-bps", type=float, default=0.20)
    parser.add_argument("--forecast-weight", type=float, default=0.70)
    parser.add_argument("--min-reentry-events", type=int, default=40)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-gross-exposure", type=float, default=1.0)
    parser.add_argument("--forecast-mode", default="heuristic")
    parser.add_argument("--decision-mode", default="off")
    parser.add_argument("--signal-latency-us", type=int, default=0)
    parser.add_argument("--mm-min-entry-microprice-edge-100ms-bps", type=float, default=0.0)
    parser.add_argument("--mm-min-entry-spread-100ms-bps", type=float, default=0.0)
    parser.add_argument("--mm-max-entry-side-imbalance-1s", type=float, default=1.0)
    return parser.parse_args()


def split_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def split_floats(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def split_strings(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def read_manifest(path: Path, max_sessions: int) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["status"] == "ok"]
    return rows[:max_sessions]


def parse_stdout_metrics(text: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.startswith("sleeve="):
            continue
        key, value = line.split("=", 1)
        metrics[key.strip()] = value.strip()
    return metrics


def read_interval_returns(path: Path) -> list[float]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [float(row["return_bps"]) for row in csv.DictReader(handle)]


def sample_sharpe(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    std = math.sqrt(variance)
    return 0.0 if std == 0.0 else mean / std


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def max_drawdown_bps(interval_returns: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in interval_returns:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def run_session(
    args: argparse.Namespace,
    row: dict[str, str],
    output_dir: Path,
    portfolio_mode: str,
    seed: int,
    adverse_selection_bps: float,
) -> dict[str, object]:
    date = row["date"]
    symbol = row.get("symbol") or Path(row["file_path"]).stem.split("_")[0].upper()
    penalty_tag = str(adverse_selection_bps).replace(".", "p")
    prefix = output_dir / (
        f"runs/{portfolio_mode}/seed_{seed}/adv_{penalty_tag}/"
        f"{symbol.lower()}_{date.replace('-', '_')}"
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(Path(args.exe)),
        row["file_path"],
        "--rolling-window",
        str(args.rolling_window),
        "--min-edge-bps",
        str(args.min_edge_bps),
        "--forecast-weight",
        str(args.forecast_weight),
        "--min-reentry-events",
        str(args.min_reentry_events),
        "--interval-seconds",
        str(args.interval_seconds),
        "--max-gross-exposure",
        str(args.max_gross_exposure),
        "--seed",
        str(seed),
        "--forecast-mode",
        args.forecast_mode,
        "--portfolio-mode",
        portfolio_mode,
        "--decision-mode",
        args.decision_mode,
        "--adverse-selection-bps",
        str(adverse_selection_bps),
        "--signal-latency-us",
        str(args.signal_latency_us),
        "--mm-min-entry-microprice-edge-100ms-bps",
        str(args.mm_min_entry_microprice_edge_100ms_bps),
        "--mm-min-entry-spread-100ms-bps",
        str(args.mm_min_entry_spread_100ms_bps),
        "--mm-max-entry-side-imbalance-1s",
        str(args.mm_max_entry_side_imbalance_1s),
        "--output-prefix",
        str(prefix),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    metrics = parse_stdout_metrics(completed.stdout)
    return {
        "portfolio_mode": portfolio_mode,
        "seed": seed,
        "adverse_selection_bps": adverse_selection_bps,
        "date": date,
        "symbol": symbol,
        "row_count": row["row_count"],
        "prefix": str(prefix),
        "processed_quotes": metrics.get("processed_quotes", ""),
        "completed_trades": metrics.get("completed_trades", ""),
        "total_net_return_bps": metrics.get("total_net_return_bps", ""),
        "max_drawdown_bps": metrics.get("max_drawdown_bps", ""),
        "minute_return_sharpe": metrics.get("minute_return_sharpe", ""),
        "latency_expired_signals": metrics.get("latency_expired_signals", ""),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def summarize_combo(
    portfolio_mode: str,
    seed: int,
    adverse_selection_bps: float,
    daily_rows: list[dict[str, object]],
) -> dict[str, object]:
    daily_pnls = [float(row["total_net_return_bps"]) for row in daily_rows]
    all_intervals: list[float] = []
    total_trades = 0
    for row in daily_rows:
        total_trades += int(row["completed_trades"])
        all_intervals.extend(read_interval_returns(Path(f"{row['prefix']}_intervals.csv")))

    losing_days = sum(1 for value in daily_pnls if value < 0.0)
    total_pnl = sum(daily_pnls)
    return {
        "portfolio_mode": portfolio_mode,
        "seed": seed,
        "adverse_selection_bps": adverse_selection_bps,
        "sessions": len(daily_rows),
        "total_pnl_bps": f"{total_pnl:.6f}",
        "avg_daily_pnl_bps": f"{(total_pnl / len(daily_rows)):.6f}",
        "median_daily_pnl_bps": f"{percentile(daily_pnls, 0.50):.6f}",
        "p05_daily_pnl_bps": f"{percentile(daily_pnls, 0.05):.6f}",
        "p95_daily_pnl_bps": f"{percentile(daily_pnls, 0.95):.6f}",
        "losing_days": losing_days,
        "loss_day_rate": f"{(losing_days / len(daily_rows)):.6f}",
        "minute_sharpe": f"{sample_sharpe(all_intervals):.12f}",
        "worst_drawdown_bps": f"{max_drawdown_bps(all_intervals):.6f}",
        "trade_count": total_trades,
    }


def summarize_distribution(combo_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, float], list[dict[str, object]]] = {}
    for row in combo_rows:
        key = (str(row["portfolio_mode"]), float(row["adverse_selection_bps"]))
        grouped.setdefault(key, []).append(row)

    output: list[dict[str, object]] = []
    for (portfolio_mode, adverse), rows in sorted(grouped.items()):
        pnls = [float(row["total_pnl_bps"]) for row in rows]
        sharpes = [float(row["minute_sharpe"]) for row in rows]
        dds = [float(row["worst_drawdown_bps"]) for row in rows]
        output.append(
            {
                "portfolio_mode": portfolio_mode,
                "adverse_selection_bps": adverse,
                "runs": len(rows),
                "mean_total_pnl_bps": f"{(sum(pnls) / len(pnls)):.6f}",
                "median_total_pnl_bps": f"{percentile(pnls, 0.50):.6f}",
                "p05_total_pnl_bps": f"{percentile(pnls, 0.05):.6f}",
                "mean_minute_sharpe": f"{(sum(sharpes) / len(sharpes)):.12f}",
                "median_minute_sharpe": f"{percentile(sharpes, 0.50):.12f}",
                "p05_minute_sharpe": f"{percentile(sharpes, 0.05):.12f}",
                "mean_worst_drawdown_bps": f"{(sum(dds) / len(dds)):.6f}",
                "worst_drawdown_bps": f"{min(dds):.6f}",
                "positive_pnl_run_rate": f"{(sum(1 for value in pnls if value > 0.0) / len(pnls)):.6f}",
            }
        )
    return output


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sessions = read_manifest(Path(args.manifest), args.max_sessions)
    seeds = split_ints(args.seeds)
    penalties = split_floats(args.adverse_selection_bps)
    portfolio_modes = split_strings(args.portfolio_modes)

    daily_output: list[dict[str, object]] = []
    combo_output: list[dict[str, object]] = []
    for portfolio_mode in portfolio_modes:
        for adverse in penalties:
            for seed in seeds:
                combo_daily = []
                for session in sessions:
                    row = run_session(args, session, output_dir, portfolio_mode, seed, adverse)
                    combo_daily.append(row)
                    daily_output.append(row)
                summary = summarize_combo(portfolio_mode, seed, adverse, combo_daily)
                combo_output.append(summary)
                print(
                    "stress_combo "
                    f"mode={portfolio_mode} seed={seed} adverse_bps={adverse} "
                    f"pnl_bps={summary['total_pnl_bps']} "
                    f"sharpe={summary['minute_sharpe']}",
                    flush=True,
                )
                write_csv(output_dir / "stress_daily_results.csv", daily_output)
                write_csv(output_dir / "stress_combo_results.csv", combo_output)
                write_csv(
                    output_dir / "stress_distribution_summary.csv",
                    summarize_distribution(combo_output),
                )

    print(f"stress_daily_results={output_dir / 'stress_daily_results.csv'}")
    print(f"stress_combo_results={output_dir / 'stress_combo_results.csv'}")
    print(f"stress_distribution_summary={output_dir / 'stress_distribution_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

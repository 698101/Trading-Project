#!/usr/bin/env python3
"""Summarize real-quote HFT evidence with conservative confidence diagnostics."""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMD,TSLA")
    parser.add_argument("--results-dir", default="hft_microstructure/Results")
    parser.add_argument("--output-csv", default="hft_microstructure/Results/real_quote_evidence_ci.csv")
    parser.add_argument("--output-report", default="hft_microstructure/Results/real_quote_robustness_report.md")
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1337)
    return parser.parse_args()


def split_csv(value: str) -> list[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def first_row(path: Path) -> dict[str, str] | None:
    rows = read_csv(path)
    return rows[0] if rows else None


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_mean_ci(values: list[float], samples: int, rng: random.Random) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0]
    estimates = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        estimates.append(sum(draw) / len(draw))
    return percentile(estimates, 0.025), percentile(estimates, 0.975)


def manifest_counts(path: Path) -> tuple[int, int]:
    rows = read_csv(path)
    ok = sum(1 for row in rows if row.get("status", "").strip() == "ok")
    return ok, len(rows)


def daily_pnls(rows: list[dict[str, str]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        try:
            values.append(float(row["total_net_return_bps"]))
        except (KeyError, ValueError):
            continue
    return values


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def evidence_rows(args: argparse.Namespace) -> list[dict[str, object]]:
    rng = random.Random(args.seed)
    rows: list[dict[str, object]] = []
    results_dir = Path(args.results_dir)
    for symbol in split_csv(args.symbols):
        manifest = results_dir / f"alpaca_{symbol.lower()}_quote_manifest.csv"
        ok_sessions, manifest_rows = manifest_counts(manifest)
        for portfolio_mode, suffix in [("full", "real_quote_results"), ("mm-only", "real_quote_mm_only")]:
            summary = first_row(results_dir / f"alpaca_{symbol.lower()}_{suffix}_summary.csv")
            daily = read_csv(results_dir / f"alpaca_{symbol.lower()}_real_quote_daily_results.csv")
            if portfolio_mode == "mm-only":
                daily = read_csv(results_dir / f"alpaca_{symbol.lower()}_real_quote_mm_only_daily_results.csv")
                if not daily:
                    daily = read_csv(
                        Path("build/real_quote_symbol_suite")
                        / symbol.lower()
                        / "real_quote_backtest_mm_only"
                        / "daily_results.csv"
                    )
            pnls = daily_pnls(daily)
            ci_low, ci_high = bootstrap_mean_ci(pnls, args.bootstrap_samples, rng)
            loss_rate = (sum(1 for value in pnls if value < 0.0) / len(pnls)) if pnls else 0.0
            summary = summary or {}
            rows.append(
                {
                    "symbol": symbol,
                    "portfolio_mode": portfolio_mode,
                    "ok_sessions": ok_sessions,
                    "manifest_rows": manifest_rows,
                    "backtest_sessions": summary.get("sessions", len(pnls) if pnls else ""),
                    "total_pnl_bps": summary.get("total_pnl_bps", ""),
                    "avg_daily_pnl_bps": f"{(sum(pnls) / len(pnls)):.6f}" if pnls else "",
                    "avg_daily_pnl_ci95_low_bps": f"{ci_low:.6f}",
                    "avg_daily_pnl_ci95_high_bps": f"{ci_high:.6f}",
                    "minute_sharpe": summary.get("minute_sharpe", ""),
                    "worst_drawdown_bps": summary.get("worst_drawdown_bps", ""),
                    "trade_count": summary.get("trade_count", ""),
                    "loss_day_rate": f"{loss_rate:.6f}",
                    "sample_warning": "low_sample" if len(pnls) < 20 else "",
                }
            )
    return rows


def markdown_table(rows: list[dict[str, object]], columns: list[str]) -> list[str]:
    output = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return output


def latency_summary(results_dir: Path, symbol: str) -> list[dict[str, str]]:
    rows = read_csv(results_dir / f"alpaca_{symbol.lower()}_real_quote_latency_sensitivity.csv")
    return [
        {
            "symbol": symbol,
            "mode": row.get("portfolio_mode", ""),
            "latency_us": row.get("signal_latency_us", ""),
            "pnl_bps": row.get("total_pnl_bps", ""),
            "minute_sharpe": row.get("minute_sharpe", ""),
            "expired": row.get("latency_expired_signals", ""),
        }
        for row in rows
    ]


def stress_summary(results_dir: Path, symbol: str) -> list[dict[str, str]]:
    rows = read_csv(results_dir / f"alpaca_{symbol.lower()}_real_quote_stress_distribution_summary.csv")
    return [
        {
            "symbol": symbol,
            "mode": row.get("portfolio_mode", ""),
            "adverse_bps": row.get("adverse_selection_bps", ""),
            "runs": row.get("runs", ""),
            "mean_pnl_bps": row.get("mean_total_pnl_bps", ""),
            "p05_pnl_bps": row.get("p05_total_pnl_bps", ""),
            "mean_minute_sharpe": row.get("mean_minute_sharpe", ""),
            "positive_run_rate": row.get("positive_pnl_run_rate", ""),
        }
        for row in rows
    ]


def write_report(args: argparse.Namespace, rows: list[dict[str, object]]) -> None:
    results_dir = Path(args.results_dir)
    symbols = split_csv(args.symbols)
    lines: list[str] = [
        "# Real-Quote HFT Robustness Report",
        "",
        "This report is generated from local Alpaca IEX top-of-book quote replays.",
        "Minute Sharpe is computed on one-minute simulator interval returns and is not an annualized daily Sharpe.",
        "",
        "## Baseline Evidence",
        "",
    ]
    lines.extend(
        markdown_table(
            rows,
            [
                "symbol",
                "portfolio_mode",
                "ok_sessions",
                "backtest_sessions",
                "total_pnl_bps",
                "avg_daily_pnl_bps",
                "avg_daily_pnl_ci95_low_bps",
                "avg_daily_pnl_ci95_high_bps",
                "minute_sharpe",
                "sample_warning",
            ],
        )
    )
    lines.extend(["", "## Latency Decay", ""])
    latency_rows: list[dict[str, str]] = []
    stress_rows: list[dict[str, str]] = []
    for symbol in symbols:
        latency_rows.extend(latency_summary(results_dir, symbol))
        stress_rows.extend(stress_summary(results_dir, symbol))
    if latency_rows:
        lines.extend(markdown_table(latency_rows, ["symbol", "mode", "latency_us", "pnl_bps", "minute_sharpe", "expired"]))
    else:
        lines.append("No latency sensitivity file found for the requested symbols.")
    lines.extend(["", "## Adverse Selection Stress", ""])
    if stress_rows:
        lines.extend(
            markdown_table(
                stress_rows,
                [
                    "symbol",
                    "mode",
                    "adverse_bps",
                    "runs",
                    "mean_pnl_bps",
                    "p05_pnl_bps",
                    "mean_minute_sharpe",
                    "positive_run_rate",
                ],
            )
        )
    else:
        lines.append("No adverse-selection stress file found for the requested symbols.")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Quote data is top-of-book, not full depth-of-book.",
            "- The simulator does not model exchange queue position or venue-specific cancel/reject behavior.",
            "- Bootstrap intervals resample days and are descriptive, not a proof of future profitability.",
            "- Low sample warnings should be treated as evidence gaps, not strategy validation.",
        ]
    )
    latency_symbols = {row["symbol"] for row in latency_rows}
    stress_symbols = {row["symbol"] for row in stress_rows}
    missing_latency = [symbol for symbol in symbols if symbol not in latency_symbols]
    missing_stress = [symbol for symbol in symbols if symbol not in stress_symbols]
    if missing_latency:
        lines.append(f"- No latency grid found for: {', '.join(missing_latency)}.")
    if missing_stress:
        lines.append(f"- No adverse-selection stress grid found for: {', '.join(missing_stress)}.")
    output_path = Path(args.output_report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report={output_path}")


def main() -> int:
    args = parse_args()
    rows = evidence_rows(args)
    output_csv = Path(args.output_csv)
    write_csv(output_csv, rows)
    print(f"evidence_ci={output_csv}")
    write_report(args, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

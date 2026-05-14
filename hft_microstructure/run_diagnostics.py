"""Run deterministic HFT demo diagnostics.

This script is intentionally separate from the strategy code. It creates a
clearly labelled synthetic quote stream for engine reproducibility, runs the
compiled simulator, and writes diagnostic CSVs that are real outputs of the
simulator rather than templates.
"""

from __future__ import annotations

import csv
import math
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "Results"
DEMO_QUOTES = RESULTS_DIR / "demo_quotes_synthetic.csv"


BASE_ARGS = [
    "--rolling-window",
    "75",
    "--min-edge-bps",
    "0.20",
    "--forecast-weight",
    "0.70",
    "--min-reentry-events",
    "40",
    "--interval-seconds",
    "60",
    "--max-gross-exposure",
    "1.0",
    "--seed",
    "1337",
    "--forecast-mode",
    "heuristic",
    "--portfolio-mode",
    "full",
    "--decision-mode",
    "off",
]


def simulator_path() -> Path:
    candidates = [ROOT / "hft_portfolio.exe", ROOT / "hft_portfolio"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Compiled simulator not found. Compile first, for example: "
        "g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o hft_portfolio.exe main.cpp"
    )


def generate_demo_quotes(path: Path, event_count: int = 7200) -> None:
    """Create a deterministic synthetic quote stream that exercises fills/logging.

    The file is synthetic by design. It is only used to verify that the engine
    runs and writes diagnostics when full historical quote files are unavailable.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    start_ns = 1_776_259_800_000_000_000
    step_ns = 10_000_000
    mid = 500.0
    spread = 0.11

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_ns", "symbol", "bid_price", "ask_price", "bid_size", "ask_size"])
        for index in range(event_count):
            phase = (index // 240) % 6
            if phase in {0, 1, 4}:
                bid_size = 24.0 + (index % 7)
                ask_size = 5.0 + (index % 3)
                mid += 0.00020 + math.sin(index / 17.0) * 0.00005
            elif phase == 2:
                bid_size = 16.0 + (index % 5)
                ask_size = 8.0 + (index % 4)
                mid += math.sin(index / 11.0) * 0.00003
            else:
                bid_size = 12.0 + (index % 4)
                ask_size = 12.0 + (index % 4)
                mid += math.sin(index / 13.0) * 0.00002

            if index % 900 == 0 and index > 0:
                mid -= 0.04

            bid = mid - spread / 2.0
            ask = mid + spread / 2.0
            writer.writerow(
                [
                    start_ns + index * step_ns,
                    "SPY_DEMO_SYNTHETIC",
                    f"{bid:.6f}",
                    f"{ask:.6f}",
                    f"{bid_size:.6f}",
                    f"{ask_size:.6f}",
                ]
            )


def replace_arg(args: list[str], option: str, value: str) -> list[str]:
    updated = list(args)
    try:
        index = updated.index(option)
    except ValueError:
        updated.extend([option, value])
        return updated
    updated[index + 1] = value
    return updated


def run_simulation(extra_args: list[str] | None = None) -> dict[str, float | str]:
    command = [str(simulator_path()), str(DEMO_QUOTES), *BASE_ARGS]
    if extra_args:
        index = 0
        while index < len(extra_args):
            option = extra_args[index]
            if option.startswith("--") and index + 1 < len(extra_args):
                command = [command[0], command[1], *replace_arg(command[2:], option, extra_args[index + 1])]
                index += 2
            else:
                command.append(option)
                index += 1

    completed = subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=True)
    metrics: dict[str, float | str] = {"stdout": completed.stdout.strip()}
    for line in completed.stdout.splitlines():
        if "=" not in line or line.startswith("sleeve="):
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        try:
            metrics[key.strip()] = float(value)
        except ValueError:
            metrics[key.strip()] = value
    return metrics


def write_ablation_results() -> list[dict[str, str | float]]:
    variants = [
        ("full_portfolio_default", [], "Default full portfolio on synthetic demo quotes."),
        ("market_making_only", ["--portfolio-mode", "mm-only"], "Runs only the market-making sleeve."),
        ("liquidity_detection_only", ["--portfolio-mode", "liquidity-only"], "Runs only the liquidity-detection sleeve when its own signal fires."),
        ("momentum_ignition_only", ["--portfolio-mode", "momentum-only"], "Runs only the momentum-ignition sleeve when its own signal fires."),
        ("defensive_decision_engine", ["--decision-mode", "full"], "Applies HMM, Hawkes-style intensity, and volatility controls."),
        ("portfolio_low_edge_gate_disabled", ["--min-edge-bps", "0.00"], "Disables the portfolio-level low-edge gate; strategy-internal edge filters remain active."),
        ("gross_exposure_cap_relaxed", ["--max-gross-exposure", "3.0"], "Relaxes the gross exposure cap for diagnostics; default remains 1.0."),
    ]
    rows: list[dict[str, str | float]] = []
    for name, args, notes in variants:
        metrics = run_simulation(args)
        trade_count = float(metrics.get("completed_trades", 0.0))
        total_pnl = float(metrics.get("total_net_return_bps", 0.0))
        rows.append(
            {
                "variant": name,
                "source_data": "synthetic_demo_quotes",
                "total_pnl_bps": total_pnl,
                "trade_count": trade_count,
                "max_drawdown_bps": float(metrics.get("max_drawdown_bps", 0.0)),
                "average_pnl_per_trade_bps": total_pnl / trade_count if trade_count else 0.0,
                "win_rate": float(metrics.get("trade_win_rate", 0.0)),
                "minute_sharpe": float(metrics.get("minute_return_sharpe", 0.0)),
                "notes": notes,
            }
        )

    output = RESULTS_DIR / "ablation_results.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def write_latency_sensitivity() -> list[dict[str, str | float]]:
    stresses = [
        ("base_fill_assumption", 0.00),
        ("plus_0_25_bps_adverse_selection", 0.25),
        ("plus_0_50_bps_adverse_selection", 0.50),
        ("plus_1_00_bps_adverse_selection", 1.00),
        ("plus_2_00_bps_adverse_selection", 2.00),
    ]
    rows: list[dict[str, str | float]] = []
    baseline_pnl = None
    for scenario, adverse_selection_bps in stresses:
        metrics = run_simulation(["--adverse-selection-bps", f"{adverse_selection_bps:.2f}"])
        trade_count = float(metrics.get("completed_trades", 0.0))
        total_pnl = float(metrics.get("total_net_return_bps", 0.0))
        if baseline_pnl is None:
            baseline_pnl = total_pnl
        degradation = (
            ((baseline_pnl - total_pnl) / abs(baseline_pnl)) * 100.0
            if baseline_pnl and abs(baseline_pnl) > 1e-12
            else 0.0
        )
        rows.append(
            {
                "scenario": scenario,
                "stress_type": "proxy_adverse_selection_bps",
                "source_data": "synthetic_demo_quotes",
                "adverse_selection_bps": adverse_selection_bps,
                "total_pnl_bps": total_pnl,
                "trade_count": trade_count,
                "max_drawdown_bps": float(metrics.get("max_drawdown_bps", 0.0)),
                "average_pnl_per_trade_bps": total_pnl / trade_count if trade_count else 0.0,
                "win_rate": float(metrics.get("trade_win_rate", 0.0)),
                "minute_sharpe": float(metrics.get("minute_return_sharpe", 0.0)),
                "percent_degradation_vs_baseline": degradation,
                "notes": "Proxy stress subtracts adverse-selection bps from each completed trade; this is not true latency modelling.",
            }
        )

    output = RESULTS_DIR / "latency_sensitivity.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def write_demo_logs() -> dict[str, float | str]:
    return run_simulation(
        [
            "--trade-log-path",
            str(RESULTS_DIR / "trade_log.csv"),
            "--rejected-signals-path",
            str(RESULTS_DIR / "rejected_signals.csv"),
        ]
    )


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def main() -> None:
    generate_demo_quotes(DEMO_QUOTES)
    demo_metrics = write_demo_logs()
    ablations = write_ablation_results()
    stresses = write_latency_sensitivity()
    print(f"demo_quotes={DEMO_QUOTES}")
    print(f"demo_completed_trades={demo_metrics.get('completed_trades', 0)}")
    print(f"trade_log_rows={count_csv_rows(RESULTS_DIR / 'trade_log.csv')}")
    print(f"rejected_signal_rows={count_csv_rows(RESULTS_DIR / 'rejected_signals.csv')}")
    print(f"ablation_variants={len(ablations)}")
    print(f"latency_scenarios={len(stresses)}")


if __name__ == "__main__":
    main()

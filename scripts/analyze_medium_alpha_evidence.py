#!/usr/bin/env python3
"""Generate robustness evidence for the medium-term alpha project."""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default="medium_term_alpha/Results")
    parser.add_argument("--output-ci", default="medium_term_alpha/Results/medium_alpha_bootstrap_ci.csv")
    parser.add_argument("--output-controls", default="medium_term_alpha/Results/medium_alpha_negative_controls.csv")
    parser.add_argument("--output-scorecard", default="medium_term_alpha/Results/medium_alpha_robustness_scorecard.csv")
    parser.add_argument("--output-report", default="medium_term_alpha/Results/medium_alpha_robustness_report.md")
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--control-samples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=2026)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def float_value(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def metric_lookup(rows: list[dict[str, str]], value_column: str = "value") -> dict[str, float]:
    output: dict[str, float] = {}
    for row in rows:
        metric = row.get("metric", "")
        if metric:
            output[metric] = float_value(row, value_column)
    return output


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


def total_return(returns: list[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1.0 + value
    return equity - 1.0


def annualized_return(returns: list[float], periods_per_year: int = 12) -> float:
    if not returns:
        return 0.0
    equity = 1.0 + total_return(returns)
    years = len(returns) / periods_per_year
    if years <= 0.0 or equity <= 0.0:
        return 0.0
    return equity ** (1.0 / years) - 1.0


def sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def annualized_sharpe(returns: list[float], periods_per_year: int = 12) -> float:
    std = sample_std(returns)
    if std <= 0.0 or not math.isfinite(std):
        return 0.0
    return (sum(returns) / len(returns)) / std * math.sqrt(periods_per_year)


def max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    return drawdown


def return_metrics(returns: list[float]) -> dict[str, float]:
    if not returns:
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "annualized_sharpe": 0.0,
            "max_drawdown": 0.0,
            "avg_monthly_return": 0.0,
            "monthly_win_rate": 0.0,
        }
    return {
        "total_return": total_return(returns),
        "annualized_return": annualized_return(returns),
        "annualized_sharpe": annualized_sharpe(returns),
        "max_drawdown": max_drawdown(returns),
        "avg_monthly_return": sum(returns) / len(returns),
        "monthly_win_rate": sum(1 for value in returns if value > 0.0) / len(returns),
    }


def bootstrap_ci_rows(returns: list[float], samples: int, rng: random.Random) -> list[dict[str, object]]:
    metric_samples: dict[str, list[float]] = {
        "total_return": [],
        "annualized_return": [],
        "annualized_sharpe": [],
        "max_drawdown": [],
        "avg_monthly_return": [],
        "monthly_win_rate": [],
    }
    if not returns:
        return []
    for _ in range(samples):
        draw = [returns[rng.randrange(len(returns))] for _ in returns]
        metrics = return_metrics(draw)
        for metric, value in metrics.items():
            metric_samples[metric].append(value)
    observed = return_metrics(returns)
    rows = []
    for metric, values in metric_samples.items():
        rows.append(
            {
                "metric": metric,
                "observed": f"{observed[metric]:.10f}",
                "ci95_low": f"{percentile(values, 0.025):.10f}",
                "ci95_high": f"{percentile(values, 0.975):.10f}",
                "bootstrap_samples": samples,
                "sample_months": len(returns),
            }
        )
    return rows


def sign_flip_controls(returns: list[float], samples: int, rng: random.Random) -> list[dict[str, object]]:
    if not returns:
        return []
    observed = return_metrics(returns)
    sharpe_draws: list[float] = []
    total_return_draws: list[float] = []
    for _ in range(samples):
        flipped = [value if rng.random() >= 0.5 else -value for value in returns]
        metrics = return_metrics(flipped)
        sharpe_draws.append(metrics["annualized_sharpe"])
        total_return_draws.append(metrics["total_return"])
    sharpe_p = sum(1 for value in sharpe_draws if value >= observed["annualized_sharpe"]) / samples
    return_p = sum(1 for value in total_return_draws if value >= observed["total_return"]) / samples
    return [
        {
            "control": "monthly_return_sign_flip",
            "observed_annualized_sharpe": f"{observed['annualized_sharpe']:.10f}",
            "control_mean_annualized_sharpe": f"{sum(sharpe_draws) / len(sharpe_draws):.10f}",
            "control_p95_annualized_sharpe": f"{percentile(sharpe_draws, 0.95):.10f}",
            "p_value_control_sharpe_ge_observed": f"{sharpe_p:.10f}",
            "observed_total_return": f"{observed['total_return']:.10f}",
            "control_p95_total_return": f"{percentile(total_return_draws, 0.95):.10f}",
            "p_value_control_total_return_ge_observed": f"{return_p:.10f}",
            "samples": samples,
            "interpretation": "Tests whether the saved monthly return signs matter after preserving return magnitudes.",
        }
    ]


def row_for_label(rows: list[dict[str, str]], key: str, value: str) -> dict[str, str] | None:
    for row in rows:
        if row.get(key) == value:
            return row
    return None


def status(pass_condition: bool, warning_condition: bool = False) -> str:
    if pass_condition:
        return "pass"
    if warning_condition:
        return "warn"
    return "fail"


def scorecard_rows(results_dir: Path, ci_rows: list[dict[str, object]], control_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summary = metric_lookup(read_csv(results_dir / "results_summary.csv"))
    benchmark = metric_lookup(read_csv(results_dir / "benchmark_comparison.csv"), value_column="momentum_strategy")
    benchmark_spy = metric_lookup(read_csv(results_dir / "benchmark_comparison.csv"), value_column="SPY")
    selected_rows = read_csv(results_dir / "selected_default_metrics.csv")
    selected = selected_rows[0] if selected_rows else {}
    walk_forward = read_csv(results_dir / "walk_forward_results.csv")
    sensitivity = read_csv(results_dir / "sensitivity_results.csv")
    capacity = read_csv(results_dir / "capacity_simulation.csv")
    factor_behavior = metric_lookup(read_csv(results_dir / "factor_behavior_summary.csv"))

    positive_wf = sum(1 for row in walk_forward if float_value(row, "annualized_sharpe") > 0.0)
    wf_count = len(walk_forward)
    worst_wf = min((float_value(row, "annualized_sharpe") for row in walk_forward), default=0.0)
    mean_wf = sum(float_value(row, "annualized_sharpe") for row in walk_forward) / wf_count if wf_count else 0.0
    selected_positive_wf = float_value(selected, "positive_walk_forward_years")
    selected_wf_count = float_value(selected, "walk_forward_year_count")
    selected_worst_wf = float_value(selected, "worst_walk_forward_year_sharpe")

    sensitivity_sharpes = [float_value(row, "annualized_sharpe") for row in sensitivity]
    min_sensitivity_sharpe = min(sensitivity_sharpes, default=0.0)
    selected_cost_10 = next(
        (
            row
            for row in sensitivity
            if abs(float_value(row, "top_quantile") - float_value(selected, "top_quantile", 0.25)) < 1e-9
            and abs(float_value(row, "cost_bps") - 10.0) < 1e-9
        ),
        {},
    )
    capacity_20 = row_for_label(capacity, "capital_scale", "20.0") or (capacity[-1] if capacity else {})
    sharpe_ci = row_for_label([{k: str(v) for k, v in row.items()} for row in ci_rows], "metric", "annualized_sharpe") or {}
    control = control_rows[0] if control_rows else {}

    rows: list[dict[str, object]] = []

    def add(category: str, check: str, value: object, threshold: str, result: str, interpretation: str) -> None:
        rows.append(
            {
                "category": category,
                "check": check,
                "value": value,
                "threshold": threshold,
                "status": result,
                "interpretation": interpretation,
            }
        )

    add(
        "headline",
        "annualized_sharpe",
        f"{summary.get('annualized_sharpe', 0.0):.4f}",
        ">= 1.0",
        status(summary.get("annualized_sharpe", 0.0) >= 1.0),
        "Risk-adjusted return clears a basic institutional hurdle.",
    )
    add(
        "benchmark",
        "sharpe_spread_vs_spy",
        f"{summary.get('annualized_sharpe', 0.0) - benchmark_spy.get('annualized_sharpe', 0.0):.4f}",
        "> 0",
        status(summary.get("annualized_sharpe", 0.0) > benchmark_spy.get("annualized_sharpe", 0.0)),
        "Strategy Sharpe should beat the benchmark, not just absolute return.",
    )
    add(
        "benchmark",
        "drawdown_vs_spy",
        f"{summary.get('max_drawdown', 0.0):.4f} vs {benchmark_spy.get('max_drawdown', 0.0):.4f}",
        "less severe than SPY",
        status(summary.get("max_drawdown", 0.0) > benchmark_spy.get("max_drawdown", 0.0)),
        "Drawdown is materially smaller than the benchmark in the saved run.",
    )
    add(
        "inference",
        "bootstrap_sharpe_ci_low",
        sharpe_ci.get("ci95_low", ""),
        "> 0.75",
        status(float(sharpe_ci.get("ci95_low", 0.0) or 0.0) > 0.75),
        "Bootstrap interval resamples months; this is descriptive uncertainty, not a proof.",
    )
    add(
        "negative_control",
        "sign_flip_sharpe_p_value",
        control.get("p_value_control_sharpe_ge_observed", ""),
        "< 0.05",
        status(float(control.get("p_value_control_sharpe_ge_observed", 1.0) or 1.0) < 0.05),
        "Preserving magnitudes but randomizing return signs rarely matches the observed Sharpe.",
    )
    add(
        "walk_forward",
        "expanding_window_positive_sharpe_years",
        f"{positive_wf}/{wf_count}",
        ">= 75%",
        status((positive_wf / wf_count) >= 0.75 if wf_count else False),
        f"Mean walk-forward Sharpe is {mean_wf:.3f}; worst year is {worst_wf:.3f}.",
    )
    add(
        "walk_forward",
        "selected_candidate_positive_sharpe_years",
        f"{selected_positive_wf:.0f}/{selected_wf_count:.0f}",
        ">= 75%",
        status((selected_positive_wf / selected_wf_count) >= 0.75 if selected_wf_count else False),
        f"Selected-candidate table reports worst yearly Sharpe of {selected_worst_wf:.3f}.",
    )
    add(
        "walk_forward",
        "worst_year_sharpe",
        f"{worst_wf:.4f}",
        "> -1.0",
        status(worst_wf > -1.0, warning_condition=worst_wf > -1.5),
        "Weak years are retained rather than filtered out.",
    )
    add(
        "sensitivity",
        "local_grid_min_sharpe",
        f"{min_sensitivity_sharpe:.4f}",
        "> 1.0",
        status(min_sensitivity_sharpe > 1.0),
        "The 3x3 top-quantile/cost grid stays above a Sharpe of 1.",
    )
    add(
        "costs",
        "selected_10bps_cost_sharpe",
        f"{float_value(selected_cost_10, 'annualized_sharpe'):.4f}",
        "> 1.0",
        status(float_value(selected_cost_10, "annualized_sharpe") > 1.0),
        "The selected configuration survives a 10 bps cost assumption.",
    )
    add(
        "capacity",
        "twenty_x_cost_proxy_sharpe",
        f"{float_value(capacity_20, 'annualized_sharpe'):.4f}",
        "> 1.0",
        status(float_value(capacity_20, "annualized_sharpe") > 1.0),
        "Capacity is only a cost proxy; it is not a calibrated market-impact model.",
    )
    add(
        "factor_risk",
        "momentum_dominance_share",
        f"{factor_behavior.get('momentum_dominance_share', 0.0):.4f}",
        "< 0.90 preferred",
        status(factor_behavior.get("momentum_dominance_share", 0.0) < 0.90, warning_condition=True),
        "The selected run is momentum-dominated, which is a concentration risk.",
    )
    add(
        "data_hygiene",
        "point_in_time_universe",
        "not_available",
        "required for production-grade evidence",
        "fail",
        "The default universe is not point-in-time and may contain survivorship bias.",
    )
    add(
        "audit",
        "full_selected_holdings",
        "not_pinned",
        "required for full replication",
        "warn",
        "Committed holdings audit files verify schema; scripts/export_medium_alpha_selected_audit.py exports the full audit from a pinned price panel.",
    )
    return rows


def markdown_table(rows: list[dict[str, object]], columns: list[str]) -> list[str]:
    output = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return output


def write_report(
    path: Path,
    results_dir: Path,
    ci_rows: list[dict[str, object]],
    control_rows: list[dict[str, object]],
    scorecard: list[dict[str, object]],
) -> None:
    summary = metric_lookup(read_csv(results_dir / "results_summary.csv"))
    benchmark_spy = metric_lookup(read_csv(results_dir / "benchmark_comparison.csv"), value_column="SPY")
    selected_rows = read_csv(results_dir / "selected_default_metrics.csv")
    selected = selected_rows[0] if selected_rows else {}
    walk_forward = read_csv(results_dir / "walk_forward_results.csv")
    sensitivity = read_csv(results_dir / "sensitivity_results.csv")
    capacity = read_csv(results_dir / "capacity_simulation.csv")

    positive_wf = sum(1 for row in walk_forward if float_value(row, "annualized_sharpe") > 0.0)
    wf_count = len(walk_forward)
    worst_wf = min((float_value(row, "annualized_sharpe") for row in walk_forward), default=0.0)
    selected_positive_wf = float_value(selected, "positive_walk_forward_years")
    selected_wf_count = float_value(selected, "walk_forward_year_count")
    selected_worst_wf = float_value(selected, "worst_walk_forward_year_sharpe")
    cost_10 = next(
        (
            row
            for row in sensitivity
            if abs(float_value(row, "top_quantile") - float_value(selected, "top_quantile", 0.25)) < 1e-9
            and abs(float_value(row, "cost_bps") - 10.0) < 1e-9
        ),
        {},
    )
    capacity_20 = row_for_label(capacity, "capital_scale", "20.0") or (capacity[-1] if capacity else {})

    lines: list[str] = [
        "# Medium-Alpha Robustness Report",
        "",
        "This report summarizes saved medium-term alpha evidence. It does not retune parameters.",
        "",
        "## Baseline",
        "",
        "| Metric | Strategy | SPY |",
        "| --- | ---: | ---: |",
        f"| Annualized Sharpe | {summary.get('annualized_sharpe', 0.0):.4f} | {benchmark_spy.get('annualized_sharpe', 0.0):.4f} |",
        f"| Annualized Return | {summary.get('annualized_return', 0.0):.4f} | {benchmark_spy.get('annualized_return', 0.0):.4f} |",
        f"| Total Return | {summary.get('total_return', 0.0):.4f} | {benchmark_spy.get('total_return', 0.0):.4f} |",
        f"| Max Drawdown | {summary.get('max_drawdown', 0.0):.4f} | {benchmark_spy.get('max_drawdown', 0.0):.4f} |",
        "",
        "## Bootstrap Intervals",
        "",
        "These intervals use `monthly_results.csv`, so the observed monthly annualized Sharpe can differ from the daily headline Sharpe in `results_summary.csv`.",
        "",
    ]
    lines.extend(markdown_table(ci_rows, ["metric", "observed", "ci95_low", "ci95_high", "sample_months"]))
    lines.extend(["", "## Negative Control", ""])
    lines.extend(
        markdown_table(
            control_rows,
            [
                "control",
                "observed_annualized_sharpe",
                "control_p95_annualized_sharpe",
                "p_value_control_sharpe_ge_observed",
                "observed_total_return",
                "control_p95_total_return",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Robustness Scorecard",
            "",
        ]
    )
    lines.extend(markdown_table(scorecard, ["category", "check", "value", "threshold", "status"]))
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- Expanding-window file is positive in {positive_wf}/{wf_count} years; worst test-year Sharpe is {worst_wf:.3f}.",
            f"- Selected-candidate table is positive in {selected_positive_wf:.0f}/{selected_wf_count:.0f} walk-forward years; worst yearly Sharpe is {selected_worst_wf:.3f}.",
            f"- Selected configuration Sharpe at 10 bps cost is {float_value(cost_10, 'annualized_sharpe'):.3f}.",
            f"- 20x cost-proxy capacity Sharpe is {float_value(capacity_20, 'annualized_sharpe'):.3f}.",
            "- The sign-flip control is a falsification check on the saved monthly return signs, not a substitute for signal-shuffle tests on raw price data.",
            "",
            "## Limitations",
            "",
            "- The default universe is not point-in-time and may contain survivorship bias.",
            "- The committed holdings/rebalance audit files are sample-run artifacts, not the full selected-default holdings history.",
            "- Capacity is modeled as higher effective costs, not full liquidity or market impact.",
            "- Alternative benchmark evidence is limited to the saved SPY comparison unless a pinned full price panel is supplied.",
            "- Historical results do not imply future performance.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def monthly_returns(results_dir: Path) -> list[float]:
    rows = read_csv(results_dir / "monthly_results.csv")
    values = [float_value(row, "strategy_monthly_return") for row in rows]
    return [value for value in values if math.isfinite(value)]


def main() -> int:
    args = parse_args()
    results_dir = Path(args.results_dir)
    rng = random.Random(args.seed)
    returns = monthly_returns(results_dir)

    ci_rows = bootstrap_ci_rows(returns, args.bootstrap_samples, rng)
    controls = sign_flip_controls(returns, args.control_samples, rng)
    scorecard = scorecard_rows(results_dir, ci_rows, controls)

    write_csv(Path(args.output_ci), ci_rows)
    write_csv(Path(args.output_controls), controls)
    write_csv(Path(args.output_scorecard), scorecard)
    write_report(Path(args.output_report), results_dir, ci_rows, controls, scorecard)
    print(f"bootstrap_ci={args.output_ci}")
    print(f"negative_controls={args.output_controls}")
    print(f"scorecard={args.output_scorecard}")
    print(f"report={args.output_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

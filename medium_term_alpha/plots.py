"""Plot helpers for the flat medium-term alpha project."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

def save_equity_plot(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
    benchmark_name: str,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    strategy_equity.plot(ax=ax, linewidth=1.8, label="Momentum strategy")
    benchmark_equity.plot(ax=ax, linewidth=1.4, label=f"{benchmark_name} buy-and-hold")
    ax.set_title("Cross-Sectional Momentum vs Benchmark")
    ax.set_ylabel("Growth of $1")
    ax.set_xlabel("Date")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_drawdown_plot(
    strategy_drawdown: pd.Series,
    benchmark_drawdown: pd.Series,
    benchmark_name: str,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    strategy_drawdown.plot(ax=ax, linewidth=1.7, label="Momentum strategy")
    benchmark_drawdown.plot(ax=ax, linewidth=1.3, label=f"{benchmark_name} buy-and-hold")
    ax.set_title("Drawdown Comparison")
    ax.set_ylabel("Drawdown")
    ax.set_xlabel("Date")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_metrics_bar_chart(
    strategy_summary: dict[str, float],
    benchmark_summary: dict[str, float],
    benchmark_name: str,
    output_path: Path,
) -> None:
    metrics = {
        "Sharpe": (strategy_summary["annualized_sharpe"], benchmark_summary["annualized_sharpe"]),
        "Return": (strategy_summary["annualized_return"], benchmark_summary["annualized_return"]),
        "Drawdown": (abs(strategy_summary["max_drawdown"]), abs(benchmark_summary["max_drawdown"])),
    }
    labels = list(metrics.keys())
    strategy_values = [values[0] for values in metrics.values()]
    benchmark_values = [values[1] for values in metrics.values()]

    x = range(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar([i - width / 2 for i in x], strategy_values, width=width, label="Momentum strategy")
    ax.bar([i + width / 2 for i in x], benchmark_values, width=width, label=f"{benchmark_name} benchmark")
    ax.set_title("Strategy vs Benchmark Metrics")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Metric value")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_rolling_sharpe_plot(rolling_metrics: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    rolling_metrics["rolling_sharpe_6m"].plot(ax=ax, label="6m rolling Sharpe", linewidth=1.5)
    rolling_metrics["rolling_sharpe_12m"].plot(ax=ax, label="12m rolling Sharpe", linewidth=1.5)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("Rolling Sharpe")
    ax.set_ylabel("Annualized Sharpe")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_long_short_plot(long_returns: pd.Series, short_returns: pd.Series, output_path: Path) -> None:
    long_equity = equity_curve(long_returns).rename("long_book")
    short_equity = equity_curve(short_returns).rename("short_book")
    fig, ax = plt.subplots(figsize=(10, 5))
    long_equity.plot(ax=ax, label="Long book", linewidth=1.5)
    short_equity.plot(ax=ax, label="Short book", linewidth=1.5)
    ax.set_title("Long vs Short Book PnL")
    ax.set_ylabel("Growth of $1")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_turnover_plot(turnover: pd.Series, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    turnover.plot(ax=ax, linewidth=1.2)
    ax.set_title("Turnover Over Time")
    ax.set_ylabel("Daily turnover")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_factor_contribution_plot(factor_contribution: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    factor_contribution.set_index("factor")["total_return"].plot(kind="bar", ax=ax)
    ax.set_title("Factor Contribution Proxy")
    ax.set_ylabel("Standalone total return")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_failure_regime_plot(failure_regime: pd.DataFrame, output_path: Path) -> None:
    if failure_regime.empty:
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    failure_regime.set_index("regime")["total_return"].plot(kind="bar", ax=ax)
    ax.set_title("Failure Regime Analysis")
    ax.set_ylabel("Strategy total return")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_factor_dominance_plot(factor_dominance: pd.DataFrame, output_path: Path) -> None:
    if factor_dominance.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    factor_dominance["momentum_rolling_return"].plot(ax=ax, label="Momentum-only rolling return", linewidth=1.4)
    factor_dominance["low_vol_rolling_return"].plot(ax=ax, label="Low-vol-only rolling return", linewidth=1.4)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("Factor Dominance Over Time")
    ax.set_ylabel("126-day rolling return")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_factor_performance_plot(factor_performance: pd.DataFrame, output_path: Path) -> None:
    if factor_performance.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    factor_performance["momentum_equity"].plot(ax=ax, label="Momentum-only", linewidth=1.4)
    factor_performance["low_volatility_equity"].plot(ax=ax, label="Low-vol-only", linewidth=1.4)
    factor_performance["composite_equity"].plot(ax=ax, label="Composite", linewidth=1.6)
    ax.set_title("Factor Performance Comparison")
    ax.set_ylabel("Growth of $1")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_rolling_factor_correlation_plot(rolling_correlation: pd.DataFrame, output_path: Path) -> None:
    if rolling_correlation.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    rolling_correlation["cross_sectional_correlation"].plot(
        ax=ax,
        label="Daily cross-sectional correlation",
        linewidth=1.0,
        alpha=0.45,
    )
    rolling_correlation["rolling_factor_correlation"].plot(
        ax=ax,
        label="126-day rolling correlation",
        linewidth=1.6,
    )
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("Momentum vs Low-Vol Signal Correlation")
    ax.set_ylabel("Correlation")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_capacity_simulation_plot(capacity: pd.DataFrame, output_path: Path) -> None:
    if capacity.empty:
        return
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    capacity.plot(x="capital_scale", y="annualized_sharpe", marker="o", ax=axes[0], legend=False)
    axes[0].set_title("Capacity Simulation")
    axes[0].set_ylabel("Sharpe")
    axes[0].grid(True, alpha=0.25)
    capacity.plot(x="capital_scale", y="total_return", marker="o", ax=axes[1], legend=False)
    axes[1].set_xlabel("Capital scale")
    axes[1].set_ylabel("Total return")
    axes[1].grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)



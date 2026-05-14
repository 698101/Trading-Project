"""Generate recruiter-facing plots from saved medium-term alpha result CSVs.

This script is reporting-only: it reads files in Results/ and writes charts to
Plots/. It does not run the strategy, change parameters, or recalculate the
backtest.
"""

from __future__ import annotations

from pathlib import Path
import sys

LOCAL_DEPS = Path(__file__).resolve().parents[1] / ".pip_tmp"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib import dates as mdates
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import PercentFormatter


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "Results"
PLOTS_DIR = ROOT / "Plots"

COLORS = {
    "navy": "#102A43",
    "blue": "#1D4ED8",
    "green": "#1F7A4D",
    "red": "#B4233A",
    "orange": "#B7791F",
    "gray": "#475569",
    "muted": "#64748B",
    "light": "#F5F7FA",
    "grid": "#CBD5E1",
}

plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "font.family": "DejaVu Sans",
        "axes.titleweight": "bold",
        "axes.labelsize": 13,
        "axes.titlesize": 18,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "legend.fontsize": 11,
    }
)


def save_figure(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def set_research_style(ax: plt.Axes, title: str, ylabel: str | None = None) -> None:
    ax.set_title(title, loc="left", fontsize=18, fontweight="bold", color=COLORS["navy"], pad=14)
    if ylabel:
        ax.set_ylabel(ylabel, color=COLORS["navy"], labelpad=10)
    ax.grid(True, axis="y", color=COLORS["grid"], linewidth=1.0, alpha=0.85)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(colors="#334155", labelsize=11)


def format_date_axis(ax: plt.Axes) -> None:
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(axis="x", rotation=0)


def add_metric_box(ax: plt.Axes, text: str, x: float = 0.03, y: float = 0.72) -> None:
    ax.text(
        x,
        y,
        text,
        transform=ax.transAxes,
        fontsize=12,
        linespacing=1.45,
        color=COLORS["navy"],
        bbox={"boxstyle": "round,pad=0.55", "facecolor": "white", "edgecolor": "#CBD5E1", "linewidth": 1.1},
    )


def draw_metric_panel(ax: plt.Axes, title: str, subtitle: str, rows: list[tuple[str, str]]) -> None:
    ax.set_axis_off()
    card = FancyBboxPatch(
        (0.02, 0.05),
        0.96,
        0.88,
        boxstyle="round,pad=0.02,rounding_size=0.025",
        linewidth=1.1,
        edgecolor="#CBD5E1",
        facecolor="#F8FAFC",
        transform=ax.transAxes,
    )
    ax.add_patch(card)
    ax.text(0.08, 0.86, title, transform=ax.transAxes, fontsize=22, fontweight="bold", color=COLORS["navy"])
    ax.text(0.08, 0.80, subtitle, transform=ax.transAxes, fontsize=11, color=COLORS["muted"])
    y = 0.68
    for label, value in rows:
        ax.text(0.10, y, label, transform=ax.transAxes, fontsize=13, color=COLORS["gray"])
        ax.text(0.88, y, value, transform=ax.transAxes, fontsize=15, fontweight="bold", color=COLORS["navy"], ha="right")
        ax.plot([0.10, 0.88], [y - 0.045, y - 0.045], transform=ax.transAxes, color="#E2E8F0", linewidth=1)
        y -= 0.11


def read_metric_csv(path: Path, metric_column: str = "metric", value_column: str = "value") -> dict[str, float]:
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    if metric_column not in frame or value_column not in frame:
        return {}
    return {
        str(row[metric_column]): float(row[value_column])
        for _, row in frame.iterrows()
        if pd.notna(row[value_column])
    }


def read_comparison_metrics(path: Path) -> tuple[dict[str, float], dict[str, float]]:
    if not path.exists():
        return {}, {}
    frame = pd.read_csv(path)
    if not {"metric", "momentum_strategy", "SPY"}.issubset(frame.columns):
        return {}, {}
    strategy = dict(zip(frame["metric"], frame["momentum_strategy"].astype(float)))
    benchmark = dict(zip(frame["metric"], frame["SPY"].astype(float)))
    return strategy, benchmark


def load_monthly_returns(path: Path) -> pd.Series:
    if not path.exists():
        raise FileNotFoundError(f"Missing monthly return file: {path}")
    frame = pd.read_csv(path, parse_dates=["date"])
    if "strategy_monthly_return" not in frame:
        raise ValueError("monthly_results.csv must contain strategy_monthly_return")
    series = frame.set_index("date")["strategy_monthly_return"].astype(float).sort_index()
    return series.dropna()


def load_daily_strategy_returns(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    frame = pd.read_csv(path, parse_dates=["date"])
    if "net_strategy_return" not in frame:
        return None
    frame = frame.set_index("date").sort_index()
    for column in ["gross_strategy_return", "net_strategy_return", "benchmark_return", "turnover", "trading_cost", "cumulative_net_return"]:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def load_benchmark_timeseries(path: Path) -> pd.Series | None:
    if not path.exists():
        return None
    frame = pd.read_csv(path, parse_dates=["date"])
    if "benchmark_return" not in frame:
        return None
    return frame.set_index("date")["benchmark_return"].astype(float).sort_index().dropna()


def daily_frame_matches_metrics(frame: pd.DataFrame, metrics: dict[str, float], tolerance: float = 0.02) -> bool:
    if frame is None or frame.empty or "net_strategy_return" not in frame:
        return False
    expected_total = metrics.get("total_return")
    if expected_total is None or pd.isna(expected_total):
        return True
    realized_total = float((1.0 + frame["net_strategy_return"].fillna(0.0)).prod() - 1.0)
    return abs(realized_total - float(expected_total)) <= tolerance


def infer_periods_per_year(index: pd.DatetimeIndex) -> int:
    if len(index) < 3:
        return 12
    median_days = pd.Series(index).diff().dt.days.dropna().median()
    return 252 if median_days <= 10 else 12


def cumulative_growth(returns: pd.Series) -> pd.Series:
    return (1.0 + returns).cumprod()


def drawdown_from_growth(growth: pd.Series) -> pd.Series:
    return growth / growth.cummax() - 1.0


def rolling_sharpe(returns: pd.Series, window: int, periods_per_year: int) -> pd.Series:
    rolling_mean = returns.rolling(window).mean()
    rolling_std = returns.rolling(window).std(ddof=1)
    return (rolling_mean / rolling_std.replace(0.0, np.nan)) * np.sqrt(float(periods_per_year))


def pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.1%}"


def num(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.2f}"


def metrics_text(metrics: dict[str, float]) -> str:
    return "\n".join(
        [
            f"Ann. return: {pct(metrics.get('annualized_return'))}",
            f"Sharpe: {num(metrics.get('annualized_sharpe'))}",
            f"Max drawdown: {pct(metrics.get('max_drawdown'))}",
            f"Turnover: {num(metrics.get('average_turnover'))}",
        ]
    )


def plot_cumulative_returns(
    returns: pd.Series,
    metrics: dict[str, float],
    benchmark: dict[str, float],
    benchmark_returns: pd.Series | None = None,
) -> None:
    growth = cumulative_growth(returns)
    fig, ax = plt.subplots(figsize=(14, 7.2), constrained_layout=True)
    ax.plot(growth.index, growth, color=COLORS["green"], linewidth=3.0, label="Momentum strategy")
    if benchmark_returns is not None and not benchmark_returns.empty:
        benchmark_growth = cumulative_growth(benchmark_returns.reindex(growth.index).fillna(0.0))
        ax.plot(benchmark_growth.index, benchmark_growth, color=COLORS["blue"], linewidth=2.5, label="SPY benchmark")
    set_research_style(ax, "Medium-Term Alpha: Cumulative Growth of $1", "Growth of $1")
    format_date_axis(ax)
    ax.legend(frameon=False, loc="upper left")
    add_metric_box(ax, metrics_text(metrics))
    if benchmark and (benchmark_returns is None or benchmark_returns.empty):
        ax.text(
            0.03,
            0.53,
            f"SPY headline: return {pct(benchmark.get('total_return'))}, Sharpe {num(benchmark.get('annualized_sharpe'))}\n"
            "Sample benchmark time series does not match headline run;\nno benchmark curve is fabricated for this chart.",
            transform=ax.transAxes,
            fontsize=10,
            color=COLORS["gray"],
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "#F8FAFC", "edgecolor": "#E5E7EB"},
        )
    save_figure(fig, PLOTS_DIR / "cumulative_returns.png")


def plot_drawdown(returns: pd.Series, metrics: dict[str, float]) -> None:
    growth = cumulative_growth(returns)
    dd = drawdown_from_growth(growth)
    fig, ax = plt.subplots(figsize=(14, 6.8), constrained_layout=True)
    ax.fill_between(dd.index, dd.values, 0.0, color=COLORS["red"], alpha=0.25)
    ax.plot(dd.index, dd.values, color=COLORS["red"], linewidth=2.2)
    set_research_style(ax, "Medium-Term Alpha: Drawdown", "Drawdown")
    format_date_axis(ax)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    worst_date = dd.idxmin()
    worst_value = float(dd.min())
    ax.scatter([worst_date], [worst_value], color=COLORS["red"], zorder=3)
    ax.annotate(
        f"Max DD {pct(metrics.get('max_drawdown', worst_value))}",
        xy=(worst_date, worst_value),
        xytext=(12, -24),
        textcoords="offset points",
        fontsize=12,
        color=COLORS["navy"],
        arrowprops={"arrowstyle": "->", "color": COLORS["red"]},
    )
    save_figure(fig, PLOTS_DIR / "drawdown.png")


def plot_rolling_sharpe_chart(returns: pd.Series) -> None:
    periods = infer_periods_per_year(returns.index)
    window = 252 if periods == 252 else 12
    sharpe = rolling_sharpe(returns, window, periods)
    label = "252-day" if periods == 252 else "12-month"
    fig, ax = plt.subplots(figsize=(14, 6.8), constrained_layout=True)
    ax.plot(sharpe.index, sharpe, color=COLORS["blue"], linewidth=2.6, label=f"{label} rolling Sharpe")
    ax.axhline(0.0, color="#111827", linewidth=1.1, alpha=0.75, label="Sharpe = 0")
    ax.axhline(1.0, color=COLORS["green"], linewidth=1.4, linestyle="--", alpha=0.95, label="Sharpe = 1")
    set_research_style(ax, f"Medium-Term Alpha: {label.title()} Rolling Sharpe", "Rolling Sharpe")
    format_date_axis(ax)
    ax.legend(frameon=False, loc="upper left")
    save_figure(fig, PLOTS_DIR / "rolling_sharpe.png")


def plot_annual_returns(returns: pd.Series, benchmark_returns: pd.Series | None = None) -> None:
    annual = (1.0 + returns).groupby(returns.index.year).prod() - 1.0
    fig, ax = plt.subplots(figsize=(14, 6.8), constrained_layout=True)
    years = annual.index.astype(str)
    if benchmark_returns is not None and not benchmark_returns.empty:
        benchmark_annual = (1.0 + benchmark_returns).groupby(benchmark_returns.index.year).prod() - 1.0
        benchmark_annual = benchmark_annual.reindex(annual.index)
        positions = np.arange(len(years))
        width = 0.38
        colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in annual.values]
        ax.bar(positions - width / 2, annual.values, color=colors, width=width, label="Strategy")
        ax.bar(positions + width / 2, benchmark_annual.values, color=COLORS["blue"], width=width, alpha=0.78, label="SPY")
        ax.set_xticks(positions)
        ax.set_xticklabels(years)
        ax.legend(frameon=False, loc="upper left")
    else:
        colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in annual.values]
        ax.bar(years, annual.values, color=colors, width=0.68)
    ax.axhline(0.0, color="#111827", linewidth=1.0)
    set_research_style(ax, "Medium-Term Alpha: Calendar-Year Returns", "Return")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.text(
        0.02,
        0.92,
        "Annual returns from saved return-series CSVs.",
        transform=ax.transAxes,
        fontsize=11,
        color=COLORS["gray"],
    )
    save_figure(fig, PLOTS_DIR / "annual_returns.png")


def plot_diagnostics_summary() -> None:
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), constrained_layout=True)
    fig.suptitle("Medium-Term Alpha Diagnostics From Saved Results", fontsize=22, fontweight="bold", color=COLORS["navy"], x=0.02, ha="left")

    sensitivity_path = RESULTS_DIR / "sensitivity_results.csv"
    if sensitivity_path.exists():
        sensitivity = pd.read_csv(sensitivity_path)
        for cost, group in sensitivity.groupby("cost_bps"):
            axes[0, 0].plot(group["top_quantile"], group["annualized_sharpe"], marker="o", linewidth=2.4, label=f"{cost:g} bps")
        set_research_style(axes[0, 0], "Sensitivity: Sharpe by Top Quantile", "Sharpe")
        axes[0, 0].legend(frameon=False, title="Cost")

    capacity_path = RESULTS_DIR / "capacity_simulation.csv"
    if capacity_path.exists():
        capacity = pd.read_csv(capacity_path)
        axes[0, 1].plot(capacity["capital_scale"], capacity["annualized_sharpe"], marker="o", linewidth=2.4, color=COLORS["orange"])
        set_research_style(axes[0, 1], "Capacity Proxy: Sharpe Decay", "Sharpe")
        axes[0, 1].set_xlabel("Capital scale")

    walk_path = RESULTS_DIR / "walk_forward_results.csv"
    if walk_path.exists():
        walk = pd.read_csv(walk_path, parse_dates=["test_start"])
        years = walk["test_start"].dt.year.astype(str)
        colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in walk["annualized_sharpe"]]
        axes[1, 0].bar(years, walk["annualized_sharpe"], color=colors)
        axes[1, 0].axhline(0.0, color="#111827", linewidth=1.0)
        set_research_style(axes[1, 0], "Walk-Forward Test-Year Sharpe", "Sharpe")

    factor_path = RESULTS_DIR / "factor_behavior_summary.csv"
    if factor_path.exists():
        factor = pd.read_csv(factor_path)
        factor = factor[factor["metric"].str.contains("share", case=False, na=False)]
        labels = factor["metric"].str.replace("_", " ", regex=False)
        axes[1, 1].barh(labels, factor["value"].astype(float), color=COLORS["blue"])
        axes[1, 1].xaxis.set_major_formatter(PercentFormatter(1.0))
        set_research_style(axes[1, 1], "Factor Behavior Shares", "Share")

    save_figure(fig, PLOTS_DIR / "factor_or_diagnostics_summary.png")


def plot_holdings_concentration() -> bool:
    path = RESULTS_DIR / "portfolio_weights.csv"
    if not path.exists():
        return False
    weights = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "ticker", "weight", "selected_flag"}
    if not required.issubset(weights.columns):
        return False
    active = weights[weights["selected_flag"].astype(str).str.lower().isin({"true", "1"})].copy()
    if active.empty:
        return False
    active["abs_weight"] = active["weight"].abs()
    concentration = active.groupby("date").agg(
        number_of_positions=("ticker", "count"),
        gross_exposure=("abs_weight", "sum"),
        top_weight=("abs_weight", "max"),
    )

    fig, ax = plt.subplots(figsize=(14, 7.0), constrained_layout=True)
    ax.plot(concentration.index, concentration["number_of_positions"], color=COLORS["blue"], linewidth=2.5, label="Positions")
    ax2 = ax.twinx()
    ax2.plot(concentration.index, concentration["top_weight"], color=COLORS["orange"], linewidth=2.2, label="Largest weight")
    set_research_style(ax, "Medium-Term Alpha Sample Audit: Holdings Concentration", "Number of positions")
    ax2.set_ylabel("Largest absolute weight", color=COLORS["navy"])
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    format_date_axis(ax)
    ax.legend(frameon=False, loc="upper left")
    ax2.legend(frameon=False, loc="upper right")
    save_figure(fig, PLOTS_DIR / "holdings_concentration.png")
    return True


def plot_turnover_costs() -> bool:
    daily_path = RESULTS_DIR / "daily_strategy_returns.csv"
    rebalance_path = RESULTS_DIR / "rebalance_log.csv"
    if daily_path.exists():
        frame = pd.read_csv(daily_path, parse_dates=["date"]).set_index("date").sort_index()
        if not {"turnover", "trading_cost"}.issubset(frame.columns):
            return False
        turnover = pd.to_numeric(frame["turnover"], errors="coerce").fillna(0.0)
        costs = pd.to_numeric(frame["trading_cost"], errors="coerce").fillna(0.0)
    elif rebalance_path.exists():
        frame = pd.read_csv(rebalance_path, parse_dates=["rebalance_date"]).set_index("rebalance_date").sort_index()
        if not {"turnover", "estimated_trading_cost"}.issubset(frame.columns):
            return False
        turnover = pd.to_numeric(frame["turnover"], errors="coerce").fillna(0.0)
        costs = pd.to_numeric(frame["estimated_trading_cost"], errors="coerce").fillna(0.0)
    else:
        return False

    fig, ax = plt.subplots(figsize=(14, 7.0), constrained_layout=True)
    ax.bar(turnover.index, turnover.values, color=COLORS["blue"], alpha=0.75, width=20 if infer_periods_per_year(turnover.index) == 252 else 18)
    ax.set_ylabel("Turnover", color=COLORS["navy"])
    ax2 = ax.twinx()
    ax2.plot(costs.index, costs.cumsum(), color=COLORS["red"], linewidth=2.4, label="Cumulative cost")
    ax2.set_ylabel("Cumulative trading cost", color=COLORS["navy"])
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    set_research_style(ax, "Medium-Term Alpha Sample Audit: Turnover And Trading Costs")
    format_date_axis(ax)
    ax.text(
        0.02,
        0.92,
        f"Sample audit export\nTotal saved trading cost: {costs.sum():.2%}",
        transform=ax.transAxes,
        fontsize=11,
        color=COLORS["gray"],
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "#F8FAFC", "edgecolor": "#E5E7EB"},
    )
    save_figure(fig, PLOTS_DIR / "turnover_costs.png")
    return True


def plot_top_holdings_by_rebalance() -> bool:
    path = RESULTS_DIR / "portfolio_weights.csv"
    if not path.exists():
        return False
    weights = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "ticker", "weight", "selected_flag"}
    if not required.issubset(weights.columns):
        return False
    active = weights[weights["selected_flag"].astype(str).str.lower().isin({"true", "1"})].copy()
    if active.empty:
        return False
    active["abs_weight"] = active["weight"].abs()
    top_names = active.groupby("ticker")["abs_weight"].sum().sort_values(ascending=False).head(10)

    fig, ax = plt.subplots(figsize=(13.5, 7.0), constrained_layout=True)
    bars = ax.barh(top_names.sort_values().index, top_names.sort_values().values, color=COLORS["green"])
    set_research_style(ax, "Medium-Term Alpha Sample Audit: Top Holdings By Cumulative Allocation", "Ticker")
    ax.set_xlabel("Sum of absolute rebalance weights", color=COLORS["navy"])
    for bar in bars:
        width = bar.get_width()
        ax.text(width + max(top_names.max() * 0.01, 0.01), bar.get_y() + bar.get_height() / 2, f"{width:.2f}", va="center", fontsize=10, color=COLORS["navy"])
    save_figure(fig, PLOTS_DIR / "top_holdings_by_rebalance.png")
    return True


def plot_dashboard(
    returns: pd.Series,
    metrics: dict[str, float],
    benchmark: dict[str, float],
    benchmark_returns: pd.Series | None = None,
) -> None:
    growth = cumulative_growth(returns)
    dd = drawdown_from_growth(growth)
    periods = infer_periods_per_year(returns.index)
    window = 252 if periods == 252 else 12
    sharpe = rolling_sharpe(returns, window, periods)
    fig = plt.figure(figsize=(18, 12), constrained_layout=True)
    grid = fig.add_gridspec(2, 2, height_ratios=[1.05, 1.0], width_ratios=[1.45, 1.0])
    fig.suptitle("Medium-Term Alpha Research Report", fontsize=26, fontweight="bold", color=COLORS["navy"], x=0.02, ha="left")
    fig.text(0.02, 0.955, "Generated from saved CSV outputs; no strategy rerun or metric invention.", fontsize=12, color=COLORS["muted"], ha="left")
    ax_growth = fig.add_subplot(grid[0, 0])
    ax_drawdown = fig.add_subplot(grid[1, 0])
    ax_sharpe = fig.add_subplot(grid[1, 1])
    ax_panel = fig.add_subplot(grid[0, 1])

    ax_growth.plot(growth.index, growth, color=COLORS["green"], linewidth=2.8)
    if benchmark_returns is not None and not benchmark_returns.empty:
        benchmark_growth = cumulative_growth(benchmark_returns.reindex(growth.index).fillna(0.0))
        ax_growth.plot(benchmark_growth.index, benchmark_growth, color=COLORS["blue"], linewidth=2.2)
    set_research_style(ax_growth, "Cumulative Growth of $1", "Growth")
    format_date_axis(ax_growth)

    ax_drawdown.fill_between(dd.index, dd.values, 0.0, color=COLORS["red"], alpha=0.25)
    ax_drawdown.plot(dd.index, dd.values, color=COLORS["red"], linewidth=2.0)
    ax_drawdown.yaxis.set_major_formatter(PercentFormatter(1.0))
    set_research_style(ax_drawdown, "Underwater Drawdown", "Drawdown")
    format_date_axis(ax_drawdown)

    ax_sharpe.plot(sharpe.index, sharpe, color=COLORS["blue"], linewidth=2.4)
    ax_sharpe.axhline(0.0, color="#111827", linewidth=1.0, label="Sharpe = 0")
    ax_sharpe.axhline(1.0, color=COLORS["green"], linestyle="--", linewidth=1.2, label="Sharpe = 1")
    set_research_style(ax_sharpe, "12-Month Rolling Sharpe", "Sharpe")
    format_date_axis(ax_sharpe)
    ax_sharpe.legend(frameon=False, loc="upper left")

    rows = [
        ("Annualized return", pct(metrics.get("annualized_return"))),
        ("Annualized Sharpe", num(metrics.get("annualized_sharpe"))),
        ("Total return", pct(metrics.get("total_return"))),
        ("Max drawdown", pct(metrics.get("max_drawdown"))),
        ("Average turnover", num(metrics.get("average_turnover"))),
        ("SPY Sharpe", num(benchmark.get("annualized_sharpe"))),
    ]
    draw_metric_panel(ax_panel, "Key Metrics", "Selected robust default", rows)

    save_figure(fig, PLOTS_DIR / "medium_term_alpha_report.png")


def main() -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    daily_frame = load_daily_strategy_returns(RESULTS_DIR / "daily_strategy_returns.csv")
    summary_metrics = read_metric_csv(RESULTS_DIR / "results_summary.csv")
    comparison_strategy, benchmark = read_comparison_metrics(RESULTS_DIR / "benchmark_comparison.csv")
    metrics = {**summary_metrics, **comparison_strategy}
    if "average_turnover" not in metrics:
        selected = pd.read_csv(RESULTS_DIR / "selected_default_metrics.csv") if (RESULTS_DIR / "selected_default_metrics.csv").exists() else pd.DataFrame()
        if not selected.empty and "average_turnover" in selected:
            metrics["average_turnover"] = float(selected.iloc[0]["average_turnover"])
    if daily_frame is not None and daily_frame_matches_metrics(daily_frame, metrics):
        strategy_returns = daily_frame["net_strategy_return"].dropna()
        benchmark_returns = daily_frame["benchmark_return"].dropna() if "benchmark_return" in daily_frame else None
    else:
        strategy_returns = load_monthly_returns(RESULTS_DIR / "monthly_results.csv")
        benchmark_returns = None

    plot_cumulative_returns(strategy_returns, metrics, benchmark, benchmark_returns)
    plot_drawdown(strategy_returns, metrics)
    plot_rolling_sharpe_chart(strategy_returns)
    plot_annual_returns(strategy_returns, benchmark_returns)
    plot_diagnostics_summary()
    plot_holdings_concentration()
    plot_turnover_costs()
    plot_top_holdings_by_rebalance()
    plot_dashboard(strategy_returns, metrics, benchmark, benchmark_returns)
    print(f"Saved medium-term alpha plots to {PLOTS_DIR}")


if __name__ == "__main__":
    main()

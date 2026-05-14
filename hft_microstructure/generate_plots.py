"""Generate recruiter-facing HFT/microstructure plots from saved result CSVs.

This script is reporting-only. It reads files in Results/ and writes charts to
Plots/ without rerunning the simulator or changing strategy assumptions.
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
    "panel": "#F8FAFC",
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


def format_date_axis(ax: plt.Axes, compact: bool = False) -> None:
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d" if compact else "%b %d"))
    ax.tick_params(axis="x", rotation=0)


def add_metric_box(ax: plt.Axes, text: str, x: float = 0.03, y: float = 0.78) -> None:
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
        facecolor=COLORS["panel"],
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


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def load_daily_results(label: str = "full_heuristic") -> pd.DataFrame:
    path = RESULTS_DIR / "daily_results.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing HFT daily results: {path}")
    frame = pd.read_csv(path)
    if "Label" in frame and label in set(frame["Label"]):
        frame = frame[frame["Label"] == label].copy()
    for column in [
        "ProcessedQuotes",
        "CompletedTrades",
        "SkippedLowEdge",
        "MissedExpectedEdgeBps",
        "ReturnIntervals",
        "TotalNetReturnBps",
        "MaxDrawdownBps",
        "MinuteReturnSharpe",
        "TradeSharpeReference",
    ]:
        if column in frame:
            frame[column] = numeric(frame[column])
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.sort_values("Date")
    frame["CumulativePnlBps"] = frame["TotalNetReturnBps"].cumsum()
    frame["DrawdownBps"] = frame["CumulativePnlBps"] - frame["CumulativePnlBps"].cummax()
    return frame


def load_summary() -> pd.Series:
    path = RESULTS_DIR / "results_summary.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    frame = pd.read_csv(path)
    if "Label" in frame:
        match = frame[frame["Label"].eq("Full Portfolio Heuristic All Days")]
        row = match.iloc[0] if not match.empty else frame.iloc[0]
    else:
        row = frame.iloc[0]
    converted = row.copy()
    for key, value in row.items():
        if key != "Label":
            try:
                converted[key] = float(str(value).replace(",", "."))
            except ValueError:
                converted[key] = value
    return converted


def plot_cumulative_pnl(daily: pd.DataFrame, summary: pd.Series) -> None:
    fig, ax = plt.subplots(figsize=(14, 7.2), constrained_layout=True)
    ax.plot(daily["Date"], daily["CumulativePnlBps"], color=COLORS["green"], linewidth=3.0)
    set_research_style(ax, "HFT Microstructure: Cumulative Net PnL", "Cumulative PnL (bps)")
    format_date_axis(ax)
    final_pnl = float(daily["CumulativePnlBps"].iloc[-1])
    ax.scatter([daily["Date"].iloc[-1]], [final_pnl], color=COLORS["green"], zorder=3)
    ax.annotate(
        f"Final PnL: {final_pnl:,.1f} bps",
        xy=(daily["Date"].iloc[-1], final_pnl),
        xytext=(-110, 24),
        textcoords="offset points",
        fontsize=12,
        color=COLORS["navy"],
        arrowprops={"arrowstyle": "->", "color": COLORS["green"]},
    )
    add_metric_box(
        ax,
        f"Minute Sharpe: {float(summary.get('MinuteSharpe', np.nan)):.2f}\n"
        f"Trades: {float(summary.get('TradeCount', np.nan)):,.0f}\n"
        f"Worst DD: {float(summary.get('WorstDrawdownBps', np.nan)):,.1f} bps",
    )
    save_figure(fig, PLOTS_DIR / "cumulative_pnl.png")


def plot_daily_returns(daily: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(14, 7.2), constrained_layout=True)
    colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in daily["TotalNetReturnBps"]]
    ax.bar(daily["Date"], daily["TotalNetReturnBps"], color=colors, width=0.72)
    ax.axhline(0.0, color="#111827", linewidth=1.2)
    set_research_style(ax, "HFT Microstructure: Session Net PnL", "Session PnL (bps)")
    ax.set_xlabel("Session date", color=COLORS["navy"])
    format_date_axis(ax)
    save_figure(fig, PLOTS_DIR / "daily_returns.png")


def plot_drawdown(daily: pd.DataFrame, summary: pd.Series) -> None:
    fig, ax = plt.subplots(figsize=(14, 6.8), constrained_layout=True)
    ax.fill_between(daily["Date"], daily["DrawdownBps"], 0.0, color=COLORS["red"], alpha=0.25)
    ax.plot(daily["Date"], daily["DrawdownBps"], color=COLORS["red"], linewidth=2.2)
    set_research_style(ax, "HFT Microstructure: Cumulative PnL Drawdown", "Drawdown (bps)")
    format_date_axis(ax)
    lower = min(float(daily["DrawdownBps"].min()) * 1.25, -1.0)
    ax.set_ylim(lower, max(1.0, float(daily["DrawdownBps"].max()) + 1.0))
    worst_idx = daily["DrawdownBps"].idxmin()
    worst_date = daily.loc[worst_idx, "Date"]
    worst_value = float(daily.loc[worst_idx, "DrawdownBps"])
    ax.scatter([worst_date], [worst_value], color=COLORS["red"], zorder=3)
    ax.annotate(
        f"Daily-curve max DD: {worst_value:,.1f} bps\nSaved intraday worst DD: {float(summary.get('WorstDrawdownBps', np.nan)):,.1f} bps",
        xy=(worst_date, worst_value),
        xytext=(12, -34),
        textcoords="offset points",
        fontsize=11,
        color=COLORS["navy"],
        arrowprops={"arrowstyle": "->", "color": COLORS["red"]},
    )
    save_figure(fig, PLOTS_DIR / "drawdown.png")


def plot_sleeve_contribution() -> bool:
    path = RESULTS_DIR / "strategy_sleeve_monte_carlo.csv"
    if not path.exists():
        return False
    frame = pd.read_csv(path)
    if not {"Strategy", "AvgNetReturnBps"}.issubset(frame.columns):
        return False
    frame["AvgNetReturnBps"] = numeric(frame["AvgNetReturnBps"])
    frame = frame.sort_values("AvgNetReturnBps", ascending=True)
    fig, ax = plt.subplots(figsize=(13.5, 7.0), constrained_layout=True)
    bars = ax.barh(frame["Strategy"], frame["AvgNetReturnBps"], color=[COLORS["blue"], COLORS["orange"], COLORS["green"]][: len(frame)])
    set_research_style(ax, "HFT Sleeve Contribution: Average Net Return")
    ax.set_xlabel("Avg net return (bps)", color=COLORS["navy"])
    ax.set_ylabel("Strategy sleeve", color=COLORS["navy"])
    for bar in bars:
        width = bar.get_width()
        ax.text(width + max(frame["AvgNetReturnBps"].max() * 0.015, 0.2), bar.get_y() + bar.get_height() / 2, f"{width:.1f}", va="center", fontsize=11, color=COLORS["navy"])
    save_figure(fig, PLOTS_DIR / "sleeve_contribution.png")
    return True


def plot_trade_diagnostics(summary: pd.Series) -> None:
    fig, ax = plt.subplots(figsize=(12, 7.0), constrained_layout=True)
    rows = [
        ("Minute Sharpe", f"{float(summary.get('MinuteSharpe', np.nan)):.2f}"),
        ("Total PnL", f"{float(summary.get('TotalPnlBps', np.nan)):,.1f} bps"),
        ("Worst drawdown", f"{float(summary.get('WorstDrawdownBps', np.nan)):,.1f} bps"),
        ("Trade count", f"{float(summary.get('TradeCount', np.nan)):,.0f}"),
        ("Win day rate", f"{float(summary.get('WinRate', np.nan)):.1%}"),
        ("Avg daily trades", f"{float(summary.get('AvgDailyTrades', np.nan)):,.0f}"),
    ]
    draw_metric_panel(ax, "HFT Trade Diagnostics", "From saved results_summary.csv; no simulator rerun.", rows)
    save_figure(fig, PLOTS_DIR / "trade_diagnostics.png")


def plot_ablation_results() -> bool:
    path = RESULTS_DIR / "ablation_results.csv"
    if not path.exists():
        return False
    frame = pd.read_csv(path)
    required = {"variant", "total_pnl_bps", "trade_count"}
    if not required.issubset(frame.columns):
        return False
    frame["total_pnl_bps"] = numeric(frame["total_pnl_bps"])
    frame["trade_count"] = numeric(frame["trade_count"])
    frame = frame.sort_values("total_pnl_bps", ascending=True)

    fig, ax = plt.subplots(figsize=(14, 7.4), constrained_layout=True)
    colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in frame["total_pnl_bps"]]
    bars = ax.barh(frame["variant"].str.replace("_", " ").str.title(), frame["total_pnl_bps"], color=colors)
    ax.axvline(0.0, color="#111827", linewidth=1.1)
    set_research_style(ax, "HFT Demo Ablation: Net PnL By Variant", "Variant")
    ax.set_xlabel("Total PnL (bps)", color=COLORS["navy"])
    for bar, trades in zip(bars, frame["trade_count"]):
        width = bar.get_width()
        label_x = width + (0.35 if width >= 0 else -0.35)
        ha = "left" if width >= 0 else "right"
        ax.text(label_x, bar.get_y() + bar.get_height() / 2, f"{width:.1f} bps | {trades:.0f} trades", va="center", ha=ha, fontsize=10, color=COLORS["navy"])
    add_metric_box(ax, "Synthetic demo diagnostics\nNot the historical 30-session result", x=0.04, y=0.08)
    save_figure(fig, PLOTS_DIR / "ablation_results.png")
    return True


def plot_latency_sensitivity() -> bool:
    path = RESULTS_DIR / "latency_sensitivity.csv"
    if not path.exists():
        return False
    frame = pd.read_csv(path)
    required = {"scenario", "total_pnl_bps", "percent_degradation_vs_baseline", "adverse_selection_bps"}
    if not required.issubset(frame.columns):
        return False
    frame["total_pnl_bps"] = numeric(frame["total_pnl_bps"])
    frame["percent_degradation_vs_baseline"] = numeric(frame["percent_degradation_vs_baseline"])
    frame["adverse_selection_bps"] = numeric(frame["adverse_selection_bps"])

    fig, ax = plt.subplots(figsize=(14, 7.2), constrained_layout=True)
    ax.plot(frame["adverse_selection_bps"], frame["total_pnl_bps"], color=COLORS["red"], linewidth=3.0, marker="o", markersize=7)
    ax.axhline(0.0, color="#111827", linewidth=1.1)
    set_research_style(ax, "HFT Demo Adverse-Selection Stress", "Total PnL (bps)")
    ax.set_xlabel("Additional adverse-selection penalty per completed trade (bps)", color=COLORS["navy"])
    for _, row in frame.iterrows():
        ax.annotate(
            f"{row['total_pnl_bps']:.1f}",
            xy=(row["adverse_selection_bps"], row["total_pnl_bps"]),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            color=COLORS["navy"],
        )
    add_metric_box(ax, "Proxy stress only\nDoes not model exchange latency", x=0.04, y=0.08)
    save_figure(fig, PLOTS_DIR / "latency_sensitivity.png")
    return True


def plot_trade_pnl_distribution() -> bool:
    path = RESULTS_DIR / "trade_log.csv"
    if not path.exists():
        return False
    frame = pd.read_csv(path)
    if "net_pnl_bps" not in frame.columns:
        return False
    frame["net_pnl_bps"] = numeric(frame["net_pnl_bps"])
    frame = frame.dropna(subset=["net_pnl_bps"])
    if frame.empty:
        return False

    fig, ax = plt.subplots(figsize=(13.5, 7.0), constrained_layout=True)
    ax.hist(frame["net_pnl_bps"], bins=min(30, max(8, len(frame) // 4)), color=COLORS["blue"], alpha=0.82, edgecolor="white")
    ax.axvline(0.0, color="#111827", linewidth=1.1)
    ax.axvline(frame["net_pnl_bps"].mean(), color=COLORS["orange"], linewidth=2.4, linestyle="--", label="Mean net PnL")
    set_research_style(ax, "HFT Demo Trade PnL Distribution", "Trade count")
    ax.set_xlabel("Net PnL per completed trade (bps)", color=COLORS["navy"])
    ax.legend(frameon=False, loc="upper left")
    add_metric_box(
        ax,
        f"Trades: {len(frame):,.0f}\nMean: {frame['net_pnl_bps'].mean():.3f} bps\nWin rate: {(frame['net_pnl_bps'] > 0).mean():.1%}",
        x=0.67,
        y=0.70,
    )
    save_figure(fig, PLOTS_DIR / "trade_pnl_distribution.png")
    return True


def plot_rejected_signal_reasons() -> bool:
    path = RESULTS_DIR / "rejected_signals.csv"
    if not path.exists():
        return False
    frame = pd.read_csv(path)
    if "reason" not in frame.columns or frame.empty:
        return False
    counts = frame["reason"].value_counts().sort_values(ascending=True)

    fig, ax = plt.subplots(figsize=(13, 6.8), constrained_layout=True)
    bars = ax.barh(counts.index.str.replace("_", " ").str.title(), counts.values, color=COLORS["gray"])
    set_research_style(ax, "HFT Demo Rejected Signal Reasons", "Reason")
    ax.set_xlabel("Count", color=COLORS["navy"])
    for bar in bars:
        width = bar.get_width()
        ax.text(width + max(counts.max() * 0.01, 1.0), bar.get_y() + bar.get_height() / 2, f"{int(width):,}", va="center", fontsize=10, color=COLORS["navy"])
    save_figure(fig, PLOTS_DIR / "rejected_signal_reasons.png")
    return True


def plot_dashboard(daily: pd.DataFrame, summary: pd.Series) -> None:
    fig = plt.figure(figsize=(18, 12), constrained_layout=True)
    grid = fig.add_gridspec(2, 2, height_ratios=[1.05, 1.0], width_ratios=[1.45, 1.0])
    fig.suptitle("HFT Microstructure Research Report", fontsize=26, fontweight="bold", color=COLORS["navy"], x=0.02, ha="left")
    fig.text(0.02, 0.955, "Generated from saved CSV outputs; no backtest rerun or metric invention.", fontsize=12, color=COLORS["muted"], ha="left")
    ax_cum = fig.add_subplot(grid[0, 0])
    ax_dd = fig.add_subplot(grid[1, 0])
    ax_bar = fig.add_subplot(grid[1, 1])
    ax_panel = fig.add_subplot(grid[0, 1])

    ax_cum.plot(daily["Date"], daily["CumulativePnlBps"], color=COLORS["green"], linewidth=2.8)
    set_research_style(ax_cum, "Cumulative Net PnL", "bps")
    format_date_axis(ax_cum, compact=True)

    ax_dd.fill_between(daily["Date"], daily["DrawdownBps"], 0.0, color=COLORS["red"], alpha=0.25)
    ax_dd.plot(daily["Date"], daily["DrawdownBps"], color=COLORS["red"], linewidth=2.0)
    set_research_style(ax_dd, "Drawdown", "bps")
    format_date_axis(ax_dd, compact=True)

    colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in daily["TotalNetReturnBps"]]
    ax_bar.bar(daily["Date"], daily["TotalNetReturnBps"], color=colors, width=0.72)
    ax_bar.axhline(0.0, color="#111827", linewidth=1.0)
    set_research_style(ax_bar, "Session PnL", "bps")
    format_date_axis(ax_bar, compact=True)

    rows = [
        ("Minute Sharpe", f"{float(summary.get('MinuteSharpe', np.nan)):.2f}"),
        ("Total PnL", f"{float(summary.get('TotalPnlBps', np.nan)):,.1f} bps"),
        ("Worst DD", f"{float(summary.get('WorstDrawdownBps', np.nan)):,.1f} bps"),
        ("Trades", f"{float(summary.get('TradeCount', np.nan)):,.0f}"),
        ("Win day rate", f"{float(summary.get('WinRate', np.nan)):.1%}"),
        ("Avg daily trades", f"{float(summary.get('AvgDailyTrades', np.nan)):,.0f}"),
    ]
    draw_metric_panel(ax_panel, "Key Metrics", "Full Portfolio Heuristic All Days", rows)

    save_figure(fig, PLOTS_DIR / "hft_report.png")


def main() -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    daily = load_daily_results()
    summary = load_summary()
    plot_cumulative_pnl(daily, summary)
    plot_daily_returns(daily)
    plot_drawdown(daily, summary)
    sleeve_created = plot_sleeve_contribution()
    plot_trade_diagnostics(summary)
    ablation_created = plot_ablation_results()
    latency_created = plot_latency_sensitivity()
    trade_distribution_created = plot_trade_pnl_distribution()
    rejected_created = plot_rejected_signal_reasons()
    plot_dashboard(daily, summary)
    if not sleeve_created:
        print("sleeve_contribution_skipped=missing strategy_sleeve_monte_carlo.csv columns")
    if not ablation_created:
        print("ablation_results_skipped=missing ablation_results.csv columns")
    if not latency_created:
        print("latency_sensitivity_skipped=missing latency_sensitivity.csv columns")
    if not trade_distribution_created:
        print("trade_pnl_distribution_skipped=missing trade_log.csv net_pnl_bps")
    if not rejected_created:
        print("rejected_signal_reasons_skipped=missing rejected_signals.csv reason")
    print(f"Saved HFT plots to {PLOTS_DIR}")


if __name__ == "__main__":
    main()

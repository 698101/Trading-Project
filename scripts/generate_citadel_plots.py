#!/usr/bin/env python3
"""Generate dark-theme reviewer plots from the saved portfolio evidence.

The script is reporting-only. It does not rerun backtests, retune parameters,
or invent missing series. Medium-term charts that use committed sample audit
files are labelled as sample-audit views.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib_cache"))
LOCAL_DEPS = ROOT / ".pip_tmp"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D


HFT_RESULTS = ROOT / "hft_microstructure" / "Results"
HFT_PLOTS = ROOT / "hft_microstructure" / "Plots"
MEDIUM_RESULTS = ROOT / "medium_term_alpha" / "Results"
MEDIUM_PLOTS = ROOT / "medium_term_alpha" / "Plots"

BG = "#070B14"
PANEL = "#0D1321"
PANEL_2 = "#111827"
GRID = "#263244"
TEXT = "#E5E7EB"
MUTED = "#94A3B8"
WHITE = "#F8FAFC"
GREEN = "#34D399"
RED = "#FB7185"
AMBER = "#FBBF24"
CYAN = "#22D3EE"
BLUE = "#60A5FA"
PURPLE = "#A78BFA"
PINK = "#F472B6"
ORANGE = "#FB923C"

SYMBOL_COLORS = {"SPY": CYAN, "QQQ": PURPLE, "IWM": AMBER}
MODE_STYLES = {"full": "-", "mm-only": "--"}


plt.rcParams.update(
    {
        "figure.facecolor": BG,
        "axes.facecolor": PANEL,
        "savefig.facecolor": BG,
        "font.family": "DejaVu Sans",
        "axes.titleweight": "bold",
        "axes.labelcolor": TEXT,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "text.color": TEXT,
        "axes.edgecolor": GRID,
        "legend.facecolor": PANEL_2,
        "legend.edgecolor": GRID,
    }
)


def ensure_dirs() -> None:
    HFT_PLOTS.mkdir(parents=True, exist_ok=True)
    MEDIUM_PLOTS.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required plot input: {path}")
    return pd.read_csv(path, **kwargs)


def clean_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def style_ax(ax: plt.Axes, title: str, xlabel: str | None = None, ylabel: str | None = None) -> None:
    ax.set_facecolor(PANEL)
    ax.set_title(title, loc="left", fontsize=16, color=WHITE, pad=12)
    if xlabel:
        ax.set_xlabel(xlabel, color=TEXT, labelpad=8)
    if ylabel:
        ax.set_ylabel(ylabel, color=TEXT, labelpad=8)
    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.75)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.tick_params(colors=MUTED)


def add_note(fig: plt.Figure, note: str) -> None:
    fig.text(0.01, 0.012, note, color=MUTED, fontsize=9, ha="left", va="bottom")


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.set_constrained_layout(False)
    try:
        fig.tight_layout(rect=(0.0, 0.04, 1.0, 0.975))
    except Exception:
        pass
    fig.savefig(path, dpi=220, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def format_bps(value: float) -> str:
    return f"{value:,.0f} bps"


def format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_pp(value: float) -> str:
    return f"{value * 100:+.1f} pp"


def line_legend(ax: plt.Axes, ncol: int = 2, loc: str = "best") -> None:
    legend = ax.legend(loc=loc, ncol=ncol, frameon=True, fontsize=9)
    if legend:
        for text in legend.get_texts():
            text.set_color(TEXT)


def hft_daily(symbol: str, mode: str = "full") -> pd.DataFrame:
    suffix = "" if mode == "full" else "_mm_only"
    path = HFT_RESULTS / f"alpaca_{symbol.lower()}_real_quote{suffix}_daily_results.csv"
    frame = read_csv(path)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["total_net_return_bps"] = clean_num(frame["total_net_return_bps"])
    frame["cumulative_pnl_bps"] = frame["total_net_return_bps"].cumsum()
    frame["drawdown_bps"] = frame["cumulative_pnl_bps"] - frame["cumulative_pnl_bps"].cummax()
    frame["mode"] = mode
    return frame


def hft_summary() -> pd.DataFrame:
    frame = read_csv(HFT_RESULTS / "alpaca_real_quote_cross_symbol_summary.csv")
    numeric_cols = [
        "ok_sessions",
        "backtest_sessions",
        "full_total_pnl_bps",
        "full_minute_sharpe",
        "full_worst_drawdown_bps",
        "full_trade_count",
        "mm_total_pnl_bps",
        "mm_minute_sharpe",
        "mm_worst_drawdown_bps",
        "mm_trade_count",
    ]
    for col in numeric_cols:
        frame[col] = clean_num(frame[col])
    return frame


def hft_quality_summary() -> pd.DataFrame:
    frame = read_csv(HFT_RESULTS / "micro_alpha_quality_sharpe_summary.csv")
    numeric_cols = [
        "min_edge_bps",
        "mm_min_entry_microprice_edge_100ms_bps",
        "mm_min_entry_spread_100ms_bps",
        "minute_sharpe",
        "daily_sharpe",
        "annualized_daily_sharpe",
        "total_pnl_bps",
        "worst_drawdown_bps",
        "trade_count",
    ]
    for col in numeric_cols:
        if col in frame:
            frame[col] = clean_num(frame[col])
    return frame


def hft_validation_summary() -> pd.DataFrame:
    frame = read_csv(HFT_RESULTS / "micro_alpha_validation_summary.csv")
    numeric_cols = [
        "sessions",
        "total_pnl_bps",
        "avg_daily_pnl_bps",
        "daily_sharpe",
        "annualized_daily_sharpe",
        "minute_sharpe",
        "worst_drawdown_bps",
        "trade_count",
    ]
    for col in numeric_cols:
        if col in frame:
            frame[col] = clean_num(frame[col])
    return frame


def hft_evidence_ci() -> pd.DataFrame:
    frame = read_csv(HFT_RESULTS / "real_quote_evidence_ci.csv")
    for col in [
        "avg_daily_pnl_bps",
        "avg_daily_pnl_ci95_low_bps",
        "avg_daily_pnl_ci95_high_bps",
        "minute_sharpe",
        "total_pnl_bps",
    ]:
        frame[col] = clean_num(frame[col])
    return frame


def hft_stress(symbol: str) -> pd.DataFrame:
    frame = read_csv(HFT_RESULTS / f"alpaca_{symbol.lower()}_real_quote_stress_distribution_summary.csv")
    for col in [
        "adverse_selection_bps",
        "mean_total_pnl_bps",
        "mean_minute_sharpe",
        "positive_pnl_run_rate",
    ]:
        frame[col] = clean_num(frame[col])
    frame["symbol"] = symbol
    return frame


def hft_latency(symbol: str) -> pd.DataFrame:
    frame = read_csv(HFT_RESULTS / f"alpaca_{symbol.lower()}_real_quote_latency_sensitivity.csv")
    for col in ["signal_latency_us", "total_pnl_bps", "minute_sharpe", "latency_expired_signals"]:
        frame[col] = clean_num(frame[col])
    frame["symbol"] = symbol
    return frame


def add_hft_title(fig: plt.Figure, subtitle: str) -> None:
    fig.suptitle(
        "HFT Microstructure Real-Quote Evidence",
        x=0.01,
        y=0.995,
        ha="left",
        fontsize=23,
        color=WHITE,
        fontweight="bold",
    )
    fig.text(0.01, 0.955, subtitle, color=MUTED, ha="left", fontsize=11)


def plot_hft_dashboard() -> None:
    summary = hft_summary()
    quality = hft_quality_summary()
    quality_combined = quality[quality["scope"] == "combined"].iloc[0]
    quality_symbols = quality[quality["scope"] == "selected_quality"].set_index("symbol")
    ci = hft_evidence_ci()
    stress = pd.concat([hft_stress(symbol) for symbol in SYMBOL_COLORS], ignore_index=True)

    fig = plt.figure(figsize=(17, 10.5))
    grid = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.0])
    add_hft_title(
        fig,
        "51 open-window sessions. Selected quality-gate micro alpha: "
        f"{quality_combined['minute_sharpe']:.3f} minute Sharpe, "
        f"{quality_combined['daily_sharpe']:.3f} daily Sharpe.",
    )

    ax_pnl = fig.add_subplot(grid[0, 0])
    x = np.arange(len(summary))
    width = 0.25
    quality_pnl = [quality_symbols.loc[symbol, "total_pnl_bps"] for symbol in summary["symbol"]]
    ax_pnl.bar(x - width, summary["full_total_pnl_bps"], width, label="Full portfolio", color=BLUE)
    ax_pnl.bar(x, summary["mm_total_pnl_bps"], width, label="Baseline mm-only", color=GREEN)
    ax_pnl.bar(x + width, quality_pnl, width, label="Selected quality gate", color=AMBER)
    ax_pnl.set_xticks(x)
    ax_pnl.set_xticklabels(summary["symbol"])
    style_ax(ax_pnl, "Total PnL: Baseline vs Quality Gate", "Symbol", "Total PnL (bps)")
    line_legend(ax_pnl, ncol=1)

    ax_sharpe = fig.add_subplot(grid[0, 1])
    quality_sharpe = [quality_symbols.loc[symbol, "minute_sharpe"] for symbol in summary["symbol"]]
    ax_sharpe.bar(x - width, summary["full_minute_sharpe"], width, label="Full portfolio", color=BLUE)
    ax_sharpe.bar(x, summary["mm_minute_sharpe"], width, label="Baseline mm-only", color=GREEN)
    ax_sharpe.bar(x + width, quality_sharpe, width, label="Selected quality gate", color=AMBER)
    ax_sharpe.axhline(0.0, color=MUTED, linewidth=1)
    ax_sharpe.set_xticks(x)
    ax_sharpe.set_xticklabels(summary["symbol"])
    style_ax(ax_sharpe, "Minute Sharpe: Baseline vs Quality Gate", "Symbol", "Minute Sharpe")
    line_legend(ax_sharpe, ncol=1)

    ax_ci = fig.add_subplot(grid[0, 2])
    labels = [f"{row.symbol} {row.portfolio_mode}" for row in ci.itertuples()]
    y = np.arange(len(ci))
    low = ci["avg_daily_pnl_bps"] - ci["avg_daily_pnl_ci95_low_bps"]
    high = ci["avg_daily_pnl_ci95_high_bps"] - ci["avg_daily_pnl_bps"]
    colors = [SYMBOL_COLORS[row.symbol] for row in ci.itertuples()]
    ax_ci.errorbar(ci["avg_daily_pnl_bps"], y, xerr=[low, high], fmt="o", color=WHITE, ecolor=MUTED, capsize=4)
    ax_ci.scatter(ci["avg_daily_pnl_bps"], y, c=colors, s=48, zorder=3)
    ax_ci.set_yticks(y)
    ax_ci.set_yticklabels(labels)
    ax_ci.invert_yaxis()
    style_ax(ax_ci, "Average Daily PnL With 95% CI", "Average daily PnL (bps)", "")

    ax_stress = fig.add_subplot(grid[1, :2])
    for symbol, color in SYMBOL_COLORS.items():
        for mode, linestyle in MODE_STYLES.items():
            subset = stress[(stress["symbol"] == symbol) & (stress["portfolio_mode"] == mode)]
            ax_stress.plot(
                subset["adverse_selection_bps"],
                subset["mean_total_pnl_bps"],
                color=color,
                linestyle=linestyle,
                linewidth=2.2,
                marker="o",
                label=f"{symbol} {mode}",
            )
    ax_stress.axhline(0.0, color=RED, linewidth=1.2)
    style_ax(ax_stress, "Adverse-Selection Stress Boundary", "Penalty per completed trade (bps)", "Mean total PnL (bps)")
    line_legend(ax_stress, ncol=3, loc="upper right")

    ax_text = fig.add_subplot(grid[1, 2])
    ax_text.set_facecolor(PANEL)
    ax_text.set_axis_off()
    baseline = quality[quality["scope"] == "original_mm_baseline"].iloc[0]
    minute_delta = float(quality_combined["minute_sharpe"] - baseline["minute_sharpe"])
    trade_delta = float(quality_combined["trade_count"] - baseline["trade_count"])
    trade_pct = trade_delta / float(baseline["trade_count"])
    lines = [
        ("Quality", f"daily Sharpe {quality_combined['daily_sharpe']:.3f}, minute Sharpe {quality_combined['minute_sharpe']:.3f}", AMBER),
        ("Improvement", f"+{minute_delta:.3f} minute Sharpe, {trade_pct * 100:.1f}% trades", GREEN),
        ("SPY", "survives 1 bps, fails at 2 bps", CYAN),
        ("QQQ", "survives 0.5 bps, fails around 1 bps", PURPLE),
        ("IWM", "full-mode marginal at 1 bps", AMBER),
    ]
    ax_text.text(0.04, 0.92, "Interview-Ready Interpretation", fontsize=15, fontweight="bold", color=WHITE)
    y0 = 0.78
    for label, text, color in lines:
        ax_text.text(0.06, y0, label, fontsize=13, color=color, fontweight="bold")
        ax_text.text(0.43, y0, text, fontsize=11, color=TEXT)
        y0 -= 0.15
    ax_text.text(0.06, 0.05, "Data: Alpaca IEX top-of-book quote replay, not live fills.", fontsize=10, color=MUTED)

    add_note(fig, "Generated from Alpaca IEX top-of-book quote replay summaries. Raw quotes are local and excluded from git.")
    save(fig, HFT_PLOTS / "hft_real_quote_dashboard.png")
    shutil.copy2(HFT_PLOTS / "hft_real_quote_dashboard.png", HFT_PLOTS / "hft_report.png")


def plot_hft_micro_alpha_quality() -> None:
    quality = hft_quality_summary()
    versions = quality[quality["scope"].isin(["original_mm_baseline", "prior_edge_selected", "combined"])].copy()
    label_map = {
        "original_mm_baseline": "Original\nmm baseline",
        "prior_edge_selected": "Prior\nedge-selected",
        "combined": "Selected\nquality gate",
    }
    versions["label"] = versions["scope"].map(label_map)
    symbol_rows = quality[quality["scope"] == "selected_quality"].copy()
    baseline = quality[quality["scope"] == "original_mm_baseline"].iloc[0]
    selected = quality[quality["scope"] == "combined"].iloc[0]
    minute_delta = float(selected["minute_sharpe"] - baseline["minute_sharpe"])
    pnl_delta = float(selected["total_pnl_bps"] - baseline["total_pnl_bps"])
    trade_pct = float((selected["trade_count"] / baseline["trade_count"]) - 1.0)

    fig = plt.figure(figsize=(16, 9))
    grid = fig.add_gridspec(2, 3, width_ratios=[1.1, 1.1, 0.95])
    fig.suptitle(
        "Micro Alpha Quality-Gate Sharpe Improvement",
        x=0.01,
        y=0.995,
        ha="left",
        fontsize=22,
        color=WHITE,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.955,
        "Selected SPY/QQQ quality gates and IWM edge floor, combined across SPY/QQQ/IWM daily PnL streams.",
        color=MUTED,
        ha="left",
        fontsize=11,
    )

    ax_daily = fig.add_subplot(grid[0, 0])
    bars = ax_daily.bar(versions["label"], versions["daily_sharpe"], color=[GREEN, CYAN, AMBER])
    style_ax(ax_daily, "Combined Daily Sharpe", "Configuration", "Daily Sharpe")
    ax_daily.axhline(0.0, color=MUTED, linewidth=1)
    for bar, value in zip(bars, versions["daily_sharpe"]):
        ax_daily.text(bar.get_x() + bar.get_width() / 2, value + 0.06, f"{value:.3f}", ha="center", color=TEXT, fontsize=11, fontweight="bold")

    ax_minute = fig.add_subplot(grid[0, 1])
    bars = ax_minute.bar(versions["label"], versions["minute_sharpe"], color=[GREEN, CYAN, AMBER])
    style_ax(ax_minute, "Combined Minute Sharpe", "Configuration", "Minute Sharpe")
    ax_minute.axhline(0.0, color=MUTED, linewidth=1)
    for bar, value in zip(bars, versions["minute_sharpe"]):
        ax_minute.text(bar.get_x() + bar.get_width() / 2, value + 0.015, f"{value:.3f}", ha="center", color=TEXT, fontsize=11, fontweight="bold")

    ax_summary = fig.add_subplot(grid[0, 2])
    ax_summary.set_axis_off()
    summary_rows = [
        ("Daily Sharpe", f"{selected['daily_sharpe']:.3f}", AMBER),
        ("Minute Sharpe", f"{selected['minute_sharpe']:.3f}", AMBER),
        ("Minute Sharpe Delta", f"+{minute_delta:.3f}", GREEN),
        ("PnL Delta", f"{pnl_delta:+,.1f} bps", GREEN if pnl_delta >= 0 else RED),
        ("Trade Count Change", f"{trade_pct * 100:+.1f}%", GREEN if trade_pct <= 0 else AMBER),
    ]
    ax_summary.text(0.03, 0.88, "Selected Combined Result", fontsize=15, color=WHITE, fontweight="bold")
    y = 0.72
    for label, value, color in summary_rows:
        ax_summary.text(0.04, y, label, fontsize=11, color=MUTED)
        ax_summary.text(0.96, y, value, fontsize=14, color=color, ha="right", fontweight="bold")
        y -= 0.14

    ax_symbol = fig.add_subplot(grid[1, :2])
    symbol_x = np.arange(len(symbol_rows))
    bars = ax_symbol.bar(symbol_x, symbol_rows["minute_sharpe"], color=[SYMBOL_COLORS.get(symbol, AMBER) for symbol in symbol_rows["symbol"]])
    ax_symbol.set_xticks(symbol_x)
    ax_symbol.set_xticklabels(symbol_rows["symbol"])
    style_ax(ax_symbol, "Selected Quality-Gate Minute Sharpe By Symbol", "Symbol", "Minute Sharpe")
    for bar, row in zip(bars, symbol_rows.itertuples()):
        label = f"{row.minute_sharpe:.3f}\nedge {row.min_edge_bps:.2f}"
        ax_symbol.text(bar.get_x() + bar.get_width() / 2, row.minute_sharpe + 0.02, label, ha="center", color=TEXT, fontsize=10)

    ax_params = fig.add_subplot(grid[1, 2])
    ax_params.set_axis_off()
    ax_params.text(0.03, 0.88, "Quality Gates", fontsize=15, color=WHITE, fontweight="bold")
    y = 0.70
    for row in symbol_rows.itertuples():
        ax_params.text(0.04, y, row.symbol, fontsize=12, color=SYMBOL_COLORS.get(row.symbol, TEXT), fontweight="bold")
        ax_params.text(
            0.26,
            y,
            f"edge {row.min_edge_bps:.2f}, micro {row.mm_min_entry_microprice_edge_100ms_bps:.2f}, spread {row.mm_min_entry_spread_100ms_bps:.2f}",
            fontsize=10,
            color=TEXT,
        )
        y -= 0.17
    ax_params.text(0.04, 0.08, "Primary metric remains minute Sharpe; daily Sharpe is a combined-session diagnostic.", fontsize=10, color=MUTED)

    add_note(fig, "Generated from micro_alpha_quality_sharpe_summary.csv. The 2.876 value is combined daily Sharpe across SPY, QQQ, and IWM daily PnL.")
    save(fig, HFT_PLOTS / "hft_micro_alpha_quality_sharpe.png")


def plot_hft_micro_alpha_validation() -> None:
    validation = hft_validation_summary()
    combined = validation[validation["scope"] == "combined"].copy()
    combined["display_label"] = combined["label"].str.replace(" ", "\n")
    train = combined[combined["split"] == "train"].copy()
    oos = combined[combined["split"] == "oos"].copy()
    selected_oos = oos[oos["variant"] == "selected_quality_gate"].iloc[0]
    baseline_oos = oos[oos["variant"] == "original_mm_baseline"].iloc[0]
    minute_delta = float(selected_oos["minute_sharpe"] - baseline_oos["minute_sharpe"])

    fig = plt.figure(figsize=(16, 8.6))
    grid = fig.add_gridspec(2, 3, width_ratios=[1.15, 1.15, 0.9])
    fig.suptitle(
        "Micro Alpha Chronological Validation",
        x=0.01,
        y=0.995,
        ha="left",
        fontsize=22,
        color=WHITE,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.955,
        "31-session train window and 20-session OOS window from saved SPY/QQQ/IWM backtests.",
        color=MUTED,
        ha="left",
        fontsize=11,
    )

    colors = [GREEN if variant == "selected_quality_gate" else CYAN if variant == "prior_edge_selected" else AMBER for variant in oos["variant"]]

    ax_minute = fig.add_subplot(grid[0, 0])
    bars = ax_minute.bar(oos["display_label"], oos["minute_sharpe"], color=colors)
    style_ax(ax_minute, "OOS Minute Sharpe", "Variant", "Minute Sharpe")
    for bar, value in zip(bars, oos["minute_sharpe"]):
        ax_minute.text(bar.get_x() + bar.get_width() / 2, value + 0.015, f"{value:.3f}", ha="center", color=TEXT, fontsize=11, fontweight="bold")

    ax_daily = fig.add_subplot(grid[0, 1])
    bars = ax_daily.bar(oos["display_label"], oos["daily_sharpe"], color=colors)
    style_ax(ax_daily, "OOS Daily Sharpe", "Variant", "Daily Sharpe")
    for bar, value in zip(bars, oos["daily_sharpe"]):
        ax_daily.text(bar.get_x() + bar.get_width() / 2, value + 0.08, f"{value:.3f}", ha="center", color=TEXT, fontsize=11, fontweight="bold")

    ax_read = fig.add_subplot(grid[0, 2])
    ax_read.set_axis_off()
    ax_read.text(0.04, 0.86, "Selected OOS Read", fontsize=15, color=WHITE, fontweight="bold")
    rows = [
        ("Minute Sharpe", f"{selected_oos['minute_sharpe']:.3f}", GREEN),
        ("Daily Sharpe", f"{selected_oos['daily_sharpe']:.3f}", GREEN),
        ("PnL", f"{selected_oos['total_pnl_bps']:,.1f} bps", TEXT),
        ("Minute Delta", f"{minute_delta:+.3f}", GREEN if minute_delta >= 0 else RED),
        ("Dates", f"{selected_oos['start_date']} to\n{selected_oos['end_date']}", MUTED),
    ]
    y = 0.68
    for label, value, color in rows:
        ax_read.text(0.04, y, label, fontsize=11, color=MUTED)
        ax_read.text(0.96, y, value, fontsize=13, color=color, ha="right", fontweight="bold")
        y -= 0.135

    ax_train = fig.add_subplot(grid[1, :2])
    width = 0.36
    x = np.arange(len(train))
    ax_train.bar(x - width / 2, train["minute_sharpe"], width, color=CYAN, label="Train")
    ax_train.bar(x + width / 2, oos["minute_sharpe"], width, color=GREEN, label="OOS")
    ax_train.set_xticks(x)
    ax_train.set_xticklabels(train["display_label"])
    style_ax(ax_train, "Train vs OOS Minute Sharpe", "Variant", "Minute Sharpe")
    line_legend(ax_train, ncol=2, loc="upper right")

    ax_note = fig.add_subplot(grid[1, 2])
    ax_note.set_axis_off()
    ax_note.text(0.04, 0.80, "Interpretation", fontsize=15, color=WHITE, fontweight="bold")
    ax_note.text(0.05, 0.58, "Quality gate is best on train and remains positive OOS.", fontsize=11, color=TEXT)
    ax_note.text(0.05, 0.38, "This is a chronological sanity check, not a future unseen live test.", fontsize=11, color=MUTED)

    add_note(fig, "Generated from micro_alpha_validation_summary.csv. Raw quote files remain local and excluded from git.")
    save(fig, HFT_PLOTS / "hft_micro_alpha_validation.png")


def plot_hft_cumulative() -> None:
    fig, ax = plt.subplots(figsize=(15, 8))
    for symbol, color in SYMBOL_COLORS.items():
        for mode, linestyle in MODE_STYLES.items():
            daily = hft_daily(symbol, mode)
            ax.plot(
                daily["date"],
                daily["cumulative_pnl_bps"],
                color=color,
                linestyle=linestyle,
                linewidth=2.4,
                label=f"{symbol} {mode}",
            )
    style_ax(ax, "Cross-Symbol Cumulative PnL", "Session date", "Cumulative PnL (bps)")
    line_legend(ax, ncol=3, loc="upper left")
    add_note(fig, "Solid lines are full portfolio; dashed lines are market-making-only. Period: 2026-03-02 to 2026-05-12.")
    save(fig, HFT_PLOTS / "hft_cross_symbol_cumulative_pnl.png")


def plot_hft_daily_bars() -> None:
    fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True)
    fig.suptitle("HFT Session PnL By Date", x=0.01, y=0.995, ha="left", fontsize=22, color=WHITE, fontweight="bold")
    for ax, symbol in zip(axes, SYMBOL_COLORS):
        daily = hft_daily(symbol, "full")
        colors = np.where(daily["total_net_return_bps"] >= 0, GREEN, RED)
        ax.bar(daily["date"], daily["total_net_return_bps"], color=colors, width=0.75)
        ax.axhline(0.0, color=MUTED, linewidth=1.0)
        style_ax(ax, f"{symbol} Full Portfolio Daily PnL", "", "PnL (bps)")
        ax.text(
            0.99,
            0.88,
            f"Loss days: {(daily['total_net_return_bps'] < 0).sum()} / {len(daily)}",
            transform=ax.transAxes,
            ha="right",
            color=MUTED,
            fontsize=10,
        )
    legend_handles = [
        Line2D([0], [0], marker="s", color="none", markerfacecolor=GREEN, markersize=10, label="Positive session"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor=RED, markersize=10, label="Negative session"),
    ]
    axes[0].legend(handles=legend_handles, loc="upper left", frameon=True)
    add_note(fig, "Session PnL is measured in basis points from the simulator's open-window quote replay.")
    save(fig, HFT_PLOTS / "hft_daily_pnl_bars.png")


def plot_hft_stress() -> None:
    stress = pd.concat([hft_stress(symbol) for symbol in SYMBOL_COLORS], ignore_index=True)
    fig, axes = plt.subplots(2, 1, figsize=(15, 10), sharex=True)
    fig.suptitle("HFT Adverse-Selection Stress", x=0.01, y=0.995, ha="left", fontsize=22, color=WHITE, fontweight="bold")
    for symbol, color in SYMBOL_COLORS.items():
        for mode, linestyle in MODE_STYLES.items():
            subset = stress[(stress["symbol"] == symbol) & (stress["portfolio_mode"] == mode)]
            label = f"{symbol} {mode}"
            axes[0].plot(subset["adverse_selection_bps"], subset["mean_total_pnl_bps"], marker="o", linewidth=2.3, color=color, linestyle=linestyle, label=label)
            axes[1].plot(subset["adverse_selection_bps"], subset["mean_minute_sharpe"], marker="o", linewidth=2.3, color=color, linestyle=linestyle, label=label)
    axes[0].axhline(0.0, color=RED, linewidth=1.1)
    axes[1].axhline(0.0, color=RED, linewidth=1.1)
    style_ax(axes[0], "Mean Total PnL vs Adverse Selection", "", "Mean total PnL (bps)")
    style_ax(axes[1], "Mean Minute Sharpe vs Adverse Selection", "Penalty per completed trade (bps)", "Minute Sharpe")
    line_legend(axes[0], ncol=3, loc="upper right")
    add_note(fig, "This is the core HFT robustness chart: it shows where the spread-capture edge breaks.")
    save(fig, HFT_PLOTS / "hft_adverse_selection_stress.png")


def plot_hft_latency() -> None:
    latency = pd.concat([hft_latency(symbol) for symbol in SYMBOL_COLORS], ignore_index=True)
    fig, axes = plt.subplots(2, 1, figsize=(15, 10), sharex=True)
    fig.suptitle("HFT Signal-Latency Sensitivity", x=0.01, y=0.995, ha="left", fontsize=22, color=WHITE, fontweight="bold")
    x_values = sorted(latency["signal_latency_us"].unique())
    x_pos = np.arange(len(x_values))
    label_map = {value: f"{int(value):,} us" for value in x_values}
    for symbol, color in SYMBOL_COLORS.items():
        for mode, linestyle in MODE_STYLES.items():
            subset = latency[(latency["symbol"] == symbol) & (latency["portfolio_mode"] == mode)].sort_values("signal_latency_us")
            axes[0].plot(x_pos, subset["total_pnl_bps"], marker="o", linewidth=2.3, color=color, linestyle=linestyle, label=f"{symbol} {mode}")
        expired = latency[(latency["symbol"] == symbol) & (latency["portfolio_mode"] == "full")].sort_values("signal_latency_us")
        axes[1].plot(x_pos, expired["latency_expired_signals"], marker="o", linewidth=2.3, color=color, label=symbol)
    axes[0].axhline(0.0, color=RED, linewidth=1.1)
    axes[0].set_xticks(x_pos)
    axes[0].set_xticklabels([label_map[value] for value in x_values])
    axes[1].set_xticks(x_pos)
    axes[1].set_xticklabels([label_map[value] for value in x_values])
    style_ax(axes[0], "Total PnL Under Delayed Signals", "", "Total PnL (bps)")
    style_ax(axes[1], "Expired Signals Under Delayed Signals", "Signal latency", "Expired signals")
    line_legend(axes[0], ncol=3, loc="upper left")
    line_legend(axes[1], ncol=3, loc="upper left")
    add_note(fig, "Latency is modeled by delaying the strategy's quote access before decisions are processed.")
    save(fig, HFT_PLOTS / "hft_latency_sensitivity.png")
    shutil.copy2(HFT_PLOTS / "hft_latency_sensitivity.png", HFT_PLOTS / "latency_sensitivity.png")


def plot_hft_bootstrap_ci() -> None:
    ci = hft_evidence_ci()
    labels = [f"{row.symbol} {row.portfolio_mode}" for row in ci.itertuples()]
    y = np.arange(len(ci))
    fig, ax = plt.subplots(figsize=(13.5, 7))
    low = ci["avg_daily_pnl_bps"] - ci["avg_daily_pnl_ci95_low_bps"]
    high = ci["avg_daily_pnl_ci95_high_bps"] - ci["avg_daily_pnl_bps"]
    ax.errorbar(ci["avg_daily_pnl_bps"], y, xerr=[low, high], fmt="o", color=WHITE, ecolor=MUTED, capsize=5, linewidth=2)
    ax.scatter(ci["avg_daily_pnl_bps"], y, c=[SYMBOL_COLORS[row.symbol] for row in ci.itertuples()], s=70, zorder=3)
    for idx, row in enumerate(ci.itertuples()):
        ax.text(row.avg_daily_pnl_ci95_high_bps + 4, idx, f"{row.avg_daily_pnl_bps:.1f}", va="center", fontsize=10, color=TEXT)
    ax.axvline(0.0, color=RED, linewidth=1.1)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    style_ax(ax, "Bootstrap Confidence Intervals: Average Daily PnL", "Average daily PnL (bps)", "")
    add_note(fig, "Bootstrap intervals resample days and are descriptive uncertainty, not proof of future profitability.")
    save(fig, HFT_PLOTS / "hft_bootstrap_ci.png")


def plot_hft_drawdown() -> None:
    fig, ax = plt.subplots(figsize=(15, 8))
    for symbol, color in SYMBOL_COLORS.items():
        for mode, linestyle in MODE_STYLES.items():
            daily = hft_daily(symbol, mode)
            ax.plot(daily["date"], daily["drawdown_bps"], color=color, linestyle=linestyle, linewidth=2.2, label=f"{symbol} {mode}")
    ax.axhline(0.0, color=MUTED, linewidth=1.0)
    style_ax(ax, "Cumulative Session Drawdown Comparison", "Session date", "Drawdown from running peak (bps)")
    line_legend(ax, ncol=3, loc="lower left")
    add_note(fig, "Drawdown is computed from cumulative session PnL; intraday worst drawdown is retained separately in result summaries.")
    save(fig, HFT_PLOTS / "hft_drawdown_comparison.png")


def medium_metrics() -> pd.Series:
    return read_csv(MEDIUM_RESULTS / "selected_default_metrics.csv").iloc[0]


def medium_benchmark_metrics() -> tuple[pd.Series, pd.Series]:
    frame = read_csv(MEDIUM_RESULTS / "benchmark_comparison.csv")
    strategy = pd.Series(clean_num(frame["momentum_strategy"]).values, index=frame["metric"])
    benchmark = pd.Series(clean_num(frame["SPY"]).values, index=frame["metric"])
    return strategy, benchmark


def medium_selected_cost_sharpe(metrics: pd.Series, cost_bps: float) -> float:
    sensitivity = read_csv(MEDIUM_RESULTS / "sensitivity_results.csv")
    for col in ["top_quantile", "cost_bps", "annualized_sharpe"]:
        sensitivity[col] = clean_num(sensitivity[col])
    selected_quantile = float(metrics["top_quantile"])
    row = sensitivity[
        np.isclose(sensitivity["top_quantile"], selected_quantile)
        & np.isclose(sensitivity["cost_bps"], cost_bps)
    ]
    if row.empty:
        return float("nan")
    return float(row.iloc[0]["annualized_sharpe"])


def medium_capacity_sharpe(capital_scale: float) -> float:
    capacity = read_csv(MEDIUM_RESULTS / "capacity_simulation.csv")
    for col in ["capital_scale", "annualized_sharpe"]:
        capacity[col] = clean_num(capacity[col])
    row = capacity[np.isclose(capacity["capital_scale"], capital_scale)]
    if row.empty:
        return float("nan")
    return float(row.iloc[0]["annualized_sharpe"])


def medium_daily_sample() -> pd.DataFrame:
    frame = read_csv(MEDIUM_RESULTS / "daily_strategy_returns.csv")
    frame["date"] = pd.to_datetime(frame["date"])
    for col in ["net_strategy_return", "benchmark_return", "cumulative_net_return", "turnover", "trading_cost"]:
        frame[col] = clean_num(frame[col])
    frame["benchmark_equity"] = (1.0 + frame["benchmark_return"]).cumprod()
    frame["strategy_drawdown"] = frame["cumulative_net_return"] / frame["cumulative_net_return"].cummax() - 1.0
    frame["benchmark_drawdown"] = frame["benchmark_equity"] / frame["benchmark_equity"].cummax() - 1.0
    return frame


def medium_monthly() -> pd.DataFrame:
    frame = read_csv(MEDIUM_RESULTS / "monthly_results.csv")
    frame["date"] = pd.to_datetime(frame["date"])
    frame["strategy_monthly_return"] = clean_num(frame["strategy_monthly_return"])
    frame["strategy_equity"] = (1.0 + frame["strategy_monthly_return"]).cumprod()
    frame["strategy_drawdown"] = frame["strategy_equity"] / frame["strategy_equity"].cummax() - 1.0
    return frame


def add_medium_title(fig: plt.Figure, subtitle: str) -> None:
    fig.suptitle(
        "Medium-Term Alpha Evidence",
        x=0.01,
        y=0.995,
        ha="left",
        fontsize=23,
        color=WHITE,
        fontweight="bold",
    )
    fig.text(0.01, 0.955, subtitle, color=MUTED, ha="left", fontsize=11)


def plot_medium_dashboard() -> None:
    metrics = medium_metrics()
    strategy_metrics, benchmark_metrics = medium_benchmark_metrics()
    monthly = medium_monthly()
    wf = read_csv(MEDIUM_RESULTS / "walk_forward_results.csv")
    wf["test_year"] = pd.to_datetime(wf["test_start"]).dt.year.astype(str)
    wf["annualized_sharpe"] = clean_num(wf["annualized_sharpe"])
    cost_sharpe_10 = medium_selected_cost_sharpe(metrics, 10.0)
    capacity_sharpe_20x = medium_capacity_sharpe(20.0)

    fig = plt.figure(figsize=(17, 10))
    grid = fig.add_gridspec(2, 3)
    add_medium_title(fig, "Selected-default full evidence spans 2018-01-02 to 2026-05-06; point-in-time universe remains the key data gap.")

    ax_equity = fig.add_subplot(grid[:, 0])
    ax_equity.plot(monthly["date"], monthly["strategy_equity"], color=GREEN, linewidth=2.6, label="Selected strategy monthly equity")
    style_ax(ax_equity, "Full Selected Strategy Equity", "Date", "Growth of $1")
    line_legend(ax_equity, ncol=1)

    ax_metrics = fig.add_subplot(grid[0, 1])
    ax_metrics.set_axis_off()
    rows = [
        ("Strategy Sharpe", f"{float(metrics['annualized_sharpe']):.2f}"),
        ("SPY Sharpe", f"{float(metrics['benchmark_annualized_sharpe']):.2f}"),
        ("Strategy Total Return", format_pct(float(strategy_metrics["total_return"]))),
        ("SPY Total Return", format_pct(float(benchmark_metrics["total_return"]))),
        ("Return Spread", format_pp(float(strategy_metrics["total_return"] - benchmark_metrics["total_return"]))),
        ("Strategy Max DD", format_pct(float(strategy_metrics["max_drawdown"]))),
        ("10 bps Cost Sharpe", f"{cost_sharpe_10:.2f}"),
        ("20x Capacity Sharpe", f"{capacity_sharpe_20x:.2f}"),
    ]
    y = 0.86
    ax_metrics.text(0.04, 0.95, "Headline Metrics", transform=ax_metrics.transAxes, fontsize=16, fontweight="bold", color=WHITE)
    for label, value in rows:
        ax_metrics.text(0.06, y, label, transform=ax_metrics.transAxes, color=MUTED, fontsize=12)
        ax_metrics.text(0.92, y, value, transform=ax_metrics.transAxes, color=WHITE, fontsize=14, fontweight="bold", ha="right")
        y -= 0.095

    ax_wf = fig.add_subplot(grid[0, 2])
    colors = np.where(wf["annualized_sharpe"] >= 0, GREEN, RED)
    ax_wf.bar(wf["test_year"], wf["annualized_sharpe"], color=colors)
    ax_wf.axhline(0.0, color=MUTED, linewidth=1)
    style_ax(ax_wf, "Walk-Forward Test Sharpe", "Test year", "Annualized Sharpe")

    ax_notes = fig.add_subplot(grid[1, 1:])
    ax_notes.set_axis_off()
    notes = [
        ("Pass", "benchmark spread, bootstrap, negative control, costs, capacity", GREEN),
        ("Warn", "momentum dominance and sample-audit holdings files", AMBER),
        ("Fail", "point-in-time / delisting-aware universe not available", RED),
    ]
    ax_notes.text(0.03, 0.84, "Robustness Scorecard Read", fontsize=16, color=WHITE, fontweight="bold")
    y = 0.62
    for label, text, color in notes:
        ax_notes.text(0.05, y, label, fontsize=15, color=color, fontweight="bold")
        ax_notes.text(0.19, y, text, fontsize=12, color=TEXT)
        y -= 0.20

    add_note(fig, "Full selected metrics and monthly equity use saved full evidence; holdings/turnover charts are sample-audit artifacts.")
    save(fig, MEDIUM_PLOTS / "medium_term_alpha_report.png")


def plot_medium_equity_curve() -> None:
    monthly = medium_monthly()
    strategy_metrics, benchmark_metrics = medium_benchmark_metrics()
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.5), gridspec_kw={"width_ratios": [1.45, 1.0]})
    axes[0].plot(monthly["date"], monthly["strategy_equity"], color=GREEN, linewidth=2.6, label="Selected strategy monthly equity")
    axes[0].scatter(monthly["date"].iloc[-1], monthly["strategy_equity"].iloc[-1], color=GREEN, s=70, zorder=3)
    axes[0].text(
        monthly["date"].iloc[-1],
        monthly["strategy_equity"].iloc[-1],
        f"  {monthly['strategy_equity'].iloc[-1]:.2f}x",
        color=TEXT,
        va="center",
        fontsize=10,
    )
    style_ax(axes[0], "Full Selected Strategy Equity", "Date", "Growth of $1")
    line_legend(axes[0], ncol=1, loc="upper left")

    labels = ["Strategy", "SPY"]
    returns = [float(strategy_metrics["total_return"]) * 100, float(benchmark_metrics["total_return"]) * 100]
    bars = axes[1].bar(labels, returns, color=[GREEN, BLUE])
    style_ax(axes[1], "Full-Period Total Return", "Series", "Total return (%)")
    for bar, value in zip(bars, returns):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + 6, f"{value:.1f}%", ha="center", color=TEXT, fontsize=11, fontweight="bold")
    add_note(fig, "Strategy equity uses full monthly_results.csv. SPY path is not plotted because only full-period benchmark summary metrics are saved.")
    save(fig, MEDIUM_PLOTS / "cumulative_returns.png")


def plot_medium_drawdown() -> None:
    monthly = medium_monthly()
    strategy_metrics, benchmark_metrics = medium_benchmark_metrics()
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.5), gridspec_kw={"width_ratios": [1.45, 1.0]})
    axes[0].fill_between(monthly["date"], monthly["strategy_drawdown"] * 100, 0, color=GREEN, alpha=0.18)
    axes[0].plot(monthly["date"], monthly["strategy_drawdown"] * 100, color=GREEN, linewidth=2.4, label="Selected strategy monthly drawdown")
    axes[0].axhline(0.0, color=MUTED, linewidth=1)
    style_ax(axes[0], "Full Monthly Strategy Drawdown Path", "Date", "Month-end drawdown (%)")
    line_legend(axes[0], ncol=1, loc="lower left")

    labels = ["Strategy", "SPY"]
    drawdowns = [float(strategy_metrics["max_drawdown"]) * 100, float(benchmark_metrics["max_drawdown"]) * 100]
    bars = axes[1].bar(labels, drawdowns, color=[GREEN, BLUE])
    axes[1].axhline(0.0, color=MUTED, linewidth=1)
    style_ax(axes[1], "Saved Max Drawdown", "Series", "Max drawdown (%)")
    axes[1].set_ylim(min(drawdowns) * 1.08, 1.0)
    for bar, value in zip(bars, drawdowns):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2,
            value / 2.0,
            f"{value:.1f}%",
            ha="center",
            va="center",
            color=TEXT,
            fontsize=11,
            fontweight="bold",
        )
    add_note(fig, "Left path is month-end full evidence; right bars use saved full-period max drawdown metrics from benchmark_comparison.csv.")
    save(fig, MEDIUM_PLOTS / "drawdown.png")


def rolling_sharpe(returns: pd.Series, months: int) -> pd.Series:
    mean = returns.rolling(months).mean()
    vol = returns.rolling(months).std(ddof=0)
    return (mean / vol) * math.sqrt(12)


def plot_medium_rolling_sharpe() -> None:
    monthly = medium_monthly()
    monthly["rolling_sharpe_6m"] = rolling_sharpe(monthly["strategy_monthly_return"], 6)
    monthly["rolling_sharpe_12m"] = rolling_sharpe(monthly["strategy_monthly_return"], 12)
    fig, ax = plt.subplots(figsize=(15, 7.5))
    ax.plot(monthly["date"], monthly["rolling_sharpe_6m"], color=CYAN, linewidth=2.1, label="6-month rolling Sharpe")
    ax.plot(monthly["date"], monthly["rolling_sharpe_12m"], color=PINK, linewidth=2.1, label="12-month rolling Sharpe")
    ax.axhline(0.0, color=MUTED, linewidth=1)
    style_ax(ax, "Rolling Sharpe From Full Monthly Evidence", "Date", "Annualized Sharpe")
    line_legend(ax, ncol=1, loc="upper left")
    add_note(fig, "Computed from saved monthly_results.csv; early windows are omitted until enough months are available.")
    save(fig, MEDIUM_PLOTS / "rolling_sharpe.png")


def plot_medium_walk_forward() -> None:
    wf = read_csv(MEDIUM_RESULTS / "walk_forward_results.csv")
    wf["test_year"] = pd.to_datetime(wf["test_start"]).dt.year.astype(str)
    for col in ["annualized_sharpe", "annualized_return", "max_drawdown"]:
        wf[col] = clean_num(wf[col])
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    colors = np.where(wf["annualized_sharpe"] >= 0, GREEN, RED)
    axes[0].bar(wf["test_year"], wf["annualized_sharpe"], color=colors)
    axes[0].axhline(0.0, color=MUTED, linewidth=1)
    style_ax(axes[0], "Walk-Forward Annualized Sharpe", "", "Sharpe")
    axes[1].bar(wf["test_year"], wf["annualized_return"] * 100, color=np.where(wf["annualized_return"] >= 0, GREEN, RED))
    axes[1].axhline(0.0, color=MUTED, linewidth=1)
    style_ax(axes[1], "Walk-Forward Annualized Return", "Test year", "Return (%)")
    add_note(fig, "Walk-forward tests are expanding-window test years; 2026 is a partial year ending 2026-05-06.")
    save(fig, MEDIUM_PLOTS / "walk_forward_yearly_performance.png")


def plot_medium_annual_returns() -> None:
    monthly = medium_monthly()
    monthly["year"] = monthly["date"].dt.year
    annual = monthly.groupby("year")["strategy_monthly_return"].apply(lambda values: (1.0 + values).prod() - 1.0)
    fig, ax = plt.subplots(figsize=(14, 7.5))
    colors = np.where(annual.values >= 0, GREEN, RED)
    bars = ax.bar(annual.index.astype(str), annual.values * 100, color=colors)
    ax.axhline(0.0, color=MUTED, linewidth=1.0)
    style_ax(ax, "Calendar-Year Strategy Returns From Monthly Evidence", "Year", "Return (%)")
    for bar, value in zip(bars, annual.values * 100):
        label_y = value + 1.2 if value >= 0 else value / 2.0
        va = "bottom" if value >= 0 else "center"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            label_y,
            f"{value:.1f}%",
            ha="center",
            va=va,
            color=TEXT,
            fontsize=10,
            fontweight="bold",
        )
    add_note(fig, "Aggregated from monthly_results.csv. 2018 starts after the strategy warm-up; 2026 is partial through 2026-05-06.")
    save(fig, MEDIUM_PLOTS / "annual_returns.png")


def plot_medium_cost_capacity() -> None:
    capacity = read_csv(MEDIUM_RESULTS / "capacity_simulation.csv")
    sensitivity = read_csv(MEDIUM_RESULTS / "sensitivity_results.csv")
    for col in ["capital_scale", "effective_cost_bps", "annualized_sharpe", "total_return"]:
        capacity[col] = clean_num(capacity[col])
    for col in ["top_quantile", "cost_bps", "annualized_sharpe"]:
        sensitivity[col] = clean_num(sensitivity[col])

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    axes[0].plot(capacity["capital_scale"], capacity["annualized_sharpe"], marker="o", color=CYAN, linewidth=2.4, label="Sharpe")
    axes[0].set_xscale("log")
    axes[0].axhline(1.0, color=AMBER, linestyle="--", linewidth=1.2, label="Sharpe 1.0")
    style_ax(axes[0], "Capacity Proxy: Sharpe vs Capital Scale", "Capital scale", "Annualized Sharpe")
    line_legend(axes[0], ncol=1)

    pivot = sensitivity.pivot_table(index="top_quantile", columns="cost_bps", values="annualized_sharpe")
    image = axes[1].imshow(pivot.values, cmap="viridis", aspect="auto", vmin=float(np.nanmin(pivot.values)), vmax=float(np.nanmax(pivot.values)))
    axes[1].set_xticks(np.arange(len(pivot.columns)))
    axes[1].set_xticklabels([f"{col:g}" for col in pivot.columns])
    axes[1].set_yticks(np.arange(len(pivot.index)))
    axes[1].set_yticklabels([f"{idx:.2f}" for idx in pivot.index])
    style_ax(axes[1], "Local Sensitivity: Sharpe Heatmap", "Cost (bps)", "Top quantile")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            axes[1].text(j, i, f"{pivot.values[i, j]:.2f}", ha="center", va="center", color=WHITE, fontsize=9)
    cbar = fig.colorbar(image, ax=axes[1], fraction=0.046, pad=0.03)
    cbar.set_label("Annualized Sharpe", color=TEXT)
    cbar.ax.yaxis.set_tick_params(color=MUTED)
    plt.setp(cbar.ax.get_yticklabels(), color=MUTED)
    add_note(fig, "Capacity is modeled as higher effective trading cost, not full market impact or liquidity simulation.")
    save(fig, MEDIUM_PLOTS / "cost_capacity_sensitivity.png")


def plot_medium_bootstrap_negative_control() -> None:
    boot = read_csv(MEDIUM_RESULTS / "medium_alpha_bootstrap_ci.csv")
    neg = read_csv(MEDIUM_RESULTS / "medium_alpha_negative_controls.csv").iloc[0]
    sharpe = boot[boot["metric"] == "annualized_sharpe"].iloc[0]
    observed = float(sharpe["observed"])
    low = float(sharpe["ci95_low"])
    high = float(sharpe["ci95_high"])
    control_p95 = float(neg["control_p95_annualized_sharpe"])
    control_mean = float(neg["control_mean_annualized_sharpe"])

    fig, ax = plt.subplots(figsize=(12, 6.8))
    ax.errorbar([observed], [1], xerr=[[observed - low], [high - observed]], fmt="o", color=GREEN, ecolor=MUTED, capsize=6, linewidth=2.5, label="Observed bootstrap 95% CI")
    ax.scatter([control_mean], [0], color=BLUE, s=90, label="Sign-flip control mean")
    ax.scatter([control_p95], [0], color=AMBER, s=90, label="Sign-flip control p95")
    ax.axvline(0.0, color=MUTED, linewidth=1)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Negative control", "Observed strategy"])
    style_ax(ax, "Monthly Bootstrap Sharpe vs Sign-Flip Negative Control", "Annualized Sharpe", "")
    line_legend(ax, ncol=1, loc="lower right")
    ax.text(observed, 1.12, f"Observed {observed:.2f}", ha="center", color=TEXT)
    ax.text(control_p95, 0.13, f"Control p95 {control_p95:.2f}", ha="center", color=TEXT)
    add_note(fig, "Uses monthly_results.csv; observed monthly Sharpe can differ from the daily headline Sharpe in selected_default_metrics.csv.")
    save(fig, MEDIUM_PLOTS / "bootstrap_negative_control.png")


def plot_medium_turnover_concentration() -> None:
    rebalance = read_csv(MEDIUM_RESULTS / "rebalance_log.csv")
    rebalance["rebalance_date"] = pd.to_datetime(rebalance["rebalance_date"])
    for col in ["turnover", "number_of_positions", "estimated_trading_cost", "gross_exposure"]:
        rebalance[col] = clean_num(rebalance[col])

    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
    axes[0].bar(rebalance["rebalance_date"], rebalance["turnover"] * 100, color=CYAN, width=18, label="Turnover")
    style_ax(axes[0], "Sample Audit Turnover By Rebalance", "", "Turnover (%)")
    axes[1].plot(rebalance["rebalance_date"], rebalance["number_of_positions"], color=GREEN, marker="o", linewidth=2.1, label="Number of positions")
    axes[1].plot(rebalance["rebalance_date"], rebalance["gross_exposure"] * 100, color=AMBER, marker="o", linewidth=2.1, label="Gross exposure (%)")
    style_ax(axes[1], "Sample Audit Holdings Concentration", "Rebalance date", "Positions / Exposure")
    line_legend(axes[1], ncol=2, loc="upper left")
    add_note(fig, "Uses committed sample-audit holdings files; full selected-default holdings require a pinned full price panel.")
    save(fig, MEDIUM_PLOTS / "turnover_holdings_concentration.png")
    shutil.copy2(MEDIUM_PLOTS / "turnover_holdings_concentration.png", MEDIUM_PLOTS / "turnover_costs.png")
    shutil.copy2(MEDIUM_PLOTS / "turnover_holdings_concentration.png", MEDIUM_PLOTS / "holdings_concentration.png")


def plot_medium_factor_diagnostics() -> None:
    metrics = medium_metrics()
    behavior = read_csv(MEDIUM_RESULTS / "factor_behavior_summary.csv").set_index("metric")["value"].astype(float)
    weights = pd.Series(
        {
            "Momentum": float(metrics["multi_momentum_weight"]),
            "Mean reversion": float(metrics["mean_reversion_weight"]),
            "Quality": float(metrics["quality_weight"]),
        }
    )
    dominance = pd.Series(
        {
            "Momentum dominance": behavior.get("momentum_dominance_share", np.nan),
            "Low-vol dominance": behavior.get("low_volatility_dominance_share", np.nan),
            "Strong divergence": behavior.get("strong_divergence_share", np.nan),
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))
    axes[0].bar(weights.index, weights.values, color=[CYAN, PURPLE, GREEN])
    style_ax(axes[0], "Selected Signal Blend Weights", "Signal component", "Weight")
    axes[1].bar(dominance.index, dominance.values, color=[AMBER, BLUE, RED])
    axes[1].set_ylim(0, 1.05)
    style_ax(axes[1], "Saved Factor Behavior Diagnostics", "Diagnostic", "Share")
    for ax in axes:
        ax.tick_params(axis="x", rotation=15)
    add_note(fig, "Momentum dominance is an explicit limitation: the selected run should not be sold as a diversified multi-factor edge.")
    save(fig, MEDIUM_PLOTS / "factor_diagnostics.png")
    shutil.copy2(MEDIUM_PLOTS / "factor_diagnostics.png", MEDIUM_PLOTS / "factor_or_diagnostics_summary.png")


def generate_hft_plots() -> None:
    plot_hft_dashboard()
    plot_hft_micro_alpha_quality()
    plot_hft_micro_alpha_validation()
    plot_hft_cumulative()
    plot_hft_daily_bars()
    plot_hft_stress()
    plot_hft_latency()
    plot_hft_bootstrap_ci()
    plot_hft_drawdown()


def generate_medium_plots() -> None:
    plot_medium_dashboard()
    plot_medium_equity_curve()
    plot_medium_drawdown()
    plot_medium_rolling_sharpe()
    plot_medium_walk_forward()
    plot_medium_annual_returns()
    plot_medium_cost_capacity()
    plot_medium_bootstrap_negative_control()
    plot_medium_turnover_concentration()
    plot_medium_factor_diagnostics()


def main() -> int:
    ensure_dirs()
    generate_hft_plots()
    generate_medium_plots()
    print(f"saved_hft_plots={HFT_PLOTS}")
    print(f"saved_medium_plots={MEDIUM_PLOTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

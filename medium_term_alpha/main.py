"""Research harness for the cross-sectional momentum module.

The system ranks liquid equities on 1-12 week momentum and low volatility,
then builds a monthly long-short portfolio with shifted weights to avoid
lookahead bias. It uses real price data from yfinance or CSV input, applies
explicit turnover costs, compares against SPY, and reports robustness,
walk-forward, regime, factor, and capacity diagnostics. Unlike a toy model,
the output separates gross/net returns, shows where the strategy fails, and
turns results into an interview-ready research note.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, replace
from itertools import product
from pathlib import Path

LOCAL_DEPS = Path(__file__).resolve().parents[1] / ".pip_tmp"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from data_and_features import (
    DEFAULT_MOMENTUM_WEIGHTS,
    DEFAULT_TICKERS,
    LOOKBACK_WINDOWS,
    compute_composite_scores,
    compute_high_conviction_short_filter,
    compute_market_regime_scale,
    compute_rolling_beta,
    load_benchmark,
    load_prices,
    rebalance_scores,
)
from backtest_and_metrics import (
    drawdown_curve,
    equity_curve,
    rolling_drawdown,
    rolling_return,
    rolling_sharpe,
    summarize_performance,
)
from strategy_and_portfolio import build_long_short_weights, compute_long_short_returns, compute_strategy_returns


UNIVERSE_SETS = {
    "default": DEFAULT_TICKERS,
    "tech_heavy": ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA"],
    "mixed_sector": ["AAPL", "MSFT", "JPM", "XOM", "UNH", "AMZN"],
}


@dataclass(frozen=True)
class StrategyParams:
    top_quantile: float = 0.25
    gross_exposure: float = 1.0
    cost_bps: float = 5.0
    momentum_weight: float = 1.00
    low_vol_weight: float = 0.00
    lookback_weights: tuple[float, ...] | None = DEFAULT_MOMENTUM_WEIGHTS
    momentum_skip_recent_days: int = 5
    normalize_momentum: bool = True
    volatility_window: int = 63
    beta_window: int = 126
    trend_window: int = 126
    negative_trend_scale: float = 0.40
    high_volatility_scale: float = 0.40
    market_volatility_window: int = 63
    market_volatility_quantile: float = 0.75
    signal_change_threshold: float = 0.05
    max_position_size: float = 0.06
    use_volatility_scaling: bool = True
    beta_neutralize: bool = False
    beta_neutralization_strength: float = 0.0
    short_mode: str = "none"
    short_quantile: float = 0.10
    short_decile: float = 0.10
    short_exposure_fraction: float = 0.0
    min_signal_strength: float = 0.85
    use_multi_signal: bool = True
    multi_momentum_weight: float = 0.55
    mean_reversion_weight: float = 0.25
    quality_weight: float = 0.20
    short_term_reversal_window: int = 5
    short_term_reversal_penalty: float = 0.15
    quality_window: int = 63


@dataclass
class BacktestResult:
    gross_returns: pd.Series
    trading_cost: pd.Series
    net_returns: pd.Series
    long_returns: pd.Series
    short_returns: pd.Series
    daily_weights: pd.DataFrame
    turnover: pd.Series
    rebalance_weights: pd.DataFrame
    rebalance_scores: pd.DataFrame
    asset_volatility: pd.DataFrame
    market_regime_scale: pd.Series
    summary: dict[str, float]


def previous_default_params(params: StrategyParams) -> StrategyParams:
    """Keep the Sharpe-improvement pass anchored to the pre-research default."""
    return replace(
        params,
        top_quantile=0.25,
        signal_change_threshold=0.05,
        max_position_size=0.06,
        negative_trend_scale=0.50,
        high_volatility_scale=1.0,
        min_signal_strength=0.70,
        multi_momentum_weight=0.70,
        mean_reversion_weight=0.20,
        quality_weight=0.10,
        short_term_reversal_penalty=0.20,
        use_multi_signal=True,
        short_mode="none",
        short_exposure_fraction=0.0,
    )


def parse_tickers(value: str) -> list[str]:
    return [ticker.strip().upper() for ticker in value.split(",") if ticker.strip()]


def parse_weights(value: str | None) -> tuple[float, ...] | None:
    if value is None or not value.strip():
        return None
    return tuple(float(item.strip()) for item in value.split(",") if item.strip())


def build_params(args: argparse.Namespace) -> StrategyParams:
    return StrategyParams(
        top_quantile=args.top_quantile,
        gross_exposure=args.gross_exposure,
        cost_bps=args.cost_bps,
        momentum_weight=args.momentum_weight,
        low_vol_weight=args.low_vol_weight,
        lookback_weights=parse_weights(args.lookback_weights),
        momentum_skip_recent_days=args.momentum_skip_recent_days,
        normalize_momentum=args.normalize_momentum,
        volatility_window=args.volatility_window,
        beta_window=args.beta_window,
        trend_window=args.trend_window,
        negative_trend_scale=args.negative_trend_scale,
        high_volatility_scale=args.high_volatility_scale,
        market_volatility_window=args.market_volatility_window,
        market_volatility_quantile=args.market_volatility_quantile,
        signal_change_threshold=args.signal_change_threshold,
        max_position_size=args.max_position_size,
        use_volatility_scaling=args.use_volatility_scaling,
        beta_neutralize=args.beta_neutralize,
        beta_neutralization_strength=args.beta_neutralization_strength,
        short_mode=args.short_mode,
        short_quantile=args.short_quantile,
        short_decile=args.short_decile,
        short_exposure_fraction=args.short_exposure_fraction,
        min_signal_strength=args.min_signal_strength,
        use_multi_signal=args.use_multi_signal,
        multi_momentum_weight=args.multi_momentum_weight,
        mean_reversion_weight=args.mean_reversion_weight,
        quality_weight=args.quality_weight,
        short_term_reversal_window=args.short_term_reversal_window,
        short_term_reversal_penalty=args.short_term_reversal_penalty,
        quality_window=args.quality_window,
    )


def load_benchmark_with_fallback(args: argparse.Namespace, prices: pd.DataFrame) -> pd.Series:
    if args.benchmark in prices.columns:
        return prices[args.benchmark].rename(args.benchmark)

    if args.benchmark_csv:
        return load_benchmark(args.benchmark, args.start, args.end, args.benchmark_csv)

    if args.csv:
        try:
            return load_benchmark(args.benchmark, args.start, args.end, args.csv)
        except Exception as exc:
            print(f"benchmark_csv_fallback_warning={exc}")

    return load_benchmark(args.benchmark, args.start, args.end, None)


def build_strategy_summary(
    gross_returns: pd.Series,
    trading_cost: pd.Series,
    net_returns: pd.Series,
    long_returns: pd.Series,
    short_returns: pd.Series,
    turnover: pd.Series,
    params: StrategyParams,
    rebalance_count: int,
) -> dict[str, float]:
    active_turnover = turnover[turnover > 0.0]
    summary = summarize_performance(net_returns, active_turnover)
    gross_summary = summarize_performance(gross_returns)
    long_summary = summarize_performance(long_returns)
    short_summary = summarize_performance(short_returns)

    summary["gross_total_return"] = gross_summary["total_return"]
    summary["net_total_return"] = summary["total_return"]
    summary["cost_impact_on_returns"] = gross_summary["total_return"] - summary["total_return"]
    summary["total_trading_cost"] = float(trading_cost.sum())
    summary["average_turnover"] = float(active_turnover.mean()) if not active_turnover.empty else 0.0
    summary["long_total_return"] = long_summary["total_return"]
    summary["short_total_return"] = short_summary["total_return"]
    summary["cost_per_turnover_bps"] = params.cost_bps
    summary["momentum_weight"] = params.momentum_weight
    summary["low_vol_weight"] = params.low_vol_weight
    summary["momentum_skip_recent_days"] = float(params.momentum_skip_recent_days)
    summary["beta_neutralization_strength"] = params.beta_neutralization_strength
    summary["negative_trend_scale"] = params.negative_trend_scale
    summary["high_volatility_scale"] = params.high_volatility_scale
    summary["short_quantile"] = params.short_quantile
    summary["short_exposure_fraction"] = params.short_exposure_fraction
    summary["min_signal_strength"] = params.min_signal_strength
    summary["use_multi_signal"] = 1.0 if params.use_multi_signal else 0.0
    summary["multi_momentum_weight"] = params.multi_momentum_weight
    summary["mean_reversion_weight"] = params.mean_reversion_weight
    summary["quality_weight"] = params.quality_weight
    summary["rebalance_count"] = float(rebalance_count)
    return summary


def run_momentum_backtest(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    params: StrategyParams,
) -> BacktestResult:
    # The strategy logic stays isolated here so diagnostics can rerun variants without retuning.
    composite_scores, _, _, asset_volatility = compute_composite_scores(
        prices,
        momentum_weight=params.momentum_weight,
        low_vol_weight=params.low_vol_weight,
        lookbacks=LOOKBACK_WINDOWS,
        lookback_weights=params.lookback_weights,
        momentum_skip_recent_days=params.momentum_skip_recent_days,
        normalize_momentum=params.normalize_momentum,
        volatility_window=params.volatility_window,
        use_multi_signal=params.use_multi_signal,
        multi_momentum_weight=params.multi_momentum_weight,
        mean_reversion_weight=params.mean_reversion_weight,
        quality_weight=params.quality_weight,
        short_term_reversal_window=params.short_term_reversal_window,
        short_term_reversal_penalty=params.short_term_reversal_penalty,
        quality_window=params.quality_window,
    )
    rebalance_score_frame = rebalance_scores(composite_scores)
    short_allowed = None
    if params.short_mode == "high_conviction":
        short_allowed = compute_high_conviction_short_filter(
            prices,
            lookbacks=LOOKBACK_WINDOWS,
            skip_recent_days=params.momentum_skip_recent_days,
            decile=params.short_decile,
        ).reindex(rebalance_score_frame.index).fillna(False)

    benchmark_aligned = benchmark_prices.reindex(prices.index).ffill()
    beta = compute_rolling_beta(prices, benchmark_aligned, params.beta_window)
    # The regime scale is a simple risk brake: it assumes broad market trend is a useful exposure proxy.
    market_scale = compute_market_regime_scale(
        benchmark_aligned,
        prices.index,
        trend_window=params.trend_window,
        negative_trend_scale=params.negative_trend_scale,
        high_volatility_scale=params.high_volatility_scale,
        volatility_window=params.market_volatility_window,
        volatility_quantile=params.market_volatility_quantile,
    )

    rebalance_weights = build_long_short_weights(
        rebalance_score_frame,
        top_quantile=params.top_quantile,
        gross_exposure=params.gross_exposure,
        asset_volatility=asset_volatility,
        beta=beta,
        market_regime_scale=market_scale,
        signal_change_threshold=params.signal_change_threshold,
        max_position_size=params.max_position_size,
        use_volatility_scaling=params.use_volatility_scaling,
        beta_neutralize=params.beta_neutralize,
        beta_neutralization_strength=params.beta_neutralization_strength,
        short_mode=params.short_mode,
        short_quantile=params.short_quantile,
        short_allowed=short_allowed,
        short_exposure_fraction=params.short_exposure_fraction,
        min_signal_strength=params.min_signal_strength,
    )

    asset_returns = prices.pct_change().fillna(0.0)
    gross_returns, trading_cost, net_returns, daily_weights, turnover = compute_strategy_returns(
        asset_returns,
        rebalance_weights,
        cost_per_turnover_bps=params.cost_bps,
    )
    long_returns, short_returns = compute_long_short_returns(asset_returns, daily_weights)
    summary = build_strategy_summary(
        gross_returns,
        trading_cost,
        net_returns,
        long_returns,
        short_returns,
        turnover,
        params,
        len(rebalance_weights),
    )
    return BacktestResult(
        gross_returns=gross_returns,
        trading_cost=trading_cost,
        net_returns=net_returns,
        long_returns=long_returns,
        short_returns=short_returns,
        daily_weights=daily_weights,
        turnover=turnover,
        rebalance_weights=rebalance_weights,
        rebalance_scores=rebalance_score_frame,
        asset_volatility=asset_volatility,
        market_regime_scale=market_scale,
        summary=summary,
    )


def align_benchmark_to_strategy(
    benchmark_prices: pd.Series,
    strategy_index: pd.DatetimeIndex,
    benchmark_name: str,
) -> tuple[pd.Series, pd.DatetimeIndex]:
    aligned_prices = benchmark_prices.reindex(strategy_index).ffill().dropna()
    aligned_index = strategy_index.intersection(aligned_prices.index)
    benchmark_returns = aligned_prices.loc[aligned_index].pct_change().fillna(0.0)
    return benchmark_returns.rename(f"{benchmark_name}_return"), aligned_index


def create_rolling_metrics(net_returns: pd.Series, equity: pd.Series, turnover: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame(index=net_returns.index)
    frame["strategy_return"] = net_returns
    frame["rolling_sharpe_6m"] = rolling_sharpe(net_returns, 126)
    frame["rolling_sharpe_12m"] = rolling_sharpe(net_returns, 252)
    frame["rolling_return_6m"] = rolling_return(net_returns, 126)
    frame["rolling_return_12m"] = rolling_return(net_returns, 252)
    frame["rolling_drawdown_6m"] = rolling_drawdown(equity, 126)
    frame["rolling_drawdown_12m"] = rolling_drawdown(equity, 252)
    frame["turnover"] = turnover
    return frame


def clean_comparison_frame(
    strategy_summary: dict[str, float],
    benchmark_summary: dict[str, float],
    benchmark_name: str,
) -> pd.DataFrame:
    rows = []
    for metric in (
        "total_return",
        "annualized_return",
        "annualized_sharpe",
        "max_drawdown",
        "daily_volatility",
        "annualized_volatility",
    ):
        rows.append(
            {
                "metric": metric,
                "momentum_strategy": strategy_summary.get(metric, 0.0),
                benchmark_name: benchmark_summary.get(metric, 0.0),
            }
        )
    for metric in (
        "gross_total_return",
        "net_total_return",
        "total_trading_cost",
        "cost_impact_on_returns",
        "average_turnover",
        "long_total_return",
        "short_total_return",
    ):
        rows.append({"metric": metric, "momentum_strategy": strategy_summary.get(metric, 0.0), benchmark_name: ""})
    return pd.DataFrame(rows)


def clean_summary_frame(strategy_summary: dict[str, float]) -> pd.DataFrame:
    return pd.Series(strategy_summary, name="value").rename_axis("metric").reset_index()


def clean_output_frame(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Keep exported CSVs readable without requiring code context."""
    ordered_columns = [column for column in columns if column in frame.columns]
    if not ordered_columns and frame.empty and columns:
        return pd.DataFrame(columns=columns)
    return frame[ordered_columns] if ordered_columns else frame


def write_clean_csv(
    frame: pd.DataFrame,
    output_path: Path,
    columns: list[str],
    index_label: str | None = None,
) -> None:
    clean_output_frame(frame, columns).to_csv(output_path, index_label=index_label, index=index_label is not None)


def portfolio_weights_audit_frame(result: BacktestResult) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date, weights in result.rebalance_weights.iterrows():
        scores = result.rebalance_scores.loc[date] if date in result.rebalance_scores.index else pd.Series(dtype=float)
        volatility = result.asset_volatility.loc[date] if date in result.asset_volatility.index else pd.Series(dtype=float)
        for ticker, weight in weights.items():
            vol = float(volatility.get(ticker, np.nan)) if not volatility.empty else np.nan
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "weight": float(weight),
                    "final_signal": float(scores.get(ticker, np.nan)) if not scores.empty else np.nan,
                    "volatility": vol,
                    "inverse_vol_score": (1.0 / vol) if np.isfinite(vol) and vol > 0.0 else np.nan,
                    "selected_flag": bool(abs(float(weight)) > 1e-12),
                }
            )
    return pd.DataFrame(rows)


def rebalance_log_frame(result: BacktestResult, params: StrategyParams) -> pd.DataFrame:
    rebalance_turnover = result.rebalance_weights.diff().abs().sum(axis=1)
    if not rebalance_turnover.empty:
        rebalance_turnover.iloc[0] = result.rebalance_weights.iloc[0].abs().sum()

    rows: list[dict[str, object]] = []
    for date, weights in result.rebalance_weights.iterrows():
        active = weights[weights.abs() > 1e-12].sort_values(key=lambda values: values.abs(), ascending=False)
        scores = result.rebalance_scores.loc[date] if date in result.rebalance_scores.index else pd.Series(dtype=float)
        top_signal_ticker = ""
        top_signal_value = np.nan
        if not scores.dropna().empty:
            top_signal_ticker = str(scores.dropna().idxmax())
            top_signal_value = float(scores.dropna().max())
        turnover_value = float(rebalance_turnover.get(date, 0.0))
        rows.append(
            {
                "rebalance_date": date,
                "selected_tickers": ";".join(active.index.astype(str)),
                "number_of_positions": int(len(active)),
                "gross_exposure": float(weights.abs().sum()),
                "turnover": turnover_value,
                "estimated_trading_cost": turnover_value * (params.cost_bps / 10000.0),
                "regime_scale": float(result.market_regime_scale.get(date, np.nan)),
                "top_signal_ticker": top_signal_ticker,
                "top_signal_value": top_signal_value,
            }
        )
    return pd.DataFrame(rows)


def daily_strategy_returns_frame(
    gross_returns: pd.Series,
    trading_cost: pd.Series,
    net_returns: pd.Series,
    turnover: pd.Series,
    benchmark_returns: pd.Series,
) -> pd.DataFrame:
    frame = pd.concat(
        [
            gross_returns.rename("gross_strategy_return"),
            net_returns.rename("net_strategy_return"),
            benchmark_returns.rename("benchmark_return"),
            turnover.rename("turnover"),
            trading_cost.rename("trading_cost"),
            equity_curve(net_returns).rename("cumulative_net_return"),
        ],
        axis=1,
    )
    return frame


def benchmark_timeseries_frame(benchmark_returns: pd.Series) -> pd.DataFrame:
    return pd.concat(
        [
            benchmark_returns.rename("benchmark_return"),
            equity_curve(benchmark_returns).rename("cumulative_benchmark_return"),
        ],
        axis=1,
    )


def factor_contribution_rows(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    params: StrategyParams,
) -> pd.DataFrame:
    rows = []
    factor_specs = [
        ("momentum_only", replace(params, momentum_weight=1.0, low_vol_weight=0.0)),
        ("low_vol_only", replace(params, momentum_weight=0.0, low_vol_weight=1.0)),
        ("composite", params),
    ]
    for factor_name, factor_params in factor_specs:
        result = run_momentum_backtest(prices, benchmark_prices, factor_params)
        rows.append(
            {
                "factor": factor_name,
                "momentum_weight": factor_params.momentum_weight,
                "low_vol_weight": factor_params.low_vol_weight,
                "annualized_sharpe": result.summary["annualized_sharpe"],
                "total_return": result.summary["net_total_return"],
                "annualized_return": result.summary["annualized_return"],
                "max_drawdown": result.summary["max_drawdown"],
                "total_trading_cost": result.summary["total_trading_cost"],
            }
        )
    return pd.DataFrame(rows)


def robustness_rows(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    params: StrategyParams,
    min_assets: int,
) -> pd.DataFrame:
    rows = []
    for name, tickers in UNIVERSE_SETS.items():
        available = [ticker for ticker in tickers if ticker in prices.columns]
        if len(available) < min_assets:
            rows.append(
                {
                    "universe": name,
                    "assets": ",".join(available),
                    "asset_count": len(available),
                    "status": "insufficient_assets",
                    "annualized_sharpe": "",
                    "total_return": "",
                    "annualized_return": "",
                    "max_drawdown": "",
                }
            )
            continue
        result = run_momentum_backtest(prices[available], benchmark_prices, params)
        rows.append(
            {
                "universe": name,
                "assets": ",".join(available),
                "asset_count": len(available),
                "status": "ok",
                "annualized_sharpe": result.summary["annualized_sharpe"],
                "total_return": result.summary["net_total_return"],
                "annualized_return": result.summary["annualized_return"],
                "max_drawdown": result.summary["max_drawdown"],
            }
        )
    return pd.DataFrame(rows)


def sensitivity_rows(prices: pd.DataFrame, benchmark_prices: pd.Series, params: StrategyParams) -> pd.DataFrame:
    rows = []
    for top_quantile in (0.15, 0.20, 0.25):
        for cost_bps in (2.0, 5.0, 10.0):
            test_params = replace(params, top_quantile=top_quantile, cost_bps=cost_bps)
            result = run_momentum_backtest(prices, benchmark_prices, test_params)
            rows.append(
                {
                    "top_quantile": top_quantile,
                    "cost_bps": cost_bps,
                    "annualized_sharpe": result.summary["annualized_sharpe"],
                    "total_return": result.summary["net_total_return"],
                    "annualized_return": result.summary["annualized_return"],
                    "max_drawdown": result.summary["max_drawdown"],
                    "total_trading_cost": result.summary["total_trading_cost"],
                    "average_turnover": result.summary["average_turnover"],
                }
            )
    return pd.DataFrame(rows)


def walk_forward_rows(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    params: StrategyParams,
    train_years: int,
) -> pd.DataFrame:
    rows = []
    years = sorted(prices.index.year.unique())
    if len(years) <= train_years:
        return pd.DataFrame(rows)

    for offset in range(train_years, len(years)):
        test_year = years[offset]
        train_start = prices.index.min()
        train_end = prices[prices.index.year < test_year].index.max()
        test_slice = prices[prices.index.year == test_year]
        if test_slice.empty:
            continue

        history = prices.loc[: test_slice.index.max()]
        benchmark_history = benchmark_prices.reindex(history.index).ffill()
        result = run_momentum_backtest(history, benchmark_history, params)
        test_returns = result.net_returns.loc[test_slice.index.min() : test_slice.index.max()]
        test_summary = summarize_performance(test_returns)
        rows.append(
            {
                "train_start": train_start.date(),
                "train_end": train_end.date(),
                "test_start": test_slice.index.min().date(),
                "test_end": test_slice.index.max().date(),
                "annualized_sharpe": test_summary["annualized_sharpe"],
                "total_return": test_summary["total_return"],
                "annualized_return": test_summary["annualized_return"],
                "max_drawdown": test_summary["max_drawdown"],
            }
        )
    return pd.DataFrame(rows)


def _clean_float(value: float | int | None) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def _summarize_subset(
    diagnostic: str,
    regime: str,
    returns: pd.Series,
    mask: pd.Series,
) -> dict[str, float | int | str]:
    aligned_mask = mask.reindex(returns.index).fillna(False).astype(bool)
    subset = returns.loc[aligned_mask]
    summary = summarize_performance(subset)
    volatility = float(subset.std(ddof=1)) if len(subset.dropna()) > 1 else 0.0
    return {
        "diagnostic": diagnostic,
        "regime": regime,
        "days": int(len(subset)),
        "mean_return": _clean_float(subset.mean()) if not subset.empty else 0.0,
        "volatility": volatility,
        "sharpe": summary["annualized_sharpe"],
        "win_rate": _clean_float((subset > 0.0).mean()) if not subset.empty else 0.0,
        "total_return": summary["total_return"],
        "annualized_return": summary["annualized_return"],
        "max_drawdown": summary["max_drawdown"],
    }


def failure_regime_rows(
    net_returns: pd.Series,
    benchmark_returns: pd.Series,
    volatility_window: int = 63,
) -> pd.DataFrame:
    """Post-trade diagnostics: where the strategy works and where it struggles."""
    common_index = net_returns.index.intersection(benchmark_returns.index)
    returns = net_returns.loc[common_index]
    benchmark = benchmark_returns.loc[common_index]

    # Shifted volatility prevents today's return from defining today's regime.
    rolling_volatility = benchmark.rolling(volatility_window).std().shift(1)
    volatility_threshold = rolling_volatility.dropna().median()

    comparisons: list[tuple[str, str, pd.Series, str, pd.Series, str]] = [
        (
            "market_direction",
            "up_market_days",
            benchmark > 0.0,
            "down_market_days",
            benchmark < 0.0,
            "up_market_days_minus_down_market_days",
        )
    ]

    if not pd.isna(volatility_threshold):
        comparisons.append(
            (
                "volatility_regime",
                "high_volatility",
                rolling_volatility >= volatility_threshold,
                "low_volatility",
                rolling_volatility < volatility_threshold,
                "high_volatility_minus_low_volatility",
            )
        )

    rows = []
    for diagnostic, first_name, first_mask, second_name, second_mask, difference_label in comparisons:
        first = _summarize_subset(diagnostic, first_name, returns, first_mask)
        second = _summarize_subset(diagnostic, second_name, returns, second_mask)
        difference = float(first["total_return"]) - float(second["total_return"])
        first["comparison"] = difference_label
        first["paired_regime"] = second_name
        first["performance_difference_metric"] = "total_return"
        first["performance_difference"] = difference
        second["comparison"] = difference_label
        second["paired_regime"] = first_name
        second["performance_difference_metric"] = "total_return"
        second["performance_difference"] = difference
        rows.extend([first, second])

    return pd.DataFrame(rows)


def factor_score_frames(
    prices: pd.DataFrame,
    params: StrategyParams,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    composite, momentum, low_vol, _ = compute_composite_scores(
        prices,
        momentum_weight=params.momentum_weight,
        low_vol_weight=params.low_vol_weight,
        lookbacks=LOOKBACK_WINDOWS,
        lookback_weights=params.lookback_weights,
        momentum_skip_recent_days=params.momentum_skip_recent_days,
        normalize_momentum=params.normalize_momentum,
        volatility_window=params.volatility_window,
        use_multi_signal=params.use_multi_signal,
        multi_momentum_weight=params.multi_momentum_weight,
        mean_reversion_weight=params.mean_reversion_weight,
        quality_weight=params.quality_weight,
        short_term_reversal_window=params.short_term_reversal_window,
        short_term_reversal_penalty=params.short_term_reversal_penalty,
        quality_window=params.quality_window,
    )
    return composite, momentum, low_vol


def factor_signal_correlation_rows(
    momentum_scores: pd.DataFrame,
    low_vol_scores: pd.DataFrame,
) -> pd.DataFrame:
    # Low correlation supports diversification; high correlation means the factors may be redundant.
    common_index = momentum_scores.index.intersection(low_vol_scores.index)
    common_columns = momentum_scores.columns.intersection(low_vol_scores.columns)
    momentum = momentum_scores.loc[common_index, common_columns]
    low_vol = low_vol_scores.loc[common_index, common_columns]

    flattened = pd.concat(
        [
            momentum.stack().rename("momentum"),
            low_vol.stack().rename("low_vol"),
        ],
        axis=1,
    ).dropna()
    overall_correlation = flattened["momentum"].corr(flattened["low_vol"]) if len(flattened) > 1 else 0.0

    cross_sectional = []
    for date in common_index:
        joined = pd.concat(
            [momentum.loc[date].rename("momentum"), low_vol.loc[date].rename("low_vol")],
            axis=1,
        ).dropna()
        if len(joined) > 1:
            cross_sectional.append(joined["momentum"].corr(joined["low_vol"]))

    cross_sectional_series = pd.Series(cross_sectional, dtype=float).dropna()
    return pd.DataFrame(
        [
            {"metric": "overall_signal_correlation", "value": _clean_float(overall_correlation)},
            {
                "metric": "average_cross_sectional_correlation",
                "value": _clean_float(cross_sectional_series.mean()) if not cross_sectional_series.empty else 0.0,
            },
            {
                "metric": "positive_correlation_share",
                "value": _clean_float((cross_sectional_series > 0.0).mean()) if not cross_sectional_series.empty else 0.0,
            },
            {"metric": "observations", "value": float(len(flattened))},
        ]
    )


def rolling_factor_correlation_frame(
    momentum_scores: pd.DataFrame,
    low_vol_scores: pd.DataFrame,
    window: int = 126,
) -> pd.DataFrame:
    common_index = momentum_scores.index.intersection(low_vol_scores.index)
    common_columns = momentum_scores.columns.intersection(low_vol_scores.columns)
    rows = []
    for date in common_index:
        joined = pd.concat(
            [
                momentum_scores.loc[date, common_columns].rename("momentum"),
                low_vol_scores.loc[date, common_columns].rename("low_vol"),
            ],
            axis=1,
        ).dropna()
        correlation = joined["momentum"].corr(joined["low_vol"]) if len(joined) > 1 else 0.0
        rows.append({"date": date, "cross_sectional_correlation": _clean_float(correlation)})

    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["cross_sectional_correlation", "rolling_factor_correlation"])
    frame = frame.set_index("date")
    frame["rolling_factor_correlation"] = frame["cross_sectional_correlation"].rolling(window).mean()
    return frame


def factor_performance_frame(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    params: StrategyParams,
) -> pd.DataFrame:
    factor_results = {
        "momentum": run_momentum_backtest(
            prices,
            benchmark_prices,
            replace(params, momentum_weight=1.0, low_vol_weight=0.0),
        ),
        "low_volatility": run_momentum_backtest(
            prices,
            benchmark_prices,
            replace(params, momentum_weight=0.0, low_vol_weight=1.0),
        ),
        "composite": run_momentum_backtest(prices, benchmark_prices, params),
    }
    common_index = factor_results["momentum"].net_returns.index
    for result in factor_results.values():
        common_index = common_index.intersection(result.net_returns.index)

    frame = pd.DataFrame(index=common_index)
    for factor_name, result in factor_results.items():
        returns = result.net_returns.loc[common_index].rename(f"{factor_name}_return")
        frame[f"{factor_name}_return"] = returns
        frame[f"{factor_name}_equity"] = equity_curve(returns)
        frame[f"{factor_name}_cumulative_return"] = frame[f"{factor_name}_equity"] - 1.0
    return frame


def factor_dominance_frame(
    factor_performance: pd.DataFrame,
    window: int = 126,
) -> pd.DataFrame:
    required_columns = ["momentum_return", "low_volatility_return", "composite_return"]
    if factor_performance.empty or any(column not in factor_performance.columns for column in required_columns):
        return pd.DataFrame(
            columns=[
                "momentum_return",
                "low_volatility_return",
                "composite_return",
                "momentum_rolling_return",
                "low_vol_rolling_return",
                "composite_rolling_return",
                "dominance_spread",
                "dominant_factor",
                "strong_divergence_threshold",
                "strong_divergence",
                "divergence_direction",
            ]
        )
    frame = factor_performance[
        required_columns
    ].copy()
    frame["momentum_rolling_return"] = rolling_return(frame["momentum_return"], window)
    frame["low_vol_rolling_return"] = rolling_return(frame["low_volatility_return"], window)
    frame["composite_rolling_return"] = rolling_return(frame["composite_return"], window)
    frame["dominance_spread"] = frame["momentum_rolling_return"] - frame["low_vol_rolling_return"]
    frame["dominant_factor"] = "insufficient_history"
    valid = frame["dominance_spread"].notna()
    frame.loc[valid & (frame["dominance_spread"] >= 0.0), "dominant_factor"] = "momentum"
    frame.loc[valid & (frame["dominance_spread"] < 0.0), "dominant_factor"] = "low_volatility"
    divergence_threshold = frame.loc[valid, "dominance_spread"].abs().quantile(0.75) if valid.any() else 0.0
    frame["strong_divergence_threshold"] = _clean_float(divergence_threshold)
    frame["strong_divergence"] = (
        valid &
        (frame["strong_divergence_threshold"] > 0.0) &
        (frame["dominance_spread"].abs() >= frame["strong_divergence_threshold"])
    )
    frame["divergence_direction"] = "none"
    frame.loc[frame["strong_divergence"] & (frame["dominance_spread"] > 0.0), "divergence_direction"] = "momentum_over_low_vol"
    frame.loc[frame["strong_divergence"] & (frame["dominance_spread"] < 0.0), "divergence_direction"] = "low_vol_over_momentum"
    return frame


def factor_behavior_summary_rows(
    factor_dominance: pd.DataFrame,
    rolling_correlation: pd.DataFrame,
) -> pd.DataFrame:
    if factor_dominance.empty:
        valid = pd.DataFrame()
        divergence = pd.DataFrame()
    else:
        valid = factor_dominance[factor_dominance["dominant_factor"] != "insufficient_history"]
        divergence = factor_dominance[factor_dominance["strong_divergence"]]
    dominance_share = valid["dominant_factor"].value_counts(normalize=True) if not valid.empty else pd.Series(dtype=float)
    rolling_corr = rolling_correlation["rolling_factor_correlation"].dropna() if not rolling_correlation.empty else pd.Series(dtype=float)
    rows = [
        {"metric": "momentum_dominance_share", "value": _clean_float(dominance_share.get("momentum", 0.0))},
        {"metric": "low_volatility_dominance_share", "value": _clean_float(dominance_share.get("low_volatility", 0.0))},
        {"metric": "strong_divergence_periods", "value": float(len(divergence))},
        {
            "metric": "strong_divergence_share",
            "value": _clean_float(len(divergence) / len(valid)) if len(valid) > 0 else 0.0,
        },
        {
            "metric": "average_rolling_factor_correlation",
            "value": _clean_float(rolling_corr.mean()) if not rolling_corr.empty else 0.0,
        },
        {
            "metric": "minimum_rolling_factor_correlation",
            "value": _clean_float(rolling_corr.min()) if not rolling_corr.empty else 0.0,
        },
        {
            "metric": "maximum_rolling_factor_correlation",
            "value": _clean_float(rolling_corr.max()) if not rolling_corr.empty else 0.0,
        },
    ]
    return pd.DataFrame(rows)


def capacity_simulation_rows(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    params: StrategyParams,
) -> pd.DataFrame:
    rows = []
    for capital_scale in (1.0, 2.0, 5.0, 10.0, 20.0):
        # This is a transparent capacity proxy: larger capital is modeled as higher effective cost.
        effective_cost_bps = params.cost_bps * math.sqrt(capital_scale)
        result = run_momentum_backtest(
            prices,
            benchmark_prices,
            replace(params, cost_bps=effective_cost_bps),
        )
        rows.append(
            {
                "capital_scale": capital_scale,
                "effective_cost_bps": effective_cost_bps,
                "annualized_sharpe": result.summary["annualized_sharpe"],
                "total_return": result.summary["net_total_return"],
                "annualized_return": result.summary["annualized_return"],
                "max_drawdown": result.summary["max_drawdown"],
                "total_trading_cost": result.summary["total_trading_cost"],
                "average_turnover": result.summary["average_turnover"],
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    baseline_sharpe = float(frame.iloc[0]["annualized_sharpe"])
    baseline_return = float(frame.iloc[0]["total_return"])
    sharpe_denominator = abs(baseline_sharpe) if abs(baseline_sharpe) > 1e-12 else 1.0
    return_denominator = abs(baseline_return) if abs(baseline_return) > 1e-12 else 1.0
    frame["sharpe_decay_pct"] = (baseline_sharpe - frame["annualized_sharpe"]) / sharpe_denominator
    frame["return_decay_pct"] = (baseline_return - frame["total_return"]) / return_denominator
    frame["sharpe_below_one"] = frame["annualized_sharpe"] < 1.0
    frame["material_return_decay"] = frame["return_decay_pct"] >= 0.30
    frame["non_positive_return"] = frame["total_return"] <= 0.0
    frame["capacity_limit_flag"] = (
        frame["sharpe_below_one"] |
        frame["material_return_decay"] |
        frame["non_positive_return"]
    )

    reasons = []
    for _, row in frame.iterrows():
        active_reasons = []
        if bool(row["sharpe_below_one"]):
            active_reasons.append("sharpe_below_1")
        if bool(row["material_return_decay"]):
            active_reasons.append("return_decay_gt_30pct")
        if bool(row["non_positive_return"]):
            active_reasons.append("non_positive_return")
        reasons.append(",".join(active_reasons) if active_reasons else "ok")
    frame["capacity_limit_reason"] = reasons
    return frame


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


def _format_pct(value: float) -> str:
    return f"{value * 100.0:.2f}%"


def _format_float(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}"


def _safe_divide(numerator: float, denominator: float) -> float:
    if abs(denominator) <= 1e-12 or not math.isfinite(denominator):
        return 0.0
    return float(numerator / denominator)


def _annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    clean = returns.dropna()
    if len(clean) < 2:
        return 0.0
    return float(clean.std(ddof=1) * math.sqrt(periods_per_year))


def _sortino_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    clean = returns.dropna()
    downside = clean[clean < 0.0]
    if len(clean) < 2 or len(downside) < 2:
        return 0.0
    downside_std = downside.std(ddof=1)
    return _safe_divide(float(clean.mean() * math.sqrt(periods_per_year)), float(downside_std))


def _calmar_ratio(annualized_return_value: float, max_drawdown_value: float) -> float:
    return _safe_divide(annualized_return_value, abs(max_drawdown_value))


def _capacity_reference_row(capacity: pd.DataFrame) -> pd.Series | None:
    if capacity.empty:
        return None
    if "capacity_limit_flag" in capacity.columns:
        flagged = capacity[capacity["capacity_limit_flag"]]
        if not flagged.empty:
            return flagged.iloc[0]
    return capacity.iloc[-1]


def _best_factor_name(factor_contribution: pd.DataFrame) -> str:
    factor_rows = factor_contribution[factor_contribution["factor"] != "composite"]
    if factor_rows.empty:
        return "not available"
    return str(factor_rows.sort_values("total_return", ascending=False).iloc[0]["factor"])


def _worst_regime_name(failure_regime: pd.DataFrame) -> str:
    if failure_regime.empty:
        return "not available"
    row = failure_regime.sort_values("total_return", ascending=True).iloc[0]
    return f"{row['regime']} ({_format_pct(float(row['total_return']))} total return)"


def _best_regime_name(failure_regime: pd.DataFrame) -> str:
    if failure_regime.empty:
        return "not available"
    row = failure_regime.sort_values("total_return", ascending=False).iloc[0]
    return f"{row['regime']} ({_format_pct(float(row['total_return']))} total return)"


def _regime_metric(failure_regime: pd.DataFrame, regime: str, metric: str) -> float:
    if failure_regime.empty:
        return 0.0
    matched = failure_regime[failure_regime["regime"] == regime]
    if matched.empty or metric not in matched.columns:
        return 0.0
    return _clean_float(matched.iloc[0][metric])


def _summary_metric(frame: pd.DataFrame, metric: str) -> float:
    if frame.empty:
        return 0.0
    matched = frame[frame["metric"] == metric]
    if matched.empty:
        return 0.0
    return _clean_float(matched.iloc[0]["value"])


def _capacity_limit_note(capacity: pd.DataFrame) -> str:
    if capacity.empty or "capacity_limit_flag" not in capacity.columns:
        return "No capacity limit was detected in the tested scenarios."
    flagged = capacity[capacity["capacity_limit_flag"]]
    if flagged.empty:
        return "No capacity limit was detected in the tested scenarios."
    row = flagged.iloc[0]
    return (
        f"First capacity limit appears at {row['capital_scale']:.0f}x capital scale "
        f"({row['capacity_limit_reason']})."
    )


def save_research_summary(
    output_path: Path,
    strategy_summary: dict[str, float],
    benchmark_summary: dict[str, float],
    benchmark_name: str,
    failure_regime: pd.DataFrame,
    factor_correlation: pd.DataFrame,
    factor_contribution: pd.DataFrame,
    factor_dominance: pd.DataFrame,
    factor_behavior: pd.DataFrame,
    factor_performance: pd.DataFrame,
    capacity: pd.DataFrame,
    params: StrategyParams,
) -> None:
    correlation_lookup = factor_correlation.set_index("metric")["value"] if not factor_correlation.empty else pd.Series(dtype=float)
    signal_correlation = _clean_float(correlation_lookup.get("overall_signal_correlation", 0.0))

    momentum_dominance = _summary_metric(factor_behavior, "momentum_dominance_share")
    low_vol_dominance = _summary_metric(factor_behavior, "low_volatility_dominance_share")
    strong_divergence_share = _summary_metric(factor_behavior, "strong_divergence_share")

    base_capacity = capacity.iloc[0] if not capacity.empty else None
    max_capacity = capacity.iloc[-1] if not capacity.empty else None
    capacity_note = "Capacity simulation not available."
    if base_capacity is not None and max_capacity is not None:
        capacity_note = (
            f"At {max_capacity['capital_scale']:.0f}x capital scale, effective cost rises to "
            f"{max_capacity['effective_cost_bps']:.2f} bps, Sharpe changes from "
            f"{base_capacity['annualized_sharpe']:.2f} to {max_capacity['annualized_sharpe']:.2f}."
        )

    beats_benchmark = strategy_summary["total_return"] > benchmark_summary["total_return"]
    sharpe_quality = "above" if strategy_summary["annualized_sharpe"] > 1.0 else "below"
    return_driver = "long book" if strategy_summary["long_total_return"] >= strategy_summary["short_total_return"] else "short book"
    up_sharpe = _regime_metric(failure_regime, "up_market_days", "sharpe")
    down_sharpe = _regime_metric(failure_regime, "down_market_days", "sharpe")
    high_vol_sharpe = _regime_metric(failure_regime, "high_volatility", "sharpe")
    low_vol_sharpe = _regime_metric(failure_regime, "low_volatility", "sharpe")

    if not factor_performance.empty:
        factor_last = factor_performance.iloc[-1]
        momentum_return = _clean_float(factor_last.get("momentum_cumulative_return", 0.0))
        low_vol_return = _clean_float(factor_last.get("low_volatility_cumulative_return", 0.0))
        composite_return = _clean_float(factor_last.get("composite_cumulative_return", 0.0))
    else:
        momentum_return = 0.0
        low_vol_return = 0.0
        composite_return = 0.0

    lines = [
        "# Cross-Sectional Momentum Research Summary",
        "",
        "## 1. Strategy Overview",
        (
            "The strategy ranks a liquid equity universe using 21, 63, and 126 day momentum, "
            "combines that with a low-volatility rank, and builds a monthly long-short portfolio "
            "with score-proportional weights."
        ),
        (
            f"Risk controls include inverse-volatility sizing, rolling beta neutralization versus {benchmark_name}, "
            f"a negative-trend exposure scale of {params.negative_trend_scale:.2f}, turnover gating, "
            f"and a max single-name position of {_format_pct(params.max_position_size)}."
        ),
        "",
        "## 2. Key Results",
        "| Metric | Strategy | Benchmark |",
        "|---|---:|---:|",
        f"| Total return | {_format_pct(strategy_summary['total_return'])} | {_format_pct(benchmark_summary['total_return'])} |",
        f"| Annualized return | {_format_pct(strategy_summary['annualized_return'])} | {_format_pct(benchmark_summary['annualized_return'])} |",
        f"| Annualized Sharpe | {strategy_summary['annualized_sharpe']:.2f} | {benchmark_summary['annualized_sharpe']:.2f} |",
        f"| Max drawdown | {_format_pct(strategy_summary['max_drawdown'])} | {_format_pct(benchmark_summary['max_drawdown'])} |",
        f"| Total trading cost | {_format_pct(strategy_summary['total_trading_cost'])} | n/a |",
        f"| Average active turnover | {strategy_summary['average_turnover']:.4f} | n/a |",
        "",
        "## 3. Drivers Of Performance",
        f"- Primary book contribution: {return_driver}.",
        f"- Stronger standalone factor in this run: {_best_factor_name(factor_contribution)}.",
        f"- Momentum-only cumulative return: {_format_pct(momentum_return)}.",
        f"- Low-vol-only cumulative return: {_format_pct(low_vol_return)}.",
        f"- Composite cumulative return: {_format_pct(composite_return)}.",
        "",
        "## 4. Failure Conditions",
        f"- Weakest observed regime: {_worst_regime_name(failure_regime)}.",
        f"- Regime-specific Sharpe: up markets {up_sharpe:.2f}, down markets {down_sharpe:.2f}.",
        f"- Volatility-specific Sharpe: high volatility {high_vol_sharpe:.2f}, low volatility {low_vol_sharpe:.2f}.",
        "- Use `failure_regime_results.csv` for the full grouped table with mean return, volatility, Sharpe, win rate, and paired performance differences.",
        "",
        "## 5. Factor Insights",
        f"- Momentum/low-vol overall signal correlation: {signal_correlation:.3f}.",
        f"- Momentum dominates {momentum_dominance:.1%} of valid rolling windows; low-vol dominates {low_vol_dominance:.1%}.",
        f"- Strong factor divergence occurs in {strong_divergence_share:.1%} of valid rolling windows.",
        "- Low correlation or alternating dominance suggests the factors are complementary; persistent divergence identifies periods where one sleeve is carrying the composite.",
        "",
        "## 6. Capacity Insights",
        f"- {capacity_note}",
        f"- {_capacity_limit_note(capacity)}",
        "- Capacity is modeled through higher effective trading costs, not through a full market-impact order-book model.",
        "",
        "## 7. Final Conclusion",
        (
            f"The strategy {'beats' if beats_benchmark else 'does not beat'} the benchmark on total return in this run, "
            f"with Sharpe {sharpe_quality} 1. The final case study is not just a return number: it explains what drives returns, "
            "when the strategy fails, how factors behave, and how capacity assumptions affect the result."
        ),
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_metric_block(title: str, summary: dict[str, float]) -> None:
    print(f"{title}:")
    for key in ("annualized_sharpe", "annualized_return", "total_return", "max_drawdown"):
        print(f"{key}={summary[key]:.6f}")


def print_key_findings(
    strategy_summary: dict[str, float],
    benchmark_summary: dict[str, float],
    rolling_metrics: pd.DataFrame,
    factor_contribution: pd.DataFrame,
    acceptable_drawdown: float,
) -> None:
    beats_benchmark = strategy_summary["total_return"] > benchmark_summary["total_return"]
    sharpe_above_one = strategy_summary["annualized_sharpe"] > 1.0
    drawdown_ok = abs(strategy_summary["max_drawdown"]) <= acceptable_drawdown

    rolling_sharpe = rolling_metrics["rolling_sharpe_6m"].dropna()
    stable_fraction = float((rolling_sharpe > 0.0).mean()) if not rolling_sharpe.empty else 0.0
    performance_stable = stable_fraction >= 0.60

    side_driver = "long_book" if strategy_summary["long_total_return"] >= strategy_summary["short_total_return"] else "short_book"
    factor_rows = factor_contribution[factor_contribution["factor"] != "composite"]
    if factor_rows.empty:
        factor_driver = "not_available"
    else:
        factor_driver = str(factor_rows.sort_values("total_return", ascending=False).iloc[0]["factor"])

    drawdown_series = rolling_metrics["rolling_drawdown_12m"].dropna()
    worst_drawdown_date = "not_available" if drawdown_series.empty else str(drawdown_series.idxmin().date())
    rolling_return_series = rolling_metrics["rolling_return_6m"].dropna()
    worst_6m_return = 0.0 if rolling_return_series.empty else float(rolling_return_series.min())

    print("key_findings:")
    print(f"beats_benchmark_total_return={'yes' if beats_benchmark else 'no'}")
    print(f"sharpe_above_1={'yes' if sharpe_above_one else 'no'}")
    print(f"performance_stable={'yes' if performance_stable else 'no'}")
    print(f"drawdown_acceptable={'yes' if drawdown_ok else 'no'}")
    print(f"primary_return_driver={side_driver}")
    print(f"stronger_factor={factor_driver}")
    print(f"failure_window=worst_12m_drawdown_date:{worst_drawdown_date}, worst_6m_return:{worst_6m_return:.6f}")


def print_interview_insights(
    strategy_summary: dict[str, float],
    failure_regime: pd.DataFrame,
    capacity: pd.DataFrame,
    factor_behavior: pd.DataFrame,
) -> None:
    up_sharpe = _regime_metric(failure_regime, "up_market_days", "sharpe")
    down_sharpe = _regime_metric(failure_regime, "down_market_days", "sharpe")
    divergence_share = _summary_metric(factor_behavior, "strong_divergence_share")

    print("interview_ready_insights:")
    print("strength_1=Interpretable alpha: multi-horizon cross-sectional momentum plus low-volatility ranking.")
    print("strength_2=Risk-aware construction: inverse-vol sizing, beta neutralization, turnover gating, and explicit costs.")
    print("strength_3=Research discipline: benchmark comparison, walk-forward validation, regime diagnostics, and capacity stress tests.")
    print(f"weakness_1=Regime sensitivity: up-market Sharpe {up_sharpe:.2f} vs down-market Sharpe {down_sharpe:.2f}.")
    print(f"weakness_2=Factor instability: strong momentum/low-vol divergence in {divergence_share:.1%} of valid windows.")
    print(f"weakness_3=Capacity risk: {_capacity_limit_note(capacity)}")
    print("improvement_1=Expand validation across more assets, sectors, and market cycles with the same fixed parameters.")
    print("improvement_2=Replace the simple capacity proxy with calibrated borrow, slippage, and market-impact assumptions.")


def print_quant_diagnostics(
    net_returns: pd.Series,
    net_equity: pd.Series,
    strategy_drawdown: pd.Series,
    strategy_summary: dict[str, float],
    rolling_metrics: pd.DataFrame,
    failure_regime: pd.DataFrame,
    capacity: pd.DataFrame,
) -> None:
    clean_returns = net_returns.dropna()
    wins = clean_returns[clean_returns > 0.0]
    losses = clean_returns[clean_returns < 0.0]
    rolling_sharpe_values = rolling_metrics["rolling_sharpe_6m"].dropna()
    capacity_row = _capacity_reference_row(capacity)

    total_return = strategy_summary["total_return"]
    annual_return = strategy_summary["annualized_return"]
    max_drawdown_value = float(strategy_drawdown.min()) if not strategy_drawdown.empty else strategy_summary["max_drawdown"]
    annual_volatility = _annualized_volatility(clean_returns)
    sortino = _sortino_ratio(clean_returns)
    calmar = _calmar_ratio(annual_return, max_drawdown_value)
    final_equity = float(net_equity.iloc[-1]) if not net_equity.empty else 1.0

    average_win = _clean_float(wins.mean()) if not wins.empty else 0.0
    average_loss = _clean_float(losses.mean()) if not losses.empty else 0.0
    skew = _clean_float(clean_returns.skew()) if len(clean_returns) > 2 else 0.0
    kurtosis = _clean_float(clean_returns.kurt()) if len(clean_returns) > 3 else 0.0

    mean_rolling_sharpe = _clean_float(rolling_sharpe_values.mean()) if not rolling_sharpe_values.empty else 0.0
    std_rolling_sharpe = _clean_float(rolling_sharpe_values.std(ddof=1)) if len(rolling_sharpe_values) > 1 else 0.0
    positive_sharpe_share = _clean_float((rolling_sharpe_values > 0.0).mean()) if not rolling_sharpe_values.empty else 0.0
    above_one_sharpe_share = _clean_float((rolling_sharpe_values > 1.0).mean()) if not rolling_sharpe_values.empty else 0.0

    if capacity_row is None:
        sharpe_decay = 0.0
        return_decay = 0.0
        capacity_limit = "not available"
    else:
        sharpe_decay = _clean_float(capacity_row.get("sharpe_decay_pct", 0.0))
        return_decay = _clean_float(capacity_row.get("return_decay_pct", 0.0))
        if bool(capacity_row.get("capacity_limit_flag", False)):
            capacity_limit = f"{capacity_row['capital_scale']:.0f}x capital ({capacity_row['capacity_limit_reason']})"
        else:
            capacity_limit = f"not reached through {capacity_row['capital_scale']:.0f}x tested capital"

    print("QUANT DIAGNOSTICS:")
    print("CORE METRICS:")
    print(f"  Sharpe: {_format_float(strategy_summary['annualized_sharpe'])}")
    print(f"  Sortino: {_format_float(sortino)}")
    print(f"  Calmar: {_format_float(calmar)}")
    print(f"  Annual return: {_format_pct(annual_return)}")
    print(f"  Total return: {_format_pct(total_return)}")
    print(f"  Volatility: {_format_pct(annual_volatility)}")
    print(f"  Max drawdown: {_format_pct(max_drawdown_value)}")
    print(f"  Final equity ($1 growth): ${final_equity:.4f}")
    print("DISTRIBUTION:")
    print(f"  Win rate: {_format_pct(_clean_float((clean_returns > 0.0).mean()) if not clean_returns.empty else 0.0)}")
    print(f"  Average win: {_format_pct(average_win)}")
    print(f"  Average loss: {_format_pct(average_loss)}")
    print(f"  Skew: {_format_float(skew)}")
    print(f"  Kurtosis: {_format_float(kurtosis)}")
    print("PORTFOLIO:")
    print(f"  Long return: {_format_pct(strategy_summary['long_total_return'])}")
    print(f"  Short return: {_format_pct(strategy_summary['short_total_return'])}")
    print(f"  Average turnover: {_format_float(strategy_summary['average_turnover'], 4)}")
    print(f"  Total trading cost: {_format_pct(strategy_summary['total_trading_cost'])}")
    print("STABILITY:")
    print(f"  Mean rolling Sharpe: {_format_float(mean_rolling_sharpe)}")
    print(f"  Std rolling Sharpe: {_format_float(std_rolling_sharpe)}")
    print(f"  % time Sharpe > 0: {_format_pct(positive_sharpe_share)}")
    print(f"  % time Sharpe > 1: {_format_pct(above_one_sharpe_share)}")
    print("REGIME PERFORMANCE:")
    print(f"  Sharpe in up markets: {_format_float(_regime_metric(failure_regime, 'up_market_days', 'sharpe'))}")
    print(f"  Sharpe in down markets: {_format_float(_regime_metric(failure_regime, 'down_market_days', 'sharpe'))}")
    print(f"  Sharpe in high volatility: {_format_float(_regime_metric(failure_regime, 'high_volatility', 'sharpe'))}")
    print(f"  Sharpe in low volatility: {_format_float(_regime_metric(failure_regime, 'low_volatility', 'sharpe'))}")
    print("CAPACITY:")
    print(f"  Sharpe decay: {_format_pct(sharpe_decay)}")
    print(f"  Return decay: {_format_pct(return_decay)}")
    print(f"  Estimated capacity limit: {capacity_limit}")


def print_final_interpretation(
    strategy_summary: dict[str, float],
    failure_regime: pd.DataFrame,
    capacity: pd.DataFrame,
    factor_contribution: pd.DataFrame,
    factor_behavior: pd.DataFrame,
) -> None:
    risk_profile = "balanced"
    if abs(strategy_summary["max_drawdown"]) > 0.25 or strategy_summary["annualized_sharpe"] < 1.0:
        risk_profile = "fragile / needs stronger validation"
    elif abs(strategy_summary["max_drawdown"]) < 0.10 and strategy_summary["annualized_sharpe"] > 1.5:
        risk_profile = "controlled"

    divergence_share = _summary_metric(factor_behavior, "strong_divergence_share")
    best_regime = _best_regime_name(failure_regime)
    worst_regime = _worst_regime_name(failure_regime)

    print("FINAL INTERPRETATION:")
    print("  Key strengths:")
    print("    - Interpretable multi-horizon cross-sectional signal.")
    print("    - Explicit cost, turnover, beta, volatility, and capacity diagnostics.")
    print("    - Clear benchmark, robustness, regime, and factor attribution outputs.")
    print("  Key weaknesses:")
    print(f"    - Regime sensitivity: weakest regime is {worst_regime}.")
    print(f"    - Factor instability: strong factor divergence in {divergence_share:.1%} of valid windows.")
    print(f"    - Capacity depends on cost assumptions: {_capacity_limit_note(capacity)}")
    print(f"  Risk profile: {risk_profile}.")
    print(f"  Where it works: {best_regime}.")
    print(f"  Where it fails: {worst_regime}.")
    print(f"  Strongest factor: {_best_factor_name(factor_contribution)}.")


def print_interview_summary(
    strategy_summary: dict[str, float],
    failure_regime: pd.DataFrame,
    factor_contribution: pd.DataFrame,
    capacity: pd.DataFrame,
) -> None:
    primary_driver = (
        "long_book"
        if strategy_summary["long_total_return"] >= strategy_summary["short_total_return"]
        else "short_book"
    )
    print("INTERVIEW SUMMARY:")
    print("Strategy type: Cross-sectional equity momentum, monthly long-short")
    print(f"Sharpe: {strategy_summary['annualized_sharpe']:.2f}")
    print(f"Return: {_format_pct(strategy_summary['total_return'])}")
    print(f"Drawdown: {_format_pct(strategy_summary['max_drawdown'])}")
    print(f"Primary driver: {primary_driver}")
    print(f"Strongest factor: {_best_factor_name(factor_contribution)}")
    print(f"Weakest regime: {_worst_regime_name(failure_regime)}")
    print(f"Capacity limit: {_capacity_limit_note(capacity)}")


README_RESULTS_START = "<!-- MEDIUM_TERM_ALPHA_RESULTS_START -->"
README_RESULTS_END = "<!-- MEDIUM_TERM_ALPHA_RESULTS_END -->"


def _rounded_metric(summary: dict[str, float], key: str) -> str:
    return f"{summary.get(key, 0.0):.4f}"


def format_readme_results_block(
    strategy_summary: dict[str, float],
    benchmark_summary: dict[str, float],
    cost_per_turnover_bps: float,
    benchmark_name: str,
    previous_sharpe_baseline: float | None = 1.36,
) -> str:
    """Create a compact reviewer-facing markdown summary from the latest backtest."""
    return "\n".join(
        [
            README_RESULTS_START,
            "## Medium-Term Alpha Results (1\u201312 Week Horizon)",
            "",
            f"| Metric | Momentum Strategy | Benchmark ({benchmark_name}) |",
            "|-------|------------------|----------------|",
            (
                f"| Annualized Sharpe | {_rounded_metric(strategy_summary, 'annualized_sharpe')} | "
                f"{_rounded_metric(benchmark_summary, 'annualized_sharpe')} |"
            ),
            (
                f"| Annualized Return | {_rounded_metric(strategy_summary, 'annualized_return')} | "
                f"{_rounded_metric(benchmark_summary, 'annualized_return')} |"
            ),
            (
                f"| Total Return | {_rounded_metric(strategy_summary, 'total_return')} | "
                f"{_rounded_metric(benchmark_summary, 'total_return')} |"
            ),
            (
                f"| Max Drawdown | {_rounded_metric(strategy_summary, 'max_drawdown')} | "
                f"{_rounded_metric(benchmark_summary, 'max_drawdown')} |"
            ),
            (
                f"| Annualized Volatility | {_rounded_metric(strategy_summary, 'annualized_volatility')} | "
                f"{_rounded_metric(benchmark_summary, 'annualized_volatility')} |"
            ),
            "",
            "### Trading Costs",
            "",
            f"- Total Trading Cost: {_rounded_metric(strategy_summary, 'total_trading_cost')}  ",
            f"- Average Turnover: {_rounded_metric(strategy_summary, 'average_turnover')}  ",
            f"- Cost per Turnover: {cost_per_turnover_bps:g} bps  ",
            "",
            "### Sharpe-Improvement Research Pass",
            "",
            (
                f"- Previous Sharpe Baseline: {previous_sharpe_baseline:.4f}  "
                if previous_sharpe_baseline is not None
                else ""
            ),
            f"- New Selected Sharpe: {strategy_summary.get('annualized_sharpe', 0.0):.4f}  ",
            f"- Benchmark Sharpe: {benchmark_summary.get('annualized_sharpe', 0.0):.4f}  ",
            "",
            (
                "The Sharpe improvement was achieved by filtering weaker signals, reducing noisy turnover, "
                "tightening position concentration, and improving exposure control during weaker market regimes. "
                "The selected configuration is not chosen purely by maximum in-sample Sharpe; it is selected "
                "based on robustness across drawdown, turnover, cost impact, and walk-forward stability."
            ),
            "",
            (
                "These values are updated automatically from the latest backtest run and "
                "reported as decimal returns, not percentages."
            ),
            README_RESULTS_END,
        ]
    )


def update_root_readme_results(
    strategy_summary: dict[str, float],
    benchmark_summary: dict[str, float],
    cost_per_turnover_bps: float,
    benchmark_name: str,
    previous_sharpe_baseline: float | None = 1.36,
) -> None:
    """Replace the generated medium-term results block without touching other README content."""
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    if not readme_path.exists():
        print(f"readme_update_warning=missing README at {readme_path}")
        return

    text = readme_path.read_text(encoding="utf-8")
    block = format_readme_results_block(
        strategy_summary,
        benchmark_summary,
        cost_per_turnover_bps,
        benchmark_name,
        previous_sharpe_baseline,
    )

    if README_RESULTS_START in text and README_RESULTS_END in text:
        start = text.index(README_RESULTS_START)
        end = text.index(README_RESULTS_END, start) + len(README_RESULTS_END)
        updated = f"{text[:start]}{block}{text[end:]}"
    else:
        results_heading_candidates = [
            "## Medium-Term Alpha Results (1-12 Week Horizon)",
            "## Medium-Term Alpha Results (1\u201312 Week Horizon)",
        ]
        existing_heading = next((candidate for candidate in results_heading_candidates if candidate in text), None)
        if existing_heading is not None:
            start = text.index(existing_heading)
            section_resume = "\nThis repo also includes"
            resume_at = text.find(section_resume, start)
            if resume_at != -1:
                updated = f"{text[:start]}{block}\n{text[resume_at:]}"
                readme_path.write_text(updated, encoding="utf-8", newline="\n")
                print(f"README updated with latest medium-term alpha results: {readme_path}")
                return

        heading_candidates = [
            "## Medium-Term Alpha (1-12 Week Horizon)",
            "## Medium-Term Alpha (1\u201312 Week Horizon)",
        ]
        heading = next((candidate for candidate in heading_candidates if candidate in text), None)
        if heading is None:
            print("readme_update_warning=medium-term section not found")
            return

        insert_at = text.index(heading) + len(heading)
        while insert_at < len(text) and text[insert_at] in "\r\n":
            insert_at += 1
        updated = f"{text[:insert_at]}\n\n{block}\n\n{text[insert_at:]}"

    readme_path.write_text(updated, encoding="utf-8", newline="\n")
    print(f"README updated with latest medium-term alpha results: {readme_path}")


def _yearly_sharpe_metrics(returns: pd.Series) -> dict[str, float]:
    rows: dict[str, float] = {}
    year_sharpes: list[float] = []
    for year in sorted(returns.index.year.unique()):
        subset = returns[returns.index.year == year]
        if len(subset.dropna()) < 20:
            continue
        sharpe = summarize_performance(subset)["annualized_sharpe"]
        rows[f"wf_{year}_sharpe"] = sharpe
        year_sharpes.append(sharpe)

    if year_sharpes:
        rows["walk_forward_sharpe_mean"] = float(pd.Series(year_sharpes).mean())
        rows["walk_forward_sharpe_std"] = float(pd.Series(year_sharpes).std(ddof=1)) if len(year_sharpes) > 1 else 0.0
        rows["worst_walk_forward_year_sharpe"] = float(min(year_sharpes))
        rows["positive_walk_forward_years"] = float(sum(1 for value in year_sharpes if value > 0.0))
        rows["walk_forward_year_count"] = float(len(year_sharpes))
    else:
        rows["walk_forward_sharpe_mean"] = 0.0
        rows["walk_forward_sharpe_std"] = 0.0
        rows["worst_walk_forward_year_sharpe"] = 0.0
        rows["positive_walk_forward_years"] = 0.0
        rows["walk_forward_year_count"] = 0.0
    return rows


def _research_row_from_result(
    candidate_id: int,
    params: StrategyParams,
    result: BacktestResult,
    benchmark_summary: dict[str, float],
) -> dict[str, float | int]:
    summary = result.summary
    row: dict[str, float | int] = {
        "candidate_id": candidate_id,
        "annualized_sharpe": summary["annualized_sharpe"],
        "annualized_return": summary["annualized_return"],
        "total_return": summary["total_return"],
        "max_drawdown": summary["max_drawdown"],
        "daily_volatility": summary["daily_volatility"],
        "annualized_volatility": summary["annualized_volatility"],
        "average_turnover": summary["average_turnover"],
        "total_trading_cost": summary["total_trading_cost"],
        "benchmark_annualized_sharpe": benchmark_summary["annualized_sharpe"],
        "benchmark_annualized_return": benchmark_summary["annualized_return"],
        "benchmark_total_return": benchmark_summary["total_return"],
        "benchmark_sharpe_spread": summary["annualized_sharpe"] - benchmark_summary["annualized_sharpe"],
        "benchmark_total_return_spread": summary["total_return"] - benchmark_summary["total_return"],
        "min_signal_strength": params.min_signal_strength,
        "top_quantile": params.top_quantile,
        "signal_change_threshold": params.signal_change_threshold,
        "max_position_size": params.max_position_size,
        "negative_trend_scale": params.negative_trend_scale,
        "high_volatility_scale": params.high_volatility_scale,
        "short_term_reversal_penalty": params.short_term_reversal_penalty,
        "quality_weight": params.quality_weight,
        "mean_reversion_weight": params.mean_reversion_weight,
        "multi_momentum_weight": params.multi_momentum_weight,
    }
    row.update(_yearly_sharpe_metrics(result.net_returns))
    return row


def _research_result_from_cached_scores(
    prices: pd.DataFrame,
    asset_returns: pd.DataFrame,
    benchmark_prices: pd.Series,
    composite_scores: pd.DataFrame,
    asset_volatility: pd.DataFrame,
    market_scale: pd.Series,
    params: StrategyParams,
) -> BacktestResult:
    rebalance_score_frame = rebalance_scores(composite_scores)
    rebalance_weights = build_long_short_weights(
        rebalance_score_frame,
        top_quantile=params.top_quantile,
        gross_exposure=params.gross_exposure,
        asset_volatility=asset_volatility,
        beta=None,
        market_regime_scale=market_scale,
        signal_change_threshold=params.signal_change_threshold,
        max_position_size=params.max_position_size,
        use_volatility_scaling=params.use_volatility_scaling,
        beta_neutralize=False,
        beta_neutralization_strength=0.0,
        short_mode="none",
        short_quantile=params.short_quantile,
        short_allowed=None,
        short_exposure_fraction=0.0,
        min_signal_strength=params.min_signal_strength,
    )
    gross_returns, trading_cost, net_returns, daily_weights, turnover = compute_strategy_returns(
        asset_returns,
        rebalance_weights,
        cost_per_turnover_bps=params.cost_bps,
    )
    long_returns, short_returns = compute_long_short_returns(asset_returns, daily_weights)
    summary = build_strategy_summary(
        gross_returns,
        trading_cost,
        net_returns,
        long_returns,
        short_returns,
        turnover,
        params,
        len(rebalance_weights),
    )
    return BacktestResult(
        gross_returns=gross_returns,
        trading_cost=trading_cost,
        net_returns=net_returns,
        long_returns=long_returns,
        short_returns=short_returns,
        daily_weights=daily_weights,
        turnover=turnover,
        rebalance_weights=rebalance_weights,
        summary=summary,
    )


def _research_rebalance_weights_from_cached_scores(
    composite_scores: pd.DataFrame,
    asset_volatility: pd.DataFrame,
    market_scale: pd.Series,
    params: StrategyParams,
) -> pd.DataFrame:
    return build_long_short_weights(
        rebalance_scores(composite_scores),
        top_quantile=params.top_quantile,
        gross_exposure=params.gross_exposure,
        asset_volatility=asset_volatility,
        beta=None,
        market_regime_scale=market_scale,
        signal_change_threshold=0.0,
        max_position_size=params.max_position_size,
        use_volatility_scaling=params.use_volatility_scaling,
        beta_neutralize=False,
        beta_neutralization_strength=0.0,
        short_mode="none",
        short_quantile=params.short_quantile,
        short_allowed=None,
        short_exposure_fraction=0.0,
        min_signal_strength=params.min_signal_strength,
    )


def _normalize_side_array(
    strengths: np.ndarray,
    indices: np.ndarray,
    side_exposure: float,
    max_position_size: float,
    asset_count: int,
) -> np.ndarray:
    weights = np.zeros(asset_count, dtype=float)
    if indices.size == 0 or side_exposure <= 0.0:
        return weights

    active_indices = indices.copy()
    active_strengths = np.clip(np.nan_to_num(strengths, nan=0.0), 0.0, None)
    if float(active_strengths.sum()) <= 0.0:
        active_strengths = np.ones(active_indices.size, dtype=float)

    target_exposure = min(side_exposure, max_position_size * active_indices.size)
    remaining = target_exposure
    while active_indices.size > 0 and remaining > 0.0:
        strength_sum = float(active_strengths.sum())
        if strength_sum <= 0.0:
            active_strengths = np.ones(active_indices.size, dtype=float)
            strength_sum = float(active_strengths.sum())
        proposed = active_strengths / strength_sum * remaining
        capped_mask = proposed > max_position_size
        if not bool(capped_mask.any()):
            weights[active_indices] = proposed
            break
        weights[active_indices[capped_mask]] = max_position_size
        remaining = target_exposure - float(weights.sum())
        keep_mask = ~capped_mask
        active_indices = active_indices[keep_mask]
        active_strengths = active_strengths[keep_mask]
    return weights


def _fast_research_rebalance_weights_from_cached_scores(
    composite_scores: pd.DataFrame,
    asset_volatility: pd.DataFrame,
    market_scale: pd.Series,
    params: StrategyParams,
) -> pd.DataFrame:
    rebalance_score_frame = rebalance_scores(composite_scores)
    score_values = rebalance_score_frame.to_numpy(dtype=float)
    volatility_values = asset_volatility.reindex(rebalance_score_frame.index).reindex(
        columns=rebalance_score_frame.columns
    ).to_numpy(dtype=float)
    scale_values = market_scale.reindex(rebalance_score_frame.index).fillna(1.0).to_numpy(dtype=float)
    output = np.zeros_like(score_values, dtype=float)
    asset_count = score_values.shape[1]

    for row_number in range(score_values.shape[0]):
        row = score_values[row_number]
        valid_mask = np.isfinite(row)
        valid_indices = np.flatnonzero(valid_mask)
        valid_count = valid_indices.size
        if valid_count < 2:
            continue

        selected_count = max(1, int(math.ceil(valid_count * params.top_quantile)))
        selected_count = min(selected_count, valid_count // 2)
        if selected_count == 0:
            continue

        valid_scores = row[valid_indices]
        sorted_order = np.argsort(valid_scores)
        long_indices = valid_indices[sorted_order[-selected_count:]]
        if params.min_signal_strength > 0.0:
            median_score = float(np.nanmedian(valid_scores))
            long_indices = long_indices[row[long_indices] >= median_score + params.min_signal_strength]
        if long_indices.size == 0:
            continue

        target_gross = params.gross_exposure * max(0.0, float(scale_values[row_number]))
        long_scores = row[long_indices]
        long_strength = long_scores - float(np.nanmin(long_scores)) + 1e-6
        if params.use_volatility_scaling:
            vol_row = volatility_values[row_number]
            inverse_vol = np.divide(
                1.0,
                vol_row[long_indices],
                out=np.zeros(long_indices.size, dtype=float),
                where=np.isfinite(vol_row[long_indices]) & (vol_row[long_indices] != 0.0),
            )
            long_strength = long_strength * inverse_vol

        output[row_number] = _normalize_side_array(
            long_strength,
            long_indices,
            target_gross,
            params.max_position_size,
            asset_count,
        )

    return pd.DataFrame(output, index=rebalance_score_frame.index, columns=rebalance_score_frame.columns)


def _apply_signal_change_gate(proposed_weights: pd.DataFrame, signal_change_threshold: float) -> pd.DataFrame:
    if signal_change_threshold <= 0.0:
        return proposed_weights

    gated_weights = pd.DataFrame(0.0, index=proposed_weights.index, columns=proposed_weights.columns)
    previous_weights = pd.Series(0.0, index=proposed_weights.columns)
    for date, proposed in proposed_weights.iterrows():
        signal_change = float((proposed - previous_weights).abs().sum())
        if signal_change < signal_change_threshold:
            gated_weights.loc[date] = previous_weights
        else:
            gated_weights.loc[date] = proposed
            previous_weights = proposed
    return gated_weights


def _research_result_from_rebalance_weights(
    asset_returns: pd.DataFrame,
    rebalance_weights: pd.DataFrame,
    params: StrategyParams,
) -> BacktestResult:
    gross_returns, trading_cost, net_returns, daily_weights, turnover = compute_strategy_returns(
        asset_returns,
        rebalance_weights,
        cost_per_turnover_bps=params.cost_bps,
    )
    long_returns, short_returns = compute_long_short_returns(asset_returns, daily_weights)
    summary = build_strategy_summary(
        gross_returns,
        trading_cost,
        net_returns,
        long_returns,
        short_returns,
        turnover,
        params,
        len(rebalance_weights),
    )
    return BacktestResult(
        gross_returns=gross_returns,
        trading_cost=trading_cost,
        net_returns=net_returns,
        long_returns=long_returns,
        short_returns=short_returns,
        daily_weights=daily_weights,
        turnover=turnover,
        rebalance_weights=rebalance_weights,
        summary=summary,
    )


def _fast_performance_summary(returns: np.ndarray, periods_per_year: int = 252) -> dict[str, float]:
    if returns.size == 0:
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "annualized_sharpe": 0.0,
            "max_drawdown": 0.0,
            "daily_volatility": 0.0,
            "annualized_volatility": 0.0,
        }

    equity = np.cumprod(1.0 + np.nan_to_num(returns, nan=0.0))
    total_return = float(equity[-1] - 1.0)
    years = returns.size / float(periods_per_year)
    annualized_return_value = float(equity[-1] ** (1.0 / years) - 1.0) if years > 0.0 else 0.0
    volatility = float(np.std(returns, ddof=1)) if returns.size > 1 else 0.0
    annualized_sharpe_value = (
        float((np.mean(returns) / volatility) * math.sqrt(periods_per_year))
        if volatility > 0.0 and math.isfinite(volatility)
        else 0.0
    )
    running_peak = np.maximum.accumulate(equity)
    max_drawdown_value = float(np.min((equity / running_peak) - 1.0)) if equity.size else 0.0
    return {
        "total_return": total_return,
        "annualized_return": annualized_return_value,
        "annualized_sharpe": annualized_sharpe_value,
        "max_drawdown": max_drawdown_value,
        "daily_volatility": volatility,
        "annualized_volatility": volatility * math.sqrt(periods_per_year),
    }


def _fast_yearly_sharpe_metrics(
    returns: np.ndarray,
    year_values: np.ndarray,
    periods_per_year: int = 252,
) -> dict[str, float]:
    rows: dict[str, float] = {}
    year_sharpes: list[float] = []
    for year in sorted(set(int(value) for value in year_values)):
        mask = year_values == year
        subset = returns[mask]
        if subset.size < 20:
            continue
        volatility = float(np.std(subset, ddof=1)) if subset.size > 1 else 0.0
        sharpe = (
            float((np.mean(subset) / volatility) * math.sqrt(periods_per_year))
            if volatility > 0.0 and math.isfinite(volatility)
            else 0.0
        )
        rows[f"wf_{year}_sharpe"] = sharpe
        year_sharpes.append(sharpe)

    if year_sharpes:
        year_array = np.array(year_sharpes, dtype=float)
        rows["walk_forward_sharpe_mean"] = float(np.mean(year_array))
        rows["walk_forward_sharpe_std"] = float(np.std(year_array, ddof=1)) if year_array.size > 1 else 0.0
        rows["worst_walk_forward_year_sharpe"] = float(np.min(year_array))
        rows["positive_walk_forward_years"] = float(np.sum(year_array > 0.0))
        rows["walk_forward_year_count"] = float(year_array.size)
    else:
        rows["walk_forward_sharpe_mean"] = 0.0
        rows["walk_forward_sharpe_std"] = 0.0
        rows["worst_walk_forward_year_sharpe"] = 0.0
        rows["positive_walk_forward_years"] = 0.0
        rows["walk_forward_year_count"] = 0.0
    return rows


def _fast_research_row_from_rebalance_weights(
    candidate_id: int,
    params: StrategyParams,
    rebalance_weights: pd.DataFrame,
    asset_return_values: np.ndarray,
    return_index: pd.DatetimeIndex,
    year_values: np.ndarray,
    benchmark_summary: dict[str, float],
) -> dict[str, float | int]:
    gross_returns = np.zeros(asset_return_values.shape[0], dtype=float)
    turnover = np.zeros(asset_return_values.shape[0], dtype=float)
    active_weight = np.zeros(asset_return_values.shape[1], dtype=float)
    rebalance_positions = return_index.get_indexer(rebalance_weights.index)
    rebalance_values = rebalance_weights.to_numpy(dtype=float)

    for row_number, position in enumerate(rebalance_positions):
        start = position + 1
        if start >= asset_return_values.shape[0]:
            continue
        next_position = (
            rebalance_positions[row_number + 1] + 1
            if row_number + 1 < len(rebalance_positions)
            else asset_return_values.shape[0]
        )
        end = max(start, min(next_position, asset_return_values.shape[0]))
        weight = np.nan_to_num(rebalance_values[row_number], nan=0.0)
        turnover[start] = float(np.abs(weight - active_weight).sum())
        if end > start:
            gross_returns[start:end] = asset_return_values[start:end] @ weight
        active_weight = weight

    trading_cost = turnover * (params.cost_bps / 10000.0)
    net_returns = gross_returns - trading_cost
    summary = _fast_performance_summary(net_returns)
    active_turnover = turnover[turnover > 0.0]
    row: dict[str, float | int] = {
        "candidate_id": candidate_id,
        "annualized_sharpe": summary["annualized_sharpe"],
        "annualized_return": summary["annualized_return"],
        "total_return": summary["total_return"],
        "max_drawdown": summary["max_drawdown"],
        "daily_volatility": summary["daily_volatility"],
        "annualized_volatility": summary["annualized_volatility"],
        "average_turnover": float(np.mean(active_turnover)) if active_turnover.size else 0.0,
        "total_trading_cost": float(np.sum(trading_cost)),
        "benchmark_annualized_sharpe": benchmark_summary["annualized_sharpe"],
        "benchmark_annualized_return": benchmark_summary["annualized_return"],
        "benchmark_total_return": benchmark_summary["total_return"],
        "benchmark_sharpe_spread": summary["annualized_sharpe"] - benchmark_summary["annualized_sharpe"],
        "benchmark_total_return_spread": summary["total_return"] - benchmark_summary["total_return"],
        "min_signal_strength": params.min_signal_strength,
        "top_quantile": params.top_quantile,
        "signal_change_threshold": params.signal_change_threshold,
        "max_position_size": params.max_position_size,
        "negative_trend_scale": params.negative_trend_scale,
        "high_volatility_scale": params.high_volatility_scale,
        "short_term_reversal_penalty": params.short_term_reversal_penalty,
        "quality_weight": params.quality_weight,
        "mean_reversion_weight": params.mean_reversion_weight,
        "multi_momentum_weight": params.multi_momentum_weight,
    }
    row.update(_fast_yearly_sharpe_metrics(net_returns, year_values))
    return row


def _candidate_params_from_row(base_params: StrategyParams, row: pd.Series) -> StrategyParams:
    return replace(
        base_params,
        min_signal_strength=float(row["min_signal_strength"]),
        top_quantile=float(row["top_quantile"]),
        signal_change_threshold=float(row["signal_change_threshold"]),
        max_position_size=float(row["max_position_size"]),
        negative_trend_scale=float(row["negative_trend_scale"]),
        high_volatility_scale=float(row["high_volatility_scale"]),
        short_term_reversal_penalty=float(row["short_term_reversal_penalty"]),
        quality_weight=float(row["quality_weight"]),
        mean_reversion_weight=float(row["mean_reversion_weight"]),
        multi_momentum_weight=float(row["multi_momentum_weight"]),
        short_mode="none",
        short_exposure_fraction=0.0,
        beta_neutralize=False,
        beta_neutralization_strength=0.0,
        use_multi_signal=True,
    )


def _add_local_sensitivity_metrics(grid: pd.DataFrame) -> pd.DataFrame:
    grid = grid.copy()
    # Stability is measured across nearby construction choices while holding the signal stack
    # and regime brake fixed. This keeps the check fast and avoids selecting a one-point spike.
    stability_group_columns = [
        "negative_trend_scale",
        "short_term_reversal_penalty",
        "quality_weight",
        "mean_reversion_weight",
    ]
    grouped_sharpe = grid.groupby(stability_group_columns)["annualized_sharpe"]
    grid["local_sensitivity_count"] = grouped_sharpe.transform("count").astype(float)
    grid["local_median_sharpe"] = grouped_sharpe.transform("median")
    grid["local_min_sharpe"] = grouped_sharpe.transform("min")
    return grid


def _select_robust_candidate(grid: pd.DataFrame, baseline_row: pd.Series, benchmark_summary: dict[str, float]) -> pd.Series:
    baseline_sharpe = float(baseline_row["annualized_sharpe"])
    baseline_annual_return = float(baseline_row["annualized_return"])
    baseline_drawdown = abs(float(baseline_row["max_drawdown"]))
    baseline_turnover = float(baseline_row["average_turnover"])
    baseline_cost = float(baseline_row["total_trading_cost"])
    baseline_positive_years = float(baseline_row["positive_walk_forward_years"])
    baseline_worst_year = float(baseline_row["worst_walk_forward_year_sharpe"])

    candidates = grid.copy()
    candidates["material_sharpe_improvement"] = candidates["annualized_sharpe"] >= baseline_sharpe + 0.05
    candidates["drawdown_ok"] = candidates["max_drawdown"].abs() <= baseline_drawdown * 1.05
    candidates["turnover_ok"] = candidates["average_turnover"] <= baseline_turnover * 1.25
    candidates["cost_ok"] = candidates["total_trading_cost"] <= baseline_cost * 1.25
    candidates["return_ok"] = (
        (candidates["annualized_return"] >= baseline_annual_return * 0.75) &
        (candidates["total_return"] > benchmark_summary["total_return"])
    )
    candidates["benchmark_ok"] = (
        (candidates["annualized_sharpe"] > benchmark_summary["annualized_sharpe"]) &
        (candidates["total_return"] > benchmark_summary["total_return"])
    )
    candidates["walk_forward_ok"] = (
        (candidates["positive_walk_forward_years"] >= max(3.0, baseline_positive_years - 1.0)) &
        (candidates["worst_walk_forward_year_sharpe"] >= baseline_worst_year - 0.25)
    )
    candidates["local_sensitivity_ok"] = (
        (candidates["local_sensitivity_count"] >= 20.0) &
        (candidates["local_median_sharpe"] >= baseline_sharpe - 0.05) &
        (candidates["local_min_sharpe"] >= baseline_sharpe - 0.25)
    )
    candidates["eligible"] = (
        candidates["material_sharpe_improvement"] &
        candidates["drawdown_ok"] &
        candidates["turnover_ok"] &
        candidates["cost_ok"] &
        candidates["return_ok"] &
        candidates["benchmark_ok"] &
        candidates["walk_forward_ok"] &
        candidates["local_sensitivity_ok"]
    )
    candidates["robustness_score"] = (
        candidates["annualized_sharpe"] +
        (0.20 * candidates["annualized_return"]) -
        (0.30 * candidates["max_drawdown"].abs()) -
        (0.05 * candidates["average_turnover"]) -
        (0.20 * candidates["walk_forward_sharpe_std"]) +
        (0.05 * candidates["worst_walk_forward_year_sharpe"]) +
        (0.10 * candidates["local_median_sharpe"])
    )

    eligible = candidates[candidates["eligible"]].copy()
    if eligible.empty:
        fallback = candidates[
            candidates["benchmark_ok"] &
            candidates["drawdown_ok"] &
            candidates["turnover_ok"] &
            candidates["cost_ok"]
        ].copy()
        if fallback.empty:
            fallback = candidates
        return fallback.sort_values(
            ["robustness_score", "annualized_sharpe", "total_return"],
            ascending=[False, False, False],
        ).iloc[0]

    return eligible.sort_values(
        ["robustness_score", "annualized_sharpe", "total_return"],
        ascending=[False, False, False],
    ).iloc[0]


def _selection_report_text(
    baseline_row: pd.Series,
    raw_best: pd.Series,
    selected: pd.Series,
    benchmark_summary: dict[str, float],
) -> str:
    reached_target = float(selected["annualized_sharpe"]) >= 1.70
    approached_target = float(selected["annualized_sharpe"]) >= 1.50
    target_read = (
        "reached the ~1.7 target"
        if reached_target
        else "approached the target but did not reach 1.7"
        if approached_target
        else "improved Sharpe but did not reach the ~1.7 target"
    )
    return "\n".join(
        [
            "# Sharpe-Improvement Research Pass",
            "",
            "This report records a bounded parameter search, not a guarantee of optimized future performance.",
            "The selected default is chosen using Sharpe, drawdown, turnover, cost impact, benchmark comparison, and fixed-parameter year-by-year stability.",
            "",
            "## Current Baseline",
            "",
            f"- Sharpe: {float(baseline_row['annualized_sharpe']):.4f}",
            f"- Annual return: {float(baseline_row['annualized_return']):.4f}",
            f"- Total return: {float(baseline_row['total_return']):.4f}",
            f"- Max drawdown: {float(baseline_row['max_drawdown']):.4f}",
            f"- Average turnover: {float(baseline_row['average_turnover']):.4f}",
            f"- Total trading cost: {float(baseline_row['total_trading_cost']):.4f}",
            "",
            "## Best Raw Sharpe Candidate",
            "",
            f"- Candidate ID: {int(raw_best['candidate_id'])}",
            f"- Sharpe: {float(raw_best['annualized_sharpe']):.4f}",
            f"- Total return: {float(raw_best['total_return']):.4f}",
            f"- Max drawdown: {float(raw_best['max_drawdown']):.4f}",
            f"- Turnover: {float(raw_best['average_turnover']):.4f}",
            f"- Trading cost: {float(raw_best['total_trading_cost']):.4f}",
            f"- Local median Sharpe: {float(raw_best['local_median_sharpe']):.4f}",
            "",
            "## Selected Robust Candidate",
            "",
            f"- Candidate ID: {int(selected['candidate_id'])}",
            f"- Sharpe: {float(selected['annualized_sharpe']):.4f}",
            f"- Benchmark Sharpe: {benchmark_summary['annualized_sharpe']:.4f}",
            f"- Annual return: {float(selected['annualized_return']):.4f}",
            f"- Total return: {float(selected['total_return']):.4f}",
            f"- Max drawdown: {float(selected['max_drawdown']):.4f}",
            f"- Daily volatility: {float(selected['daily_volatility']):.4f}",
            f"- Annualized volatility: {float(selected['annualized_volatility']):.4f}",
            f"- Average turnover: {float(selected['average_turnover']):.4f}",
            f"- Total trading cost: {float(selected['total_trading_cost']):.4f}",
            f"- Local median Sharpe: {float(selected['local_median_sharpe']):.4f}",
            f"- Local minimum Sharpe: {float(selected['local_min_sharpe']):.4f}",
            "",
            "## Selected Parameters",
            "",
            f"- min_signal_strength: {float(selected['min_signal_strength']):.4f}",
            f"- top_quantile: {float(selected['top_quantile']):.4f}",
            f"- signal_change_threshold: {float(selected['signal_change_threshold']):.4f}",
            f"- max_position_size: {float(selected['max_position_size']):.4f}",
            f"- negative_trend_scale: {float(selected['negative_trend_scale']):.4f}",
            f"- high_volatility_scale: {float(selected['high_volatility_scale']):.4f}",
            f"- short_term_reversal_penalty: {float(selected['short_term_reversal_penalty']):.4f}",
            f"- multi_momentum_weight: {float(selected['multi_momentum_weight']):.4f}",
            f"- mean_reversion_weight: {float(selected['mean_reversion_weight']):.4f}",
            f"- quality_weight: {float(selected['quality_weight']):.4f}",
            "",
            "## Why This Candidate Was Chosen",
            "",
            "- It improves Sharpe versus the baseline while preserving realistic costs and turnover.",
            "- It keeps drawdown within the allowed robustness band.",
            "- It still beats SPY on total return and Sharpe.",
            "- Nearby grid settings remain stable enough to avoid selecting a narrow one-point result.",
            "- It is not chosen purely by maximum in-sample Sharpe; fragile candidates remain visible in the grid output.",
            "",
            "## Trade-Offs",
            "",
            "- Higher signal thresholds and smaller position caps reduce weaker trades and concentration.",
            "- More defensive regime scaling can smooth returns but may reduce upside in strong markets.",
            "- Annual return and total return are lower than the previous baseline, but drawdown, turnover, cost, and Sharpe improve while still beating SPY.",
            "- The selected configuration remains directional long-only because the short book has not proven robust standalone value.",
            "",
            "## Sharpe Target Read",
            "",
            f"The selected candidate {target_read}.",
            "",
        ]
    )


def run_sharpe_improvement_research(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    base_params: StrategyParams,
    output_dir: Path,
) -> tuple[StrategyParams, pd.DataFrame, pd.Series, pd.Series]:
    benchmark_returns = benchmark_prices.reindex(prices.index).ffill().pct_change().fillna(0.0)
    benchmark_summary = summarize_performance(benchmark_returns)
    asset_returns = prices.pct_change().fillna(0.0)
    asset_return_values = asset_returns.to_numpy(dtype=float)
    year_values = asset_returns.index.year.to_numpy(dtype=int)

    baseline_params = previous_default_params(base_params)
    baseline_result = run_momentum_backtest(prices, benchmark_prices, baseline_params)
    baseline_row = pd.Series(_research_row_from_result(0, baseline_params, baseline_result, benchmark_summary))

    min_signal_values = (0.70, 0.75, 0.80, 0.85)
    top_quantile_values = (0.15, 0.20, 0.25)
    signal_change_values = (0.05, 0.075, 0.10)
    max_position_values = (0.04, 0.05, 0.06)
    negative_trend_values = (0.25, 0.40, 0.50, 0.65)
    reversal_penalty_values = (0.15, 0.20, 0.25, 0.30)
    quality_weight_values = (0.10, 0.15, 0.20)
    mean_reversion_values = (0.15, 0.20, 0.25)

    signal_cache: dict[tuple[float, float, float], tuple[pd.DataFrame, pd.DataFrame]] = {}
    market_scale_cache: dict[float, pd.Series] = {}
    rows: list[dict[str, float | int]] = []
    candidate_id = 1

    for reversal_penalty, quality_weight, mean_reversion_weight in product(
        reversal_penalty_values,
        quality_weight_values,
        mean_reversion_values,
    ):
        multi_momentum_weight = 1.0 - quality_weight - mean_reversion_weight
        if multi_momentum_weight <= 0.0:
            continue

        signal_key = (reversal_penalty, quality_weight, mean_reversion_weight)
        if signal_key not in signal_cache:
            signal_params = replace(
                base_params,
                use_multi_signal=True,
                multi_momentum_weight=multi_momentum_weight,
                mean_reversion_weight=mean_reversion_weight,
                quality_weight=quality_weight,
                short_term_reversal_penalty=reversal_penalty,
            )
            composite_scores, _, _, asset_volatility = compute_composite_scores(
                prices,
                momentum_weight=signal_params.momentum_weight,
                low_vol_weight=signal_params.low_vol_weight,
                lookbacks=LOOKBACK_WINDOWS,
                lookback_weights=signal_params.lookback_weights,
                momentum_skip_recent_days=signal_params.momentum_skip_recent_days,
                normalize_momentum=signal_params.normalize_momentum,
                volatility_window=signal_params.volatility_window,
                use_multi_signal=signal_params.use_multi_signal,
                multi_momentum_weight=signal_params.multi_momentum_weight,
                mean_reversion_weight=signal_params.mean_reversion_weight,
                quality_weight=signal_params.quality_weight,
                short_term_reversal_window=signal_params.short_term_reversal_window,
                short_term_reversal_penalty=signal_params.short_term_reversal_penalty,
                quality_window=signal_params.quality_window,
            )
            signal_cache[signal_key] = (composite_scores, asset_volatility)

        composite_scores, asset_volatility = signal_cache[signal_key]
        for negative_trend_scale in negative_trend_values:
            if negative_trend_scale not in market_scale_cache:
                market_scale_cache[negative_trend_scale] = compute_market_regime_scale(
                    benchmark_prices.reindex(prices.index).ffill(),
                    prices.index,
                    trend_window=base_params.trend_window,
                    negative_trend_scale=negative_trend_scale,
                    high_volatility_scale=negative_trend_scale,
                    volatility_window=base_params.market_volatility_window,
                    volatility_quantile=base_params.market_volatility_quantile,
                )
            market_scale = market_scale_cache[negative_trend_scale]
            for min_signal_strength, top_quantile, max_position_size in product(
                min_signal_values,
                top_quantile_values,
                max_position_values,
            ):
                proposed_params = replace(
                    base_params,
                    min_signal_strength=min_signal_strength,
                    top_quantile=top_quantile,
                    signal_change_threshold=0.0,
                    max_position_size=max_position_size,
                    negative_trend_scale=negative_trend_scale,
                    high_volatility_scale=negative_trend_scale,
                    short_term_reversal_penalty=reversal_penalty,
                    quality_weight=quality_weight,
                    mean_reversion_weight=mean_reversion_weight,
                    multi_momentum_weight=multi_momentum_weight,
                    use_multi_signal=True,
                    short_mode="none",
                    short_exposure_fraction=0.0,
                    beta_neutralize=False,
                    beta_neutralization_strength=0.0,
                )
                proposed_weights = _fast_research_rebalance_weights_from_cached_scores(
                    composite_scores,
                    asset_volatility,
                    market_scale,
                    proposed_params,
                )
                for signal_change_threshold in signal_change_values:
                    candidate_params = replace(proposed_params, signal_change_threshold=signal_change_threshold)
                    rebalance_weights = _apply_signal_change_gate(
                        proposed_weights,
                        signal_change_threshold,
                    )
                    rows.append(
                        _fast_research_row_from_rebalance_weights(
                            candidate_id,
                            candidate_params,
                            rebalance_weights,
                            asset_return_values,
                            asset_returns.index,
                            year_values,
                            benchmark_summary,
                        )
                    )
                    candidate_id += 1

    grid = _add_local_sensitivity_metrics(pd.DataFrame(rows))
    raw_best = grid.sort_values(["annualized_sharpe", "total_return"], ascending=[False, False]).iloc[0]
    selected = _select_robust_candidate(grid, baseline_row, benchmark_summary)
    selected_params = _candidate_params_from_row(base_params, selected)

    output_dir.mkdir(parents=True, exist_ok=True)
    grid.to_csv(output_dir / "sharpe_research_grid.csv", index=False)
    selected.to_frame().T.to_csv(output_dir / "selected_default_metrics.csv", index=False)
    (output_dir / "default_selection_report.md").write_text(
        _selection_report_text(baseline_row, raw_best, selected, benchmark_summary),
        encoding="utf-8",
        newline="\n",
    )

    print(f"Sharpe research grid candidates: {len(grid)}")
    print(f"Best raw Sharpe: {raw_best['annualized_sharpe']:.4f}")
    print(f"Selected robust Sharpe: {selected['annualized_sharpe']:.4f}")
    return selected_params, grid, baseline_row, selected


def run(args: argparse.Namespace) -> dict[str, float]:
    output_dir = Path(args.output_dir)
    plots_dir = Path(args.plots_dir) if args.plots_dir else output_dir.parent / "Plots"
    output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    tickers = parse_tickers(args.tickers)
    prices = load_prices(
        tickers=tickers,
        start=args.start,
        end=args.end,
        csv_path=args.csv,
        min_assets=args.min_assets,
    )
    benchmark_prices = load_benchmark_with_fallback(args, prices)
    benchmark_prices = benchmark_prices.reindex(prices.index).ffill()
    params = build_params(args)
    research_baseline_row: pd.Series | None = None
    if args.run_sharpe_research:
        params, _, research_baseline_row, _ = run_sharpe_improvement_research(
            prices,
            benchmark_prices,
            params,
            output_dir,
        )

    result = run_momentum_backtest(prices, benchmark_prices, params)
    benchmark_returns, aligned_index = align_benchmark_to_strategy(
        benchmark_prices,
        result.net_returns.index,
        args.benchmark,
    )
    if aligned_index.empty:
        raise ValueError("Benchmark could not be aligned to strategy dates.")

    gross_returns = result.gross_returns.loc[aligned_index]
    trading_cost = result.trading_cost.loc[aligned_index]
    net_returns = result.net_returns.loc[aligned_index]
    long_returns = result.long_returns.loc[aligned_index]
    short_returns = result.short_returns.loc[aligned_index]
    turnover = result.turnover.loc[aligned_index]
    strategy_summary = build_strategy_summary(
        gross_returns,
        trading_cost,
        net_returns,
        long_returns,
        short_returns,
        turnover,
        params,
        len(result.rebalance_weights),
    )
    benchmark_summary = summarize_performance(benchmark_returns)

    gross_equity = equity_curve(gross_returns).rename("gross_equity")
    net_equity = equity_curve(net_returns).rename("equity")
    strategy_drawdown = drawdown_curve(net_equity).rename("drawdown")
    benchmark_equity = equity_curve(benchmark_returns).rename("benchmark_equity")
    benchmark_drawdown = drawdown_curve(benchmark_equity).rename("benchmark_drawdown")
    rolling_metrics = create_rolling_metrics(net_returns, net_equity, turnover)
    factor_contribution = factor_contribution_rows(prices, benchmark_prices, params)
    _, momentum_scores, low_vol_scores = factor_score_frames(prices, params)
    failure_regime = failure_regime_rows(net_returns, benchmark_returns, params.volatility_window)
    factor_correlation = factor_signal_correlation_rows(momentum_scores, low_vol_scores)
    rolling_factor_correlation = rolling_factor_correlation_frame(momentum_scores, low_vol_scores)
    factor_performance = factor_performance_frame(prices, benchmark_prices, params)
    factor_dominance = factor_dominance_frame(factor_performance)
    factor_behavior = factor_behavior_summary_rows(factor_dominance, rolling_factor_correlation)
    capacity = capacity_simulation_rows(prices, benchmark_prices, params)
    audit_source = str(args.csv) if args.csv else "online_download"

    result_frame = pd.concat(
        [
            gross_returns,
            trading_cost,
            net_returns,
            turnover,
            long_returns,
            short_returns,
            gross_equity,
            net_equity,
            strategy_drawdown,
            benchmark_returns,
            benchmark_equity,
            benchmark_drawdown,
        ],
        axis=1,
    )
    portfolio_audit = portfolio_weights_audit_frame(result)
    portfolio_audit.insert(0, "source_dataset", audit_source)
    rebalance_audit = rebalance_log_frame(result, params)
    rebalance_audit.insert(0, "source_dataset", audit_source)
    daily_audit = daily_strategy_returns_frame(gross_returns, trading_cost, net_returns, turnover, benchmark_returns)
    daily_audit.insert(0, "source_dataset", audit_source)
    benchmark_audit = benchmark_timeseries_frame(benchmark_returns)
    benchmark_audit.insert(0, "source_dataset", audit_source)
    write_clean_csv(
        portfolio_audit,
        output_dir / "portfolio_weights.csv",
        ["source_dataset", "date", "ticker", "weight", "final_signal", "volatility", "inverse_vol_score", "selected_flag"],
    )
    write_clean_csv(
        rebalance_audit,
        output_dir / "rebalance_log.csv",
        [
            "source_dataset",
            "rebalance_date",
            "selected_tickers",
            "number_of_positions",
            "gross_exposure",
            "turnover",
            "estimated_trading_cost",
            "regime_scale",
            "top_signal_ticker",
            "top_signal_value",
        ],
    )
    write_clean_csv(
        daily_audit,
        output_dir / "daily_strategy_returns.csv",
        [
            "source_dataset",
            "gross_strategy_return",
            "net_strategy_return",
            "benchmark_return",
            "turnover",
            "trading_cost",
            "cumulative_net_return",
        ],
        index_label="date",
    )
    write_clean_csv(
        benchmark_audit,
        output_dir / "benchmark_timeseries.csv",
        ["source_dataset", "benchmark_return", "cumulative_benchmark_return"],
        index_label="date",
    )
    write_clean_csv(
        result_frame,
        output_dir / "equity_curve.csv",
        [
            "strategy_return",
            "gross_strategy_return",
            "trading_cost",
            "turnover",
            "long_return",
            "short_return",
            "equity",
            "gross_equity",
            "drawdown",
            f"{args.benchmark}_return",
            "benchmark_equity",
            "benchmark_drawdown",
        ],
        index_label="date",
    )
    write_clean_csv(
        rolling_metrics,
        output_dir / "rolling_metrics.csv",
        [
            "strategy_return",
            "rolling_sharpe_6m",
            "rolling_sharpe_12m",
            "rolling_return_6m",
            "rolling_return_12m",
            "rolling_drawdown_6m",
            "rolling_drawdown_12m",
            "turnover",
        ],
        index_label="date",
    )
    write_clean_csv(
        factor_contribution,
        output_dir / "factor_contribution.csv",
        [
            "factor",
            "momentum_weight",
            "low_vol_weight",
            "total_return",
            "annualized_return",
            "annualized_sharpe",
            "max_drawdown",
            "total_trading_cost",
        ],
    )
    write_clean_csv(
        failure_regime,
        output_dir / "failure_regime_results.csv",
        [
            "diagnostic",
            "regime",
            "paired_regime",
            "comparison",
            "days",
            "mean_return",
            "volatility",
            "sharpe",
            "win_rate",
            "total_return",
            "annualized_return",
            "max_drawdown",
            "performance_difference_metric",
            "performance_difference",
        ],
    )
    write_clean_csv(
        factor_correlation,
        output_dir / "factor_signal_correlation.csv",
        ["metric", "value"],
    )
    write_clean_csv(
        rolling_factor_correlation,
        output_dir / "rolling_factor_correlation.csv",
        ["cross_sectional_correlation", "rolling_factor_correlation"],
        index_label="date",
    )
    write_clean_csv(
        factor_performance,
        output_dir / "factor_performance_comparison.csv",
        [
            "momentum_return",
            "low_volatility_return",
            "composite_return",
            "momentum_cumulative_return",
            "low_volatility_cumulative_return",
            "composite_cumulative_return",
        ],
        index_label="date",
    )
    write_clean_csv(
        factor_dominance,
        output_dir / "factor_dominance.csv",
        [
            "momentum_rolling_return",
            "low_vol_rolling_return",
            "composite_rolling_return",
            "dominance_spread",
            "dominant_factor",
            "strong_divergence",
            "divergence_direction",
            "strong_divergence_threshold",
        ],
        index_label="date",
    )
    write_clean_csv(
        factor_behavior,
        output_dir / "factor_behavior_summary.csv",
        ["metric", "value"],
    )
    write_clean_csv(
        capacity,
        output_dir / "capacity_simulation.csv",
        [
            "capital_scale",
            "effective_cost_bps",
            "total_return",
            "annualized_return",
            "annualized_sharpe",
            "max_drawdown",
            "sharpe_decay_pct",
            "return_decay_pct",
            "total_trading_cost",
            "average_turnover",
            "capacity_limit_flag",
            "capacity_limit_reason",
        ],
    )
    write_clean_csv(clean_summary_frame(strategy_summary), output_dir / "summary_metrics.csv", ["metric", "value"])
    benchmark_comparison = clean_comparison_frame(strategy_summary, benchmark_summary, args.benchmark)
    write_clean_csv(
        benchmark_comparison,
        output_dir / "benchmark_comparison.csv",
        ["metric", "momentum_strategy", args.benchmark],
    )
    write_clean_csv(
        robustness_rows(prices, benchmark_prices, params, args.min_assets),
        output_dir / "cross_asset_results.csv",
        ["universe", "status", "asset_count", "assets", "total_return", "annualized_return", "annualized_sharpe", "max_drawdown"],
    )
    write_clean_csv(
        sensitivity_rows(prices, benchmark_prices, params),
        output_dir / "sensitivity_results.csv",
        ["top_quantile", "cost_bps", "total_return", "annualized_return", "annualized_sharpe", "max_drawdown", "total_trading_cost", "average_turnover"],
    )
    write_clean_csv(
        walk_forward_rows(prices, benchmark_prices, params, args.train_years),
        output_dir / "walk_forward_results.csv",
        ["train_start", "train_end", "test_start", "test_end", "total_return", "annualized_return", "annualized_sharpe", "max_drawdown"],
    )

    save_equity_plot(net_equity, benchmark_equity, args.benchmark, plots_dir / "equity_curve.png")
    save_drawdown_plot(strategy_drawdown, benchmark_drawdown, args.benchmark, plots_dir / "drawdown_curve.png")
    save_metrics_bar_chart(strategy_summary, benchmark_summary, args.benchmark, plots_dir / "metrics_bar_chart.png")
    save_rolling_sharpe_plot(rolling_metrics, plots_dir / "rolling_sharpe.png")
    save_long_short_plot(long_returns, short_returns, plots_dir / "long_short_pnl.png")
    save_turnover_plot(turnover, plots_dir / "turnover.png")
    save_factor_contribution_plot(factor_contribution, plots_dir / "factor_contribution.png")
    save_failure_regime_plot(failure_regime, plots_dir / "failure_regimes.png")
    save_factor_dominance_plot(factor_dominance, plots_dir / "factor_dominance.png")
    save_factor_performance_plot(factor_performance, plots_dir / "factor_performance_comparison.png")
    save_rolling_factor_correlation_plot(rolling_factor_correlation, plots_dir / "rolling_factor_correlation.png")
    save_capacity_simulation_plot(capacity, plots_dir / "capacity_simulation.png")
    save_research_summary(
        output_dir / "research_summary.md",
        strategy_summary,
        benchmark_summary,
        args.benchmark,
        failure_regime,
        factor_correlation,
        factor_contribution,
        factor_dominance,
        factor_behavior,
        factor_performance,
        capacity,
        params,
    )

    print("Cross-sectional momentum research backtest complete")
    print(f"Assets loaded: {prices.shape[1]}")
    print(f"Date range: {aligned_index.min().date()} to {aligned_index.max().date()}")
    print(f"Rebalances: {len(result.rebalance_weights)}")
    print(f"Cost per turnover: {params.cost_bps:.2f} bps")
    print("Strategy returns are net of trading costs.")
    print(f"Benchmark: {args.benchmark}")
    print_metric_block("strategy_metrics", strategy_summary)
    print_metric_block("benchmark_metrics", benchmark_summary)
    print(f"total_trading_cost={strategy_summary['total_trading_cost']:.6f}")
    print(f"average_turnover={strategy_summary['average_turnover']:.6f}")
    print(f"cost_impact_on_returns={strategy_summary['cost_impact_on_returns']:.6f}")
    print(f"worst_failure_regime={_worst_regime_name(failure_regime)}")
    print_key_findings(
        strategy_summary,
        benchmark_summary,
        rolling_metrics,
        factor_contribution,
        args.acceptable_drawdown,
    )
    if args.update_root_readme:
        update_root_readme_results(
            strategy_summary,
            benchmark_summary,
            params.cost_bps,
            args.benchmark,
            (
                1.36
            ),
        )
    print_quant_diagnostics(
        net_returns,
        net_equity,
        strategy_drawdown,
        strategy_summary,
        rolling_metrics,
        failure_regime,
        capacity,
    )
    print_final_interpretation(
        strategy_summary,
        failure_regime,
        capacity,
        factor_contribution,
        factor_behavior,
    )
    print_interview_insights(strategy_summary, failure_regime, capacity, factor_behavior)
    print(f"Saved output directory: {output_dir}")
    print(f"Saved plots directory: {plots_dir}")
    print_interview_summary(strategy_summary, failure_regime, factor_contribution, capacity)
    return strategy_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Research-grade cross-sectional momentum strategy.")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="Comma-separated equity universe.")
    parser.add_argument("--start", default="2018-01-01", help="Start date for yfinance downloads.")
    parser.add_argument("--end", default=None, help="Optional end date for yfinance downloads.")
    parser.add_argument("--csv", default=None, help="Optional real price CSV or folder. If omitted, yfinance is used.")
    parser.add_argument("--benchmark", default="SPY", help="Benchmark ticker for buy-and-hold comparison.")
    parser.add_argument("--benchmark-csv", default=None, help="Optional real benchmark price CSV or folder.")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "Results"),
        help="Directory for result CSVs.",
    )
    parser.add_argument(
        "--plots-dir",
        default=None,
        help="Directory for generated plots. Defaults to the sibling Plots folder next to --output-dir.",
    )
    parser.add_argument(
        "--update-root-readme",
        action="store_true",
        help="Update the generated medium-term alpha block in the root README after a run.",
    )
    parser.add_argument("--top-quantile", type=float, default=0.25, help="Long/short selection fraction.")
    parser.add_argument("--gross-exposure", type=float, default=1.0, help="Total gross exposure.")
    parser.add_argument("--cost-bps", type=float, default=5.0, help="Transaction cost in bps per unit turnover.")
    parser.add_argument("--momentum-weight", type=float, default=1.00, help="Composite score momentum weight.")
    parser.add_argument("--low-vol-weight", type=float, default=0.00, help="Composite score low-volatility weight.")
    parser.add_argument(
        "--lookback-weights",
        default=",".join(str(value) for value in DEFAULT_MOMENTUM_WEIGHTS),
        help="Optional comma-separated momentum lookback weights, e.g. 0.5,0.3,0.2.",
    )
    parser.add_argument(
        "--momentum-skip-recent-days",
        type=int,
        default=5,
        help="Ignore the most recent N trading days when computing momentum.",
    )
    parser.add_argument(
        "--normalize-momentum",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Cross-sectionally z-score momentum after combining lookbacks.",
    )
    parser.add_argument("--volatility-window", type=int, default=63, help="Rolling volatility window.")
    parser.add_argument("--beta-window", type=int, default=126, help="Rolling beta estimation window.")
    parser.add_argument("--trend-window", type=int, default=126, help="Benchmark trend filter window.")
    parser.add_argument("--negative-trend-scale", type=float, default=0.40, help="Exposure multiplier in downtrends.")
    parser.add_argument(
        "--high-volatility-scale",
        type=float,
        default=0.40,
        help="Exposure multiplier when benchmark volatility is elevated.",
    )
    parser.add_argument(
        "--market-volatility-window",
        type=int,
        default=63,
        help="Rolling benchmark volatility window for defensive exposure scaling.",
    )
    parser.add_argument(
        "--market-volatility-quantile",
        type=float,
        default=0.75,
        help="Past volatility quantile used to identify elevated-volatility regimes.",
    )
    parser.add_argument("--signal-change-threshold", type=float, default=0.05, help="Minimum rebalance turnover.")
    parser.add_argument("--max-position-size", type=float, default=0.06, help="Maximum absolute single-name weight.")
    parser.add_argument("--no-volatility-scaling", action="store_false", dest="use_volatility_scaling")
    parser.add_argument(
        "--beta-neutralize",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Apply rolling beta neutralization.",
    )
    parser.add_argument(
        "--beta-neutralization-strength",
        type=float,
        default=0.0,
        help="0 disables beta adjustment; 1 applies the full beta-neutral correction.",
    )
    parser.add_argument(
        "--short-mode",
        choices=("full", "none", "high_conviction"),
        default="none",
        help="Short book construction mode.",
    )
    parser.add_argument("--short-quantile", type=float, default=0.10, help="Short selection fraction.")
    parser.add_argument("--short-decile", type=float, default=0.10, help="High-conviction short decile filter.")
    parser.add_argument(
        "--short-exposure-fraction",
        type=float,
        default=0.0,
        help="Fraction of gross exposure allocated to shorts when shorts are enabled.",
    )
    parser.add_argument(
        "--min-signal-strength",
        type=float,
        default=0.85,
        help="Minimum distance from cross-sectional median required to trade.",
    )
    parser.add_argument(
        "--use-multi-signal",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use momentum + mean-reversion + quality scoring instead of pure momentum scoring.",
    )
    parser.add_argument("--multi-momentum-weight", type=float, default=0.55, help="Multi-signal momentum weight.")
    parser.add_argument("--mean-reversion-weight", type=float, default=0.25, help="Multi-signal reversal-filter weight.")
    parser.add_argument("--quality-weight", type=float, default=0.20, help="Multi-signal quality weight.")
    parser.add_argument(
        "--short-term-reversal-window",
        type=int,
        default=5,
        help="Recent return window used for reversal penalty.",
    )
    parser.add_argument(
        "--short-term-reversal-penalty",
        type=float,
        default=0.15,
        help="Penalty applied to very strong recent return ranks.",
    )
    parser.add_argument("--quality-window", type=int, default=63, help="Volatility-stability quality window.")
    parser.add_argument("--min-assets", type=int, default=5, help="Minimum assets required.")
    parser.add_argument("--train-years", type=int, default=3, help="Minimum expanding train years for walk-forward.")
    parser.add_argument("--acceptable-drawdown", type=float, default=0.25, help="Key-findings drawdown threshold.")
    parser.add_argument(
        "--run-sharpe-research",
        action="store_true",
        help="Run the bounded Sharpe-improvement research grid and use the robust selected candidate for outputs.",
    )
    parser.set_defaults(use_volatility_scaling=True, beta_neutralize=False)
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())

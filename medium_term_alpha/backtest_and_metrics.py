from __future__ import annotations

import math

import pandas as pd


def equity_curve(returns: pd.Series) -> pd.Series:
    return (1.0 + returns.fillna(0.0)).cumprod().rename("equity")


def drawdown_curve(equity: pd.Series) -> pd.Series:
    running_peak = equity.cummax()
    return (equity / running_peak - 1.0).rename("drawdown")


def annualized_sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    returns = returns.dropna()
    if len(returns) < 2:
        return 0.0
    std = returns.std(ddof=1)
    if std == 0.0 or not math.isfinite(std):
        return 0.0
    return float((returns.mean() / std) * math.sqrt(periods_per_year))


def max_drawdown(drawdown: pd.Series) -> float:
    if drawdown.empty:
        return 0.0
    return float(drawdown.min())


def annualized_return(equity: pd.Series, periods_per_year: int = 252) -> float:
    equity = equity.dropna()
    if len(equity) < 2:
        return 0.0
    years = len(equity) / float(periods_per_year)
    if years <= 0.0:
        return 0.0
    return float(equity.iloc[-1] ** (1.0 / years) - 1.0)


def summarize_performance(
    returns: pd.Series,
    turnover: pd.Series | None = None,
    periods_per_year: int = 252,
) -> dict[str, float]:
    equity = equity_curve(returns)
    drawdown = drawdown_curve(equity)
    summary = {
        "total_return": float(equity.iloc[-1] - 1.0) if not equity.empty else 0.0,
        "annualized_return": annualized_return(equity, periods_per_year),
        "annualized_sharpe": annualized_sharpe(returns, periods_per_year),
        "max_drawdown": max_drawdown(drawdown),
        "daily_volatility": float(returns.std(ddof=1)) if len(returns.dropna()) > 1 else 0.0,
    }
    summary["annualized_volatility"] = summary["daily_volatility"] * math.sqrt(periods_per_year)
    if turnover is not None and not turnover.empty:
        summary["average_rebalance_turnover"] = float(turnover.mean())
    return summary


def rolling_sharpe(returns: pd.Series, window: int, periods_per_year: int = 252) -> pd.Series:
    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std()
    return ((mean / std) * math.sqrt(periods_per_year)).replace([float("inf"), float("-inf")], 0.0)


def rolling_return(returns: pd.Series, window: int) -> pd.Series:
    return (1.0 + returns.fillna(0.0)).rolling(window).apply(lambda values: values.prod() - 1.0, raw=True)


def rolling_drawdown(equity: pd.Series, window: int) -> pd.Series:
    rolling_peak = equity.rolling(window).max()
    return (equity / rolling_peak) - 1.0

from __future__ import annotations

import math

import pandas as pd


def _normalize_side(
    strengths: pd.Series,
    side_exposure: float,
    max_position_size: float,
) -> pd.Series:
    strengths = strengths.clip(lower=0.0).dropna()
    if strengths.empty or side_exposure <= 0.0:
        return pd.Series(0.0, index=strengths.index)

    if strengths.sum() <= 0.0:
        strengths = pd.Series(1.0, index=strengths.index)

    # Position caps prevent one unusually strong signal from dominating the book.
    target_exposure = min(side_exposure, max_position_size * len(strengths))
    weights = pd.Series(0.0, index=strengths.index)
    remaining = target_exposure
    active = strengths.copy()

    while not active.empty and remaining > 0.0:
        proposed = active / active.sum() * remaining
        capped = proposed[proposed > max_position_size]
        if capped.empty:
            weights.loc[active.index] = proposed
            break
        weights.loc[capped.index] = max_position_size
        remaining = target_exposure - weights.sum()
        active = active.drop(index=capped.index)

    return weights


def _rescale_to_gross(
    weights: pd.Series,
    target_gross: float,
    max_position_size: float,
) -> pd.Series:
    if target_gross <= 0.0 or weights.abs().sum() <= 0.0:
        return weights * 0.0
    scaled = weights * (target_gross / weights.abs().sum())
    scaled = scaled.clip(lower=-max_position_size, upper=max_position_size)
    gross = scaled.abs().sum()
    if gross > 0.0 and gross < target_gross:
        scaled = (scaled * (target_gross / gross)).clip(
            lower=-max_position_size,
            upper=max_position_size,
        )
    return scaled


def _beta_neutralize(
    weights: pd.Series,
    betas: pd.Series,
    target_gross: float,
    max_position_size: float,
    strength: float = 1.0,
) -> pd.Series:
    selected = weights[weights != 0.0].index
    if selected.empty or strength <= 0.0:
        return weights

    beta_values = betas.reindex(selected).fillna(1.0)
    portfolio_beta = float((weights.reindex(selected) * beta_values).sum())
    denominator = float((beta_values * beta_values).sum())
    if denominator <= 0.0:
        return weights

    # Beta neutralization reduces broad market exposure so returns are driven more by stock selection.
    adjusted = weights.copy()
    adjusted.loc[selected] = adjusted.loc[selected] - (strength * (portfolio_beta / denominator) * beta_values)
    adjusted.loc[weights == 0.0] = 0.0
    return _rescale_to_gross(adjusted, target_gross, max_position_size)


def build_long_short_weights(
    scores: pd.DataFrame,
    top_quantile: float = 0.20,
    gross_exposure: float = 1.0,
    asset_volatility: pd.DataFrame | None = None,
    beta: pd.DataFrame | None = None,
    market_regime_scale: pd.Series | None = None,
    signal_change_threshold: float = 0.10,
    max_position_size: float = 0.20,
    use_volatility_scaling: bool = True,
    beta_neutralize: bool = True,
    beta_neutralization_strength: float = 1.0,
    short_mode: str = "full",
    short_quantile: float | None = None,
    short_allowed: pd.DataFrame | None = None,
    short_exposure_fraction: float = 0.50,
    min_signal_strength: float = 0.0,
) -> pd.DataFrame:
    """Long top-ranked assets and short bottom-ranked assets at each rebalance."""
    if short_mode not in {"full", "none", "high_conviction"}:
        raise ValueError("short_mode must be one of: full, none, high_conviction.")

    weights = pd.DataFrame(0.0, index=scores.index, columns=scores.columns)
    previous_weights = pd.Series(0.0, index=scores.columns)

    for date, row in scores.iterrows():
        valid = row.dropna()
        if len(valid) < 2:
            weights.loc[date] = previous_weights
            continue

        count = max(1, int(math.ceil(len(valid) * top_quantile)))
        count = min(count, len(valid) // 2)
        if count == 0:
            continue

        ranked = valid.sort_values()
        active_short_quantile = short_quantile if short_quantile is not None else top_quantile
        short_count = max(1, int(math.ceil(len(valid) * active_short_quantile)))
        short_count = min(short_count, len(valid) // 2)

        shorts = ranked.index[:short_count]
        longs = ranked.index[-count:]

        median_score = float(valid.median())
        if min_signal_strength > 0.0:
            # Signal gates stop the portfolio from paying turnover on middle-ranked names.
            longs = valid.loc[longs][valid.loc[longs] >= median_score + min_signal_strength].index
            shorts = valid.loc[shorts][valid.loc[shorts] <= median_score - min_signal_strength].index

        if short_mode == "none":
            shorts = pd.Index([])
        elif short_mode == "high_conviction" and short_allowed is not None and date in short_allowed.index:
            allowed_row = short_allowed.loc[date].reindex(shorts).fillna(False)
            shorts = pd.Index([ticker for ticker in shorts if bool(allowed_row.loc[ticker])])

        scale = 1.0
        if market_regime_scale is not None and date in market_regime_scale.index:
            scale = float(market_regime_scale.loc[date])
        # In negative market regimes, the assumption is that lower gross exposure improves survival.
        target_gross = gross_exposure * max(0.0, scale)
        if short_mode == "none" or len(shorts) == 0:
            long_side_exposure = target_gross
            short_side_exposure = 0.0
        else:
            short_side_exposure = target_gross * max(0.0, min(1.0, short_exposure_fraction))
            long_side_exposure = target_gross - short_side_exposure

        long_strength = valid.loc[longs] - valid.loc[longs].min() + 1e-6
        short_strength = valid.loc[shorts].max() - valid.loc[shorts] + 1e-6

        if use_volatility_scaling and asset_volatility is not None and date in asset_volatility.index:
            # Inverse-vol scaling avoids letting volatile names consume too much risk.
            vol_row = asset_volatility.loc[date].replace(0.0, float("nan"))
            long_strength = long_strength * (1.0 / vol_row.reindex(longs).astype(float)).fillna(0.0)
            short_strength = short_strength * (1.0 / vol_row.reindex(shorts).astype(float)).fillna(0.0)

        proposed = pd.Series(0.0, index=scores.columns)
        proposed.loc[longs] = _normalize_side(long_strength, long_side_exposure, max_position_size)
        proposed.loc[shorts] = -_normalize_side(short_strength, short_side_exposure, max_position_size)

        if beta_neutralize and beta is not None and date in beta.index:
            proposed = _beta_neutralize(
                proposed,
                beta.loc[date],
                target_gross=target_gross,
                max_position_size=max_position_size,
                strength=beta_neutralization_strength,
            )

        signal_change = float((proposed - previous_weights).abs().sum())
        if signal_change_threshold > 0.0 and signal_change < signal_change_threshold:
            # Turnover gating accepts stale weights when the signal change is too small to justify cost.
            weights.loc[date] = previous_weights
        else:
            weights.loc[date] = proposed
            previous_weights = proposed

    return weights


def align_daily_weights(rebalance_weights: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill rebalance weights and shift one day to avoid lookahead bias."""
    daily_weights = rebalance_weights.reindex(returns.index).ffill().fillna(0.0)
    # The one-period shift is the core anti-lookahead assumption in the daily backtest.
    return daily_weights.shift(1).fillna(0.0)


def compute_strategy_returns(
    asset_returns: pd.DataFrame,
    rebalance_weights: pd.DataFrame,
    cost_per_turnover_bps: float = 0.0,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.DataFrame, pd.Series]:
    daily_weights = align_daily_weights(rebalance_weights, asset_returns)
    gross_returns = (daily_weights * asset_returns).sum(axis=1).rename("gross_strategy_return")
    daily_turnover = daily_weights.diff().abs().sum(axis=1).fillna(0.0).rename("turnover")
    if not daily_turnover.empty:
        daily_turnover.iloc[0] = daily_weights.iloc[0].abs().sum()
    # Costs are charged on turnover so high-churn parameter choices are penalized directly.
    trading_cost = (daily_turnover * (cost_per_turnover_bps / 10000.0)).rename("trading_cost")
    net_returns = (gross_returns - trading_cost).rename("strategy_return")
    return gross_returns, trading_cost, net_returns, daily_weights, daily_turnover


def compute_long_short_returns(
    asset_returns: pd.DataFrame,
    daily_weights: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    long_returns = (daily_weights.clip(lower=0.0) * asset_returns).sum(axis=1)
    short_returns = (daily_weights.clip(upper=0.0) * asset_returns).sum(axis=1)
    return long_returns.rename("long_return"), short_returns.rename("short_return")


def compute_turnover(rebalance_weights: pd.DataFrame) -> pd.Series:
    turnover = rebalance_weights.diff().abs().sum(axis=1)
    if not turnover.empty:
        turnover.iloc[0] = rebalance_weights.iloc[0].abs().sum()
    return turnover.rename("turnover")

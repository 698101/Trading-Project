from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_TICKERS = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "GOOG",
    "META",
    "NVDA",
    "TSLA",
    "AVGO",
    "AMD",
    "NFLX",
    "CRM",
    "ORCL",
    "ADBE",
    "QCOM",
    "TXN",
    "IBM",
    "CSCO",
    "NOW",
    "INTU",
    "AMAT",
    "LRCX",
    "MU",
    "PANW",
    "INTC",
    "JPM",
    "BAC",
    "WFC",
    "GS",
    "MS",
    "C",
    "V",
    "MA",
    "AXP",
    "XOM",
    "CVX",
    "COP",
    "SLB",
    "EOG",
    "UNH",
    "JNJ",
    "LLY",
    "MRK",
    "ABBV",
    "PFE",
    "TMO",
    "ABT",
    "GILD",
    "PG",
    "COST",
    "WMT",
    "HD",
    "MCD",
    "NKE",
    "KO",
    "PEP",
    "DIS",
    "CAT",
    "GE",
    "HON",
    "BA",
    "UPS",
    "RTX",
    "LIN",
    "NEE",
]


def _clean_prices(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.copy()
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()
    prices = prices.apply(pd.to_numeric, errors="coerce")
    prices = prices.dropna(axis=1, how="all")
    prices = prices.ffill().dropna(how="all")
    return prices


def _price_column(columns: Iterable[str]) -> str:
    normalized = {str(col).strip().lower(): str(col) for col in columns}
    for candidate in ("adj close", "adj_close", "adjusted_close", "close"):
        if candidate in normalized:
            return normalized[candidate]
    raise ValueError("CSV must contain an adjusted close or close price column.")


def _read_single_ticker_csv(path: Path, ticker: str) -> pd.Series:
    frame = pd.read_csv(path)
    date_col = next((col for col in frame.columns if str(col).strip().lower() in {"date", "timestamp"}), None)
    if date_col is None:
        raise ValueError(f"{path} must contain a Date or timestamp column.")
    price_col = _price_column(frame.columns)
    series = frame[[date_col, price_col]].copy()
    series[date_col] = pd.to_datetime(series[date_col])
    series = series.set_index(date_col).sort_index()
    return pd.to_numeric(series[price_col], errors="coerce").rename(ticker)


def load_prices_from_csv(path: str | Path, tickers: list[str] | None = None) -> pd.DataFrame:
    """Load real adjusted-close prices from a wide CSV, long CSV, or per-ticker CSV folder."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"CSV path does not exist: {source}")

    if source.is_dir():
        if not tickers:
            tickers = sorted(p.stem.upper() for p in source.glob("*.csv"))
        series = []
        for ticker in tickers:
            candidates = [
                source / f"{ticker}.csv",
                source / f"{ticker.lower()}.csv",
                source / f"{ticker.upper()}.csv",
            ]
            match = next((candidate for candidate in candidates if candidate.exists()), None)
            if match is not None:
                series.append(_read_single_ticker_csv(match, ticker))
        if not series:
            raise ValueError(f"No ticker CSV files found in {source}")
        return _clean_prices(pd.concat(series, axis=1))

    frame = pd.read_csv(source)
    date_col = next((col for col in frame.columns if str(col).strip().lower() in {"date", "timestamp"}), None)
    if date_col is not None:
        frame[date_col] = pd.to_datetime(frame[date_col])

    symbol_col = next((col for col in frame.columns if str(col).strip().lower() in {"symbol", "ticker"}), None)
    if symbol_col is not None and date_col is not None:
        price_col = _price_column(frame.columns)
        prices = frame.pivot(index=date_col, columns=symbol_col, values=price_col)
        if tickers:
            prices = prices[[ticker for ticker in tickers if ticker in prices.columns]]
        return _clean_prices(prices)

    if date_col is not None:
        frame = frame.set_index(date_col)
    else:
        frame = frame.set_index(frame.columns[0])

    if tickers:
        available = [ticker for ticker in tickers if ticker in frame.columns]
        frame = frame[available]
    return _clean_prices(frame)


def load_prices_from_yfinance(tickers: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    """Download real adjusted-close data from Yahoo Finance via yfinance."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError(
            "yfinance is required for online downloads. Install it or pass --csv with real price data."
        ) from exc

    raw = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
    )
    if raw.empty:
        raise ValueError("yfinance returned no data. Check tickers, dates, and network access.")

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            prices = raw["Close"]
        elif "Adj Close" in raw.columns.get_level_values(0):
            prices = raw["Adj Close"]
        else:
            raise ValueError("Could not find Close prices in yfinance response.")
    else:
        if "Close" not in raw.columns:
            raise ValueError("Could not find Close prices in yfinance response.")
        prices = raw[["Close"]].rename(columns={"Close": tickers[0]})

    return _clean_prices(prices)


def load_prices(
    tickers: list[str] | None = None,
    start: str = "2018-01-01",
    end: str | None = None,
    csv_path: str | Path | None = None,
    min_assets: int = 5,
) -> pd.DataFrame:
    tickers = tickers or DEFAULT_TICKERS
    prices = (
        load_prices_from_csv(csv_path, tickers)
        if csv_path is not None
        else load_prices_from_yfinance(tickers, start, end)
    )

    prices = prices[[col for col in prices.columns if prices[col].notna().sum() > 0]]
    if prices.shape[1] < min_assets:
        raise ValueError(
            f"Need at least {min_assets} assets with real prices; loaded {prices.shape[1]}."
        )
    return prices


def load_benchmark(
    ticker: str = "SPY",
    start: str = "2018-01-01",
    end: str | None = None,
    csv_path: str | Path | None = None,
) -> pd.Series:
    if csv_path is not None:
        prices = load_prices_from_csv(csv_path, [ticker])
    else:
        prices = load_prices_from_yfinance([ticker], start, end)

    if ticker in prices.columns:
        return prices[ticker].rename(ticker)
    if prices.shape[1] == 1:
        return prices.iloc[:, 0].rename(ticker)
    raise ValueError(f"Benchmark ticker {ticker} was not found in loaded price data.")

# ---- Signal engineering functions flattened from signals.py ----

import math

import pandas as pd


LOOKBACK_WINDOWS = (21, 63, 126)
DEFAULT_MOMENTUM_WEIGHTS = (0.5, 0.3, 0.2)


def compute_rolling_returns(
    prices: pd.DataFrame,
    lookbacks: tuple[int, ...] = LOOKBACK_WINDOWS,
    skip_recent_days: int = 0,
) -> dict[int, pd.DataFrame]:
    """Compute close-to-close rolling returns for each lookback window."""
    signal_prices = prices.shift(skip_recent_days) if skip_recent_days > 0 else prices
    return {window: signal_prices.pct_change(window) for window in lookbacks}


def _cross_sectional_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    row_mean = frame.mean(axis=1)
    row_std = frame.std(axis=1).replace(0.0, float("nan"))
    return frame.sub(row_mean, axis=0).div(row_std, axis=0)


def compute_momentum_scores(
    prices: pd.DataFrame,
    lookbacks: tuple[int, ...] = LOOKBACK_WINDOWS,
    lookback_weights: tuple[float, ...] | None = None,
    skip_recent_days: int = 0,
    normalize_scores: bool = False,
) -> pd.DataFrame:
    """Rank assets cross-sectionally and combine ranks into one momentum score."""
    rolling_returns = compute_rolling_returns(prices, lookbacks, skip_recent_days)

    if lookback_weights is not None:
        if len(lookback_weights) != len(lookbacks):
            raise ValueError("lookback_weights must match the number of lookback windows.")
        total_weight = sum(lookback_weights)
        if total_weight <= 0.0:
            raise ValueError("lookback_weights must have positive total weight.")
        weighted = sum(
            rolling_returns[window] * (weight / total_weight)
            for window, weight in zip(lookbacks, lookback_weights)
        )
        # Cross-sectional normalization keeps signal strength comparable through time.
        scores = _cross_sectional_zscore(weighted)
        return scores.dropna(how="all")

    # Percentile ranks make signals comparable across assets and lookback windows.
    percentile_ranks = [
        returns.rank(axis=1, ascending=True, pct=True)
        for returns in rolling_returns.values()
    ]
    scores = sum(percentile_ranks) / float(len(percentile_ranks))
    if normalize_scores:
        scores = _cross_sectional_zscore(scores)
    return scores.dropna(how="all")


def compute_high_conviction_short_filter(
    prices: pd.DataFrame,
    lookbacks: tuple[int, ...] = LOOKBACK_WINDOWS,
    skip_recent_days: int = 0,
    decile: float = 0.10,
) -> pd.DataFrame:
    """Require an asset to be in the bottom decile across every momentum horizon."""
    rolling_returns = compute_rolling_returns(prices, lookbacks, skip_recent_days)
    filters = [
        returns.rank(axis=1, ascending=True, pct=True) <= decile
        for returns in rolling_returns.values()
    ]
    allowed = filters[0]
    for frame in filters[1:]:
        allowed = allowed & frame
    return allowed.fillna(False)


def compute_mean_reversion_scores(
    prices: pd.DataFrame,
    momentum_scores: pd.DataFrame,
    short_term_window: int = 5,
    reversal_penalty: float = 0.20,
) -> pd.DataFrame:
    """Penalize overextended names while preserving the medium-term trend signal."""
    short_term_return = prices.pct_change(short_term_window)
    # High recent-return ranks are penalized because very stretched names often mean-revert.
    short_term_rank = short_term_return.rank(axis=1, ascending=True, pct=True)
    short_term_rank = _cross_sectional_zscore(short_term_rank)

    common_index = momentum_scores.index.intersection(short_term_rank.index)
    common_columns = momentum_scores.columns.intersection(short_term_rank.columns)
    mean_reversion = (
        momentum_scores.loc[common_index, common_columns] -
        (reversal_penalty * short_term_rank.loc[common_index, common_columns])
    )
    return _cross_sectional_zscore(mean_reversion).dropna(how="all")


def compute_rolling_volatility(prices: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    """Annualized rolling volatility per asset."""
    returns = prices.pct_change()
    return returns.rolling(window).std() * math.sqrt(252.0)


def compute_low_volatility_scores(prices: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    """Rank lower-volatility assets higher cross-sectionally."""
    volatility = compute_rolling_volatility(prices, window)
    # Low-vol acts as a stabilizer, assuming less noisy winners are more investable.
    return volatility.rank(axis=1, ascending=False, pct=True).dropna(how="all")


def compute_quality_scores(
    prices: pd.DataFrame,
    volatility_window: int = 21,
    stability_window: int = 63,
) -> pd.DataFrame:
    """Approximate quality as stable realized volatility through time."""
    returns = prices.pct_change()
    rolling_volatility = returns.rolling(volatility_window).std()
    volatility_instability = rolling_volatility.rolling(stability_window).std()
    # Stable volatility is a low-complexity proxy for more consistent trend behavior.
    quality_rank = volatility_instability.rank(axis=1, ascending=False, pct=True)
    return _cross_sectional_zscore(quality_rank).dropna(how="all")


def compute_composite_scores(
    prices: pd.DataFrame,
    momentum_weight: float = 0.70,
    low_vol_weight: float = 0.30,
    lookbacks: tuple[int, ...] = LOOKBACK_WINDOWS,
    lookback_weights: tuple[float, ...] | None = None,
    momentum_skip_recent_days: int = 0,
    normalize_momentum: bool = False,
    volatility_window: int = 63,
    use_multi_signal: bool = False,
    multi_momentum_weight: float = 0.70,
    mean_reversion_weight: float = 0.20,
    quality_weight: float = 0.10,
    short_term_reversal_window: int = 5,
    short_term_reversal_penalty: float = 0.20,
    quality_window: int = 63,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Combine cross-sectional momentum and low-volatility ranks."""
    momentum = compute_momentum_scores(
        prices,
        lookbacks,
        lookback_weights=lookback_weights,
        skip_recent_days=momentum_skip_recent_days,
        normalize_scores=normalize_momentum,
    )
    low_vol = compute_low_volatility_scores(prices, volatility_window)
    common_index = momentum.index.intersection(low_vol.index)
    common_columns = momentum.columns.intersection(low_vol.columns)
    momentum = momentum.loc[common_index, common_columns]
    low_vol = low_vol.loc[common_index, common_columns]

    if use_multi_signal:
        mean_reversion = compute_mean_reversion_scores(
            prices[common_columns],
            momentum,
            short_term_window=short_term_reversal_window,
            reversal_penalty=short_term_reversal_penalty,
        )
        quality = compute_quality_scores(
            prices[common_columns],
            volatility_window=max(5, min(volatility_window, 21)),
            stability_window=quality_window,
        )
        common_index = momentum.index.intersection(mean_reversion.index).intersection(quality.index)
        common_columns = momentum.columns.intersection(mean_reversion.columns).intersection(quality.columns)
        momentum = momentum.loc[common_index, common_columns]
        low_vol = low_vol.loc[common_index, common_columns]
        mean_reversion = mean_reversion.loc[common_index, common_columns]
        quality = quality.loc[common_index, common_columns]

        total_weight = multi_momentum_weight + mean_reversion_weight + quality_weight
        if total_weight <= 0.0:
            raise ValueError("Multi-signal weights must have positive total weight.")
        final_score = (
            (multi_momentum_weight * momentum) +
            (mean_reversion_weight * mean_reversion) +
            (quality_weight * quality)
        ) / total_weight
        composite = _cross_sectional_zscore(final_score)
        asset_volatility = compute_rolling_volatility(prices[common_columns], volatility_window)
        return composite.dropna(how="all"), momentum, low_vol, asset_volatility

    total_weight = momentum_weight + low_vol_weight
    if total_weight <= 0.0:
        raise ValueError("At least one factor weight must be positive.")

    # Composite scoring keeps the model interpretable: no black box, just explicit factor weights.
    composite = (
        (momentum * momentum_weight) +
        (low_vol * low_vol_weight)
    ) / total_weight
    asset_volatility = compute_rolling_volatility(prices[common_columns], volatility_window)
    return composite.dropna(how="all"), momentum, low_vol, asset_volatility


def compute_rolling_beta(
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    window: int = 126,
) -> pd.DataFrame:
    """Estimate rolling asset beta versus the benchmark using daily returns."""
    asset_returns = prices.pct_change()
    benchmark_returns = benchmark_prices.reindex(prices.index).ffill().pct_change()
    benchmark_variance = benchmark_returns.rolling(window).var()
    betas = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    for column in prices.columns:
        # Beta estimates support market-neutral construction rather than directional market bets.
        covariance = asset_returns[column].rolling(window).cov(benchmark_returns)
        betas[column] = covariance / benchmark_variance
    return betas.replace([float("inf"), float("-inf")], float("nan")).fillna(1.0)


def compute_market_regime_scale(
    benchmark_prices: pd.Series,
    index: pd.DatetimeIndex,
    trend_window: int = 126,
    negative_trend_scale: float = 0.50,
    high_volatility_scale: float = 1.0,
    volatility_window: int = 63,
    volatility_quantile: float = 0.75,
) -> pd.Series:
    """Reduce gross exposure when benchmark trend is negative or volatility is elevated."""
    aligned = benchmark_prices.reindex(index).ffill()
    trend_return = aligned.pct_change(trend_window)
    scale = pd.Series(1.0, index=index, name="market_regime_scale")
    # This assumes broad downtrends are hostile to long-short momentum capacity and liquidity.
    scale.loc[trend_return < 0.0] = negative_trend_scale
    if high_volatility_scale < 1.0:
        returns = aligned.pct_change()
        realized_volatility = returns.rolling(volatility_window).std().shift(1)
        threshold = realized_volatility.expanding(min_periods=volatility_window).quantile(volatility_quantile)
        scale.loc[realized_volatility > threshold] = scale.loc[realized_volatility > threshold].clip(
            upper=high_volatility_scale
        )
    return scale.fillna(1.0)


def monthly_rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Use the last available trading day of each month as the rebalance date."""
    dates = pd.Series(index=index, data=index)
    return pd.DatetimeIndex(dates.groupby(index.to_period("M")).max())


def rebalance_scores(scores: pd.DataFrame) -> pd.DataFrame:
    dates = monthly_rebalance_dates(scores.index)
    available_dates = dates.intersection(scores.index)
    return scores.loc[available_dates].dropna(how="all")

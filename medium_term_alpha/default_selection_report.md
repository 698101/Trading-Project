# Sharpe-Improvement Research Pass

This report records a bounded parameter search, not a guarantee of optimized future performance.
The selected default is chosen using Sharpe, drawdown, turnover, cost impact, benchmark comparison, and fixed-parameter year-by-year stability.

## Current Baseline

- Sharpe: 1.3968
- Annual return: 0.2264
- Total return: 4.4642
- Max drawdown: -0.2213
- Average turnover: 0.7051
- Total trading cost: 0.0331

## Best Raw Sharpe Candidate

- Candidate ID: 1099
- Sharpe: 1.4591
- Total return: 2.5974
- Max drawdown: -0.1551
- Turnover: 0.4961
- Trading cost: 0.0233
- Local median Sharpe: 1.3399

## Selected Robust Candidate

- Candidate ID: 3670
- Sharpe: 1.4505
- Benchmark Sharpe: 0.8030
- Annual return: 0.1890
- Total return: 3.2241
- Max drawdown: -0.1564
- Daily volatility: 0.0079
- Annualized volatility: 0.1248
- Average turnover: 0.5999
- Total trading cost: 0.0282
- Local median Sharpe: 1.3516
- Local minimum Sharpe: 1.2840

## Selected Parameters

- min_signal_strength: 0.8500
- top_quantile: 0.2500
- signal_change_threshold: 0.0500
- max_position_size: 0.0600
- negative_trend_scale: 0.4000
- high_volatility_scale: 0.4000
- short_term_reversal_penalty: 0.1500
- multi_momentum_weight: 0.5500
- mean_reversion_weight: 0.2500
- quality_weight: 0.2000

## Why This Candidate Was Chosen

- It improves Sharpe versus the baseline while preserving realistic costs and turnover.
- It keeps drawdown within the allowed robustness band.
- It still beats SPY on total return and Sharpe.
- Nearby grid settings remain stable enough to avoid selecting a narrow one-point result.
- It is not chosen purely by maximum in-sample Sharpe; fragile candidates remain visible in the grid output.

## Trade-Offs

- Higher signal thresholds and smaller position caps reduce weaker trades and concentration.
- More defensive regime scaling can smooth returns but may reduce upside in strong markets.
- Annual return and total return are lower than the previous baseline, but drawdown, turnover, cost, and Sharpe improve while still beating SPY.
- The selected configuration remains directional long-only because the short book has not proven robust standalone value.

## Sharpe Target Read

The selected candidate improved Sharpe but did not reach the ~1.7 target.

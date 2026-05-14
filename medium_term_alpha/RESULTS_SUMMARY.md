# Medium-Term Alpha Results Summary

This note summarizes the saved selected-default run in `Results/`. Metrics are net of transaction costs where applicable and are compared against SPY using the saved benchmark comparison file.

## Research Setup

- Objective: build an interpretable 1-12 week cross-sectional equity alpha strategy.
- Universe: liquid large-cap US equities from the project default list, or a supplied CSV.
- Benchmark: SPY.
- Rebalance cadence: monthly.
- Signal families: multi-horizon momentum, short-term reversal penalty, and quality/volatility stability.
- Cost model: 5 bps per unit turnover.
- Lookahead control: portfolio weights are shifted one day before return calculation.

## Selected Default Configuration

| Parameter | Value |
|---|---:|
| Minimum signal strength | 0.85 |
| Top quantile | 0.25 |
| Signal change threshold | 0.05 |
| Max position size | 0.06 |
| Negative trend scale | 0.40 |
| High volatility scale | 0.40 |
| Momentum weight | 0.55 |
| Mean-reversion weight | 0.25 |
| Quality weight | 0.20 |

The configuration is selected from a bounded research grid using Sharpe, drawdown, turnover, cost impact, benchmark comparison, walk-forward stability, and local sensitivity. It is not selected purely by maximum in-sample Sharpe.

## Headline Metrics

| Metric | Strategy | SPY |
|---|---:|---:|
| Annualized Sharpe | 1.4505 | 0.8030 |
| Annualized Return | 18.90% | 14.57% |
| Total Return | 322.41% | 210.21% |
| Max Drawdown | -15.64% | -33.72% |
| Daily Volatility | 0.786% | 1.213% |
| Annualized Volatility | 12.48% | 19.26% |
| Average Turnover | 0.5999 | n/a |
| Total Trading Cost | 2.82% | n/a |

The selected strategy beats SPY on total return and annualized Sharpe in the saved run, with lower max drawdown and lower annualized volatility. This is historical research evidence, not a forward guarantee.

## Robustness Scorecard

`Results/medium_alpha_robustness_report.md` is generated from the saved result artifacts without retuning parameters. It adds bootstrap intervals, a sign-flip negative control, and explicit pass/warn/fail checks.

| Category | Check | Value | Status |
|---|---|---:|---|
| Headline | Annualized Sharpe | 1.4505 | Pass |
| Benchmark | Sharpe spread vs SPY | 0.6475 | Pass |
| Inference | Monthly bootstrap Sharpe 95% CI lower bound | 0.8931 | Pass |
| Negative control | Sign-flip p-value, Sharpe >= observed | 0.0000 | Pass |
| Walk-forward | Expanding-window positive Sharpe years | 5/6 | Pass |
| Walk-forward | Selected-candidate positive Sharpe years | 8/9 | Pass |
| Sensitivity | Local grid minimum Sharpe | 1.4031 | Pass |
| Costs | Selected 10 bps cost Sharpe | 1.4236 | Pass |
| Capacity | 20x cost-proxy Sharpe | 1.3568 | Pass |
| Factor risk | Momentum dominance share | 1.0000 | Warn |
| Data hygiene | Point-in-time universe | not available | Fail |
| Audit | Full selected-default holdings | not pinned | Warn |

The monthly bootstrap uses `monthly_results.csv`, so its observed monthly annualized Sharpe differs from the daily headline Sharpe in `results_summary.csv`. The sign-flip control preserves monthly return magnitudes and randomizes signs; it is a falsification check, not a replacement for signal-shuffle tests on raw prices.

## Walk-Forward Results

Saved expanding-window walk-forward tests:

| Test Period | Total Return | Annualized Return | Sharpe | Max Drawdown |
|---|---:|---:|---:|---:|
| 2021 | 25.31% | 25.31% | 1.475 | -7.07% |
| 2022 | -6.99% | -7.02% | -0.605 | -13.74% |
| 2023 | 26.75% | 26.99% | 2.236 | -6.76% |
| 2024 | 25.49% | 25.49% | 1.607 | -9.99% |
| 2025 | 9.87% | 9.95% | 0.766 | -13.37% |
| 2026 partial | 14.65% | 49.26% | 3.142 | -4.55% |

`Results/selected_default_metrics.csv` also records 8 positive Sharpe years out of 9 for the selected candidate, with a worst walk-forward year Sharpe of -0.605. The weak 2022 result is retained in the evidence rather than filtered out.

## Sensitivity Interpretation

At the base 5 bps cost setting, the saved top-quantile sensitivity remains in a narrow Sharpe range:

| Top Quantile | Total Return | Sharpe | Max Drawdown | Avg Turnover |
|---:|---:|---:|---:|---:|
| 0.15 | 277.21% | 1.429 | -13.35% | 0.5439 |
| 0.20 | 309.49% | 1.441 | -15.77% | 0.5887 |
| 0.25 | 322.41% | 1.451 | -15.64% | 0.5999 |

For the selected 0.25 top quantile, increasing costs from 2 bps to 10 bps lowers Sharpe from 1.467 to 1.424 and total return from 329.60% to 310.68%. The cost sensitivity is visible but does not erase the saved benchmark-relative advantage.

## Capacity Interpretation

`Results/capacity_simulation.csv` stress-tests the strategy through higher effective costs:

| Capital Scale | Effective Cost | Total Return | Sharpe | Max Drawdown |
|---:|---:|---:|---:|---:|
| 1x | 5.00 bps | 322.41% | 1.451 | -15.64% |
| 10x | 15.81 bps | 297.46% | 1.392 | -16.16% |
| 20x | 22.36 bps | 283.06% | 1.357 | -16.47% |

This is a simple cost-stress proxy, not a calibrated market-impact model. It is useful for showing whether the result is extremely fragile to cost increases.

## Factor And Regime Diagnostics

`Results/factor_behavior_summary.csv` shows momentum-dominance share of 1.0 in the saved diagnostic, with rolling factor correlation averaging -0.064 and ranging from -0.448 to 0.382. The interpretation is that the selected run remains primarily momentum-driven, while the reversal and quality components act as filters rather than independent factor sleeves.

## Portfolio Audit Files

The project now saves audit CSVs from the backtest internals. The committed versions are generated from `Results/sample_prices.csv`, which means they verify the audit trail and export schema without being presented as the full selected-default holding history.

| File | What A Reviewer Can Inspect |
|---|---|
| `Results/portfolio_weights.csv` | Rebalance-date ticker weights, final signal values, volatility inputs, inverse-volatility scores, and selected flags |
| `Results/rebalance_log.csv` | Selected tickers, position count, gross exposure, turnover, estimated trading cost, regime scale, and top signal per rebalance |
| `Results/daily_strategy_returns.csv` | Gross strategy return, net strategy return, benchmark return, turnover, trading cost, and cumulative net return |
| `Results/benchmark_timeseries.csv` | Benchmark return and cumulative benchmark return from the same sample run |
| `Results/full_selected_default_audit_status.md` | Exact status of the full holdings audit gap and the command for exporting it from a pinned full price panel |

Costs are charged as `turnover * 5 bps / 10000`, and the audit exports make the turnover/cost path inspectable instead of only reporting aggregate cost totals.
The full selected-default audit path is now scripted in `scripts/export_medium_alpha_selected_audit.py`; it requires a pinned full price panel because summary CSVs cannot reconstruct historical holdings or signal inputs.

## Reviewer-Facing Files

- `Results/results_summary.csv`
- `Results/benchmark_comparison.csv`
- `Results/selected_default_metrics.csv`
- `Results/walk_forward_results.csv`
- `Results/sensitivity_results.csv`
- `Results/capacity_simulation.csv`
- `Results/factor_behavior_summary.csv`
- `Results/monthly_results.csv`
- `Results/medium_alpha_bootstrap_ci.csv`
- `Results/medium_alpha_negative_controls.csv`
- `Results/medium_alpha_robustness_scorecard.csv`
- `Results/medium_alpha_robustness_report.md`
- `Results/portfolio_weights.csv`
- `Results/rebalance_log.csv`
- `Results/daily_strategy_returns.csv`
- `Results/benchmark_timeseries.csv`
- `Results/full_selected_default_audit_status.md`
- `Plots/medium_term_alpha_report.png`
- `Plots/cumulative_returns.png`
- `Plots/drawdown.png`
- `Plots/rolling_sharpe.png`
- `Plots/annual_returns.png`
- `Plots/walk_forward_yearly_performance.png`
- `Plots/cost_capacity_sensitivity.png`
- `Plots/bootstrap_negative_control.png`
- `Plots/turnover_holdings_concentration.png`
- `Plots/factor_diagnostics.png`

The current dark reviewer plots keep the main performance visuals tied to full saved evidence: `cumulative_returns.png` uses full monthly strategy equity plus saved strategy/SPY total-return bars, and `drawdown.png` uses full monthly strategy drawdown plus saved strategy/SPY max-drawdown bars. Holdings and turnover plots remain sample-audit views until a pinned full holdings panel is supplied.

## Limitations

- The default universe is not point-in-time and may contain survivorship bias.
- The saved factor diagnostics are momentum-dominated, so the result should not be presented as a diversified multi-factor edge.
- Online data availability and data-cleaning differences can affect full-run metrics.
- The committed holdings and benchmark time-series audit files are generated from the fixed sample run, not from the excluded/full online selected-default dataset; `scripts/export_medium_alpha_selected_audit.py` is the reproducible path once a pinned full data snapshot is supplied.
- Capacity analysis is a cost-stress approximation, not a full liquidity/impact model.
- Negative controls are based on saved return artifacts; stronger signal-shuffle tests require a pinned full price panel.
- The strategy is not a live execution system and does not model broker routing, borrow, or tax effects.
- Historical results do not guarantee future performance.

## Next Improvements

- Use a point-in-time, delisting-aware universe.
- Run `scripts/export_medium_alpha_selected_audit.py` against a pinned full data snapshot and retain the resulting manifest plus holdings audit.
- Calibrate costs and capacity assumptions from execution data.
- Expand validation across additional universes and regimes without per-year or per-ticker tuning.

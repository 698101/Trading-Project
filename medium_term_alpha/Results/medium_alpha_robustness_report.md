# Medium-Alpha Robustness Report

This report summarizes saved medium-term alpha evidence. It does not retune parameters.

## Baseline

| Metric | Strategy | SPY |
| --- | ---: | ---: |
| Annualized Sharpe | 1.4505 | 0.8030 |
| Annualized Return | 0.1890 | 0.1457 |
| Total Return | 3.2241 | 2.1021 |
| Max Drawdown | -0.1564 | -0.3372 |

## Bootstrap Intervals

These intervals use `monthly_results.csv`, so the observed monthly annualized Sharpe can differ from the daily headline Sharpe in `results_summary.csv`.

| metric | observed | ci95_low | ci95_high | sample_months |
| --- | --- | --- | --- | --- |
| total_return | 3.2240976506 | 1.2297664547 | 7.0279804868 | 101 |
| annualized_return | 0.1867100700 | 0.0999611529 | 0.2807901435 | 101 |
| annualized_sharpe | 1.5322387538 | 0.8931151523 | 2.2164501049 | 101 |
| max_drawdown | -0.1345375182 | -0.1965392106 | -0.0617911857 | 101 |
| avg_monthly_return | 0.0149195470 | 0.0084760190 | 0.0214701855 | 101 |
| monthly_win_rate | 0.6435643564 | 0.5445544554 | 0.7326732673 | 101 |

## Negative Control

| control | observed_annualized_sharpe | control_p95_annualized_sharpe | p_value_control_sharpe_ge_observed | observed_total_return | control_p95_total_return |
| --- | --- | --- | --- | --- | --- |
| monthly_return_sign_flip | 1.5322387538 | 0.5728741236 | 0.0000000000 | 3.2240976506 | 0.7169603455 |

## Robustness Scorecard

| category | check | value | threshold | status |
| --- | --- | --- | --- | --- |
| headline | annualized_sharpe | 1.4505 | >= 1.0 | pass |
| benchmark | sharpe_spread_vs_spy | 0.6475 | > 0 | pass |
| benchmark | drawdown_vs_spy | -0.1564 vs -0.3372 | less severe than SPY | pass |
| inference | bootstrap_sharpe_ci_low | 0.8931151523 | > 0.75 | pass |
| negative_control | sign_flip_sharpe_p_value | 0.0000000000 | < 0.05 | pass |
| walk_forward | expanding_window_positive_sharpe_years | 5/6 | >= 75% | pass |
| walk_forward | selected_candidate_positive_sharpe_years | 8/9 | >= 75% | pass |
| walk_forward | worst_year_sharpe | -0.6052 | > -1.0 | pass |
| sensitivity | local_grid_min_sharpe | 1.4031 | > 1.0 | pass |
| costs | selected_10bps_cost_sharpe | 1.4236 | > 1.0 | pass |
| capacity | twenty_x_cost_proxy_sharpe | 1.3568 | > 1.0 | pass |
| factor_risk | momentum_dominance_share | 1.0000 | < 0.90 preferred | warn |
| data_hygiene | point_in_time_universe | not_available | required for production-grade evidence | fail |
| audit | full_selected_holdings | not_pinned | required for full replication | warn |

## Interpretation

- Expanding-window file is positive in 5/6 years; worst test-year Sharpe is -0.605.
- Selected-candidate table is positive in 8/9 walk-forward years; worst yearly Sharpe is -0.605.
- Selected configuration Sharpe at 10 bps cost is 1.424.
- 20x cost-proxy capacity Sharpe is 1.357.
- The sign-flip control is a falsification check on the saved monthly return signs, not a substitute for signal-shuffle tests on raw price data.

## Limitations

- The default universe is not point-in-time and may contain survivorship bias.
- The committed holdings/rebalance audit files are sample-run artifacts, not the full selected-default holdings history.
- Capacity is modeled as higher effective costs, not full liquidity or market impact.
- Alternative benchmark evidence is limited to the saved SPY comparison unless a pinned full price panel is supplied.
- Historical results do not imply future performance.

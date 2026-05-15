# Project Scorecard

This file is generated from committed result artifacts by `scripts/build_project_scorecard.py`.
It is intended as the honest recruiter/interviewer view: strong research portfolio evidence, not production trading proof.

## Overall Rating

| Dimension | Rating | Reason |
| --- | --- | --- |
| Quant research portfolio | 9/10 | Two independent systems, pinned configs, OOS/fold checks, stress tests, statistical diagnostics, CI, and honest limitations. |
| Research evidence | 7.5/10 | Strong saved evidence for a portfolio project, but still constrained by top-of-book data and limited untouched transfer coverage. |
| Live trading readiness | 4/10 | No broker fill reconciliation, no calibrated HFT queue model, and no point-in-time/delisting-aware medium-alpha universe. |

## Micro Alpha

Source: `hft_microstructure/Results/micro_alpha_quality_sharpe_summary.csv`.
Primary metric: minute Sharpe, because the evidence is intraday quote replay.

| Version | Minute Sharpe | Daily Sharpe | Ann. Daily Sharpe | Total PnL | Worst DD | Trades |
| --- | --- | --- | --- | --- | --- | --- |
| Original mm baseline | 0.513 | 2.529 | 40.15 | 32,193.4 bps | -14.3 bps | 78,070 |
| Prior edge-selected | 0.579 | 2.512 | 39.87 | 30,836.4 bps | -13.7 bps | 69,534 |
| Selected quality gate | 0.601 | 2.876 | 45.66 | 32,980.4 bps | -13.7 bps | 56,646 |

Selected quality gate improvement vs original mm baseline: +0.088 minute Sharpe (17.3%).

| Symbol | Min Edge | 100ms Microprice Gate | 100ms Spread Gate | Minute Sharpe | Daily Sharpe | Total PnL | Trades |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPY | 0.30 | 0.25 | 1.00 | 0.804 | 1.721 | 14,852.7 bps | 20,035 |
| QQQ | 0.30 | 0.25 | 1.00 | 0.615 | 1.819 | 12,752.5 bps | 26,990 |
| IWM | 0.75 | 0.00 | 0.00 | 0.397 | 1.572 | 5,375.2 bps | 9,621 |

Chronological validation sanity check:

| Variant | Split | Dates | Minute Sharpe | Daily Sharpe | Total PnL |
| --- | --- | --- | --- | --- | --- |
| Original mm baseline | OOS | 2026-04-15 to 2026-05-12 | 0.455 | 3.800 | 12,648.8 bps |
| Selected quality gate | Train | 2026-03-02 to 2026-04-14 | 0.613 | 2.532 | 20,052.3 bps |
| Selected quality gate | OOS | 2026-04-15 to 2026-05-12 | 0.584 | 3.733 | 12,928.1 bps |

Selected quality gate OOS minute Sharpe improvement vs original mm baseline: +0.129.

Extended validation:

| Scope | Symbol | Sessions | Dates | Minute Sharpe | Daily Sharpe | Total PnL |
| --- | --- | --- | --- | --- | --- | --- |
| Fresh core OOS | SPY_QQQ_IWM | 2 | 2026-05-13 to 2026-05-14 | 0.702 | 3.978 | 1,153.1 bps |
| No-retune transfer | AAPL | 5 | 2026-05-01 to 2026-05-07 | 0.175 | 1.563 | 47.9 bps |

Fresh core validation is post-cutoff but only two sessions; the AAPL transfer test is no-retune and directionally positive but weak.

Final research-quality gates:

| Gate | Status | Metric |
| --- | --- | --- |
| selected_config_pinned | pass | configs/micro_alpha_selected_quality.json |
| chronological_oos_improvement | pass | +0.129 |
| three_fold_chronological_stability | pass | min_fold_minute=0.577; min_fold_pnl=9,117.5 bps |
| statistical_significance_sanity | pass | 1.000 |
| fresh_post_cutoff_check | warn | 2 sessions; minute Sharpe 0.702 |
| no_retune_transfer_symbol | warn | AAPL minute Sharpe 0.175 |
| live_fill_calibration | fail | not available |

Final quality scorecard: 8 pass / 3 warn / 1 fail; OOS minute Sharpe 0.584; min fold minute Sharpe 0.577; min fold PnL 9,117.5 bps.
Statistical sanity: daily PSR > 0 is 1.000, Bonferroni confidence is 1.000, and sign-flip p-value is 0.0000.

Current boundary: this is Alpaca IEX top-of-book evidence over 51 SPY/QQQ/IWM open-window sessions, not full depth-of-book or live fills.

## Medium Alpha

Source: `medium_term_alpha/Results/selected_default_metrics.csv` and `benchmark_comparison.csv`.

| Metric | Strategy | SPY |
| --- | --- | --- |
| Annualized Sharpe | 1.4505 | 0.8030 |
| Annualized Return | 18.90% | 14.57% |
| Total Return | 322.41% | 210.21% |
| Max Drawdown | -15.64% | -33.72% |
| Annualized Volatility | 12.48% | 19.26% |

Robustness scorecard: 11 pass / 2 warn / 1 fail.
Current boundary: the saved result is not point-in-time/delisting-aware and remains momentum-dominated.

## Upgrade Priorities

1. Add paper/live broker fill reconciliation for the micro alpha.
2. Calibrate passive-fill and queue-position assumptions using execution or order-book data.
3. Replace the medium-alpha universe with point-in-time, delisting-aware data.
4. Extend HFT validation to genuinely new dates, more symbols, and additional intraday windows without changing the pinned config.
5. Keep release verification green in GitHub Actions.

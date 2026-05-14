# Project Scorecard

This file is generated from committed result artifacts by `scripts/build_project_scorecard.py`.
It is intended as the honest recruiter/interviewer view: strong research portfolio evidence, not production trading proof.

## Overall Rating

| Dimension | Rating | Reason |
| --- | --- | --- |
| Quant research portfolio | 8/10 | Two independent systems, real result artifacts, stress tests, walk-forward checks, and honest limitations. |
| Research evidence | 6.5-7/10 | Promising metrics with useful robustness work, but still constrained by data realism. |
| Live trading readiness | 3-4/10 | No live fills, no calibrated HFT queue model, and no point-in-time/delisting-aware medium-alpha universe. |

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

1. Extend HFT validation to genuinely new dates, more symbols, and additional intraday windows.
2. Add a calibrated passive-fill and queue-position model using execution or order-book data.
3. Replace the medium-alpha universe with point-in-time, delisting-aware data.
4. Keep raw-data manifests and exact run configs pinned so GitHub evidence is reproducible.
5. Add negative controls for shuffled HFT signals and shuffled medium-alpha ranks.

# Micro Alpha Research Quality Report

This is the final no-new-data research-hardening report for the selected micro alpha.
It adds statistical sanity checks, chronological fold stability, explicit quality gates, and production-readiness boundaries.

## Headline Diagnostics

- Selected all-sample daily PSR > 0: 1.000.
- Bonferroni confidence after tracked candidate count: 1.000.
- Selected all-sample sign-flip p-value on total PnL: 0.0000.
- Selected OOS minute Sharpe: 0.584.
- Scorecard status: 8 pass / 3 warn / 1 fail.

## Chronological Fold Stability

| fold | sessions | dates | minute_sharpe | daily_sharpe | total_pnl_bps |
| --- | --- | --- | --- | --- | --- |
| 1 | 17 | 2026-03-02 to 2026-03-24 | 0.642 | 2.928 | 12,949.2 |
| 2 | 17 | 2026-03-25 to 2026-04-17 | 0.599 | 2.941 | 9,117.5 |
| 3 | 17 | 2026-04-20 to 2026-05-12 | 0.577 | 3.707 | 10,913.7 |

## Final Gates

| gate | status | metric | threshold |
| --- | --- | --- | --- |
| selected_config_pinned | pass | configs/micro_alpha_selected_quality.json | selected config committed |
| full_sample_minute_sharpe_improvement | pass | +0.088 | > +0.050 |
| chronological_oos_improvement | pass | +0.129 | > 0.000 |
| oos_retention_vs_train | pass | 0.953 | >= 0.750 |
| three_fold_chronological_stability | pass | min_fold_minute=0.577; min_fold_pnl=9,117.5 bps | all folds positive and min minute Sharpe > 0.400 |
| statistical_significance_sanity | pass | 1.000 | Bonferroni confidence > 0.950 |
| fresh_post_cutoff_check | warn | 2 sessions; minute Sharpe 0.702 | positive, but needs >= 20 sessions for stronger evidence |
| no_retune_transfer_symbol | warn | AAPL minute Sharpe 0.175 | > 0, with no symbol-specific retune |
| adverse_selection_boundary | pass | core mm-only survives 0.5 bps and fails at 2 bps | explicit cross-symbol break point |
| latency_sweep_coverage | pass | IWM,QQQ,SPY | SPY, QQQ, IWM at 100ms |
| top_of_book_data_depth | warn | top-of-book only | full depth/order-event data for production claims |
| live_fill_calibration | fail | not available | paper/live broker fills |

## Read

- This is strong research-portfolio evidence because the chosen gate is pinned, OOS-positive, fold-stable, stress-tested, and statistically sanity-checked.
- The remaining fail is production-specific: no broker fill reconciliation or queue-position calibration.
- The honest rating is 9/10 for a research portfolio, not 10/10 live trading infrastructure.

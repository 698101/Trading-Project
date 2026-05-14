# Micro Alpha Chronological Validation

This report splits the saved 51-session SPY/QQQ/IWM evidence chronologically into train and OOS windows.
The train fraction is 60%; the split is a validation sanity check, not a full untouched production-grade holdout.

## Combined Portfolio Metrics

| variant | split | sessions | dates | minute_sharpe | daily_sharpe | total_pnl_bps | trades |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Original mm baseline | train | 31 | 2026-03-02 to 2026-04-14 | 0.564 | 2.147 | 19,544.6 | 41,546 |
| Original mm baseline | oos | 20 | 2026-04-15 to 2026-05-12 | 0.455 | 3.800 | 12,648.8 | 36,524 |
| Original mm baseline | all | 51 | 2026-03-02 to 2026-05-12 | 0.513 | 2.529 | 32,193.4 | 78,070 |
| Prior edge-selected | train | 31 | 2026-03-02 to 2026-04-14 | 0.559 | 2.240 | 18,956.1 | 39,445 |
| Prior edge-selected | oos | 20 | 2026-04-15 to 2026-05-12 | 0.615 | 3.192 | 11,880.3 | 30,089 |
| Prior edge-selected | all | 51 | 2026-03-02 to 2026-05-12 | 0.579 | 2.512 | 30,836.4 | 69,534 |
| Selected quality gate | train | 31 | 2026-03-02 to 2026-04-14 | 0.613 | 2.532 | 20,052.3 | 32,948 |
| Selected quality gate | oos | 20 | 2026-04-15 to 2026-05-12 | 0.584 | 3.733 | 12,928.1 | 23,698 |
| Selected quality gate | all | 51 | 2026-03-02 to 2026-05-12 | 0.601 | 2.876 | 32,980.4 | 56,646 |

## Read

- Train-selected best tracked variant by combined minute Sharpe: Selected quality gate (0.613).
- Selected quality gate OOS: 0.584 minute Sharpe and 3.733 daily Sharpe.
- OOS improvement vs original mm baseline: +0.129 minute Sharpe and -0.067 daily Sharpe.
- This helps address pure full-sample tuning risk, but the next stronger step is a genuinely new date range and additional symbols.

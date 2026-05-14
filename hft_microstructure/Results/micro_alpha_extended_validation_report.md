# Micro Alpha Extended Validation

This report summarizes no-retune validation runs added after the original 51-session evidence set.
Fresh core validation uses 2026-05-13 to 2026-05-14, which is useful but statistically small.
Transfer-symbol validation applies the SPY/QQQ quality-gate parameters to AAPL without symbol-specific retuning.

## Results

| scope | symbol | sessions | dates | minute_sharpe | daily_sharpe | total_pnl_bps | trades |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fresh_core_oos | SPY_QQQ_IWM | 2 | 2026-05-13 to 2026-05-14 | 0.702 | 3.978 | 1,153.1 | 2,144 |
| fresh_core_oos | SPY | 2 | 2026-05-13 to 2026-05-14 | 1.018 | 2.261 | 548.0 | 625 |
| fresh_core_oos | QQQ | 2 | 2026-05-13 to 2026-05-14 | 0.863 | 14.036 | 532.8 | 1,308 |
| fresh_core_oos | IWM | 2 | 2026-05-13 to 2026-05-14 | 0.244 | 0.845 | 72.3 | 211 |
| transfer_symbol | AAPL | 5 | 2026-05-01 to 2026-05-07 | 0.175 | 1.563 | 47.9 | 128 |

## Read

- The fresh SPY/QQQ/IWM cut is post-cutoff evidence, but only two sessions, so daily Sharpe is especially fragile.
- The AAPL transfer test is a no-retune cross-symbol check; it is useful directionally, not broad cross-sectional proof.
- The next stronger pass should extend this to more sessions and more symbols once download time allows.

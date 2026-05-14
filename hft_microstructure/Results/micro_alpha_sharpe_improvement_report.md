# Micro Alpha Sharpe Improvement Summary

This report summarizes saved market-making-only edge-floor experiments.
Selection is by minute Sharpe, which is the primary metric for the intraday quote-replay setup.

## Selected Edge Floors

| symbol | selected_min_edge_bps | baseline_minute_sharpe | selected_minute_sharpe | minute_sharpe_delta | baseline_pnl_bps | selected_pnl_bps | selected_trades |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPY | 0.30 | 0.761 | 0.769 | 0.008 | 14,323.5 | 14,110.7 | 25,666 |
| QQQ | 0.30 | 0.453 | 0.577 | 0.124 | 11,660.7 | 11,350.5 | 34,247 |
| IWM | 0.75 | 0.382 | 0.397 | 0.015 | 6,209.2 | 5,375.2 | 9,621 |

## Combined Portfolio Diagnostic

| scope | minute_sharpe | daily_sharpe | ann_daily_sharpe | total_pnl_bps | worst_dd_bps | trades |
| --- | --- | --- | --- | --- | --- | --- |
| baseline_mm_only | 0.513 | 2.529 | 40.15 | 32,193.4 | -14.3 | 78,070 |
| selected_mm_only | 0.579 | 2.512 | 39.87 | 30,836.4 | -13.7 | 69,534 |

## Interpretation

- The selected configuration improves combined minute Sharpe by tightening the edge floor for QQQ and IWM while keeping SPY close to baseline.
- The improvement trades away some total PnL and trade count, so it should be presented as risk-adjusted tuning rather than a free performance gain.
- Daily Sharpe remains a weak diagnostic for this sample because every combined day is positive; minute Sharpe is the cleaner microstructure metric.

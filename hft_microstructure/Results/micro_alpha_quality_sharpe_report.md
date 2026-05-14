# Micro Alpha Quality Sharpe Report

This report summarizes the opt-in market-making quality gate tested after the edge-floor sweep. The primary metric remains minute Sharpe because the strategy is an intraday quote-replay microstructure alpha.

## Selected Configuration

| Symbol | Min Edge | 100ms Microprice Gate | 100ms Spread Gate | Minute Sharpe | Total PnL | Worst DD | Trades |
|---|---:|---:|---:|---:|---:|---:|---:|
| SPY | 0.30 bps | 0.25 bps | 1.00 bps | 0.804 | 14,852.7 bps | -4.7 bps | 20,035 |
| QQQ | 0.30 bps | 0.25 bps | 1.00 bps | 0.615 | 12,752.5 bps | -4.2 bps | 26,990 |
| IWM | 0.75 bps | 0.00 bps | 0.00 bps | 0.397 | 5,375.2 bps | -13.7 bps | 9,621 |

## Combined Improvement

| Version | Minute Sharpe | Daily Sharpe | Ann. Daily Sharpe | Total PnL | Worst DD | Trades |
|---|---:|---:|---:|---:|---:|---:|
| Original mm baseline | 0.513 | 2.529 | 40.15 | 32,193.4 bps | -14.3 bps | 78,070 |
| Prior edge-selected | 0.579 | 2.512 | 39.87 | 30,836.4 bps | -13.7 bps | 69,534 |
| Selected quality gate | 0.601 | 2.876 | 45.66 | 32,980.4 bps | -13.7 bps | 56,646 |

The selected quality gate improves combined minute Sharpe by 0.088 versus the original mm-only baseline, or 17.3%. It also improves total PnL by 787.1 bps while reducing trade count by 27.4%.

## Notes

- The SPY/QQQ gate requires signed 100ms microprice edge of at least 0.25 bps and 100ms spread of at least 1.00 bps.
- IWM performed best on minute Sharpe with the prior 0.75 bps edge floor and no added quality gate.
- A stricter SPY/QQQ gate at 0.50 bps microprice and 1.50 bps spread reduced combined minute Sharpe to 0.566, so the selected threshold is the better validated point in this pass.

# Medium-Term Alpha Restructure Validation

## What Was Classified

- Medium-term source: `main.py`, `data_loader.py`, `signals.py`, `portfolio.py`, and `metrics.py`.
- Medium-term outputs: summary metrics, benchmark comparison, walk-forward results, sensitivity results, capacity simulation, selected-default metrics, and selected plots.
- Excluded artifacts: `__pycache__`, `.pyc`, logs, nested output duplicates, and old package folders.

## Before Restructuring

The live-data workflow was run from the original nested module:

```powershell
python medium_term_alpha\cross_sectional_momentum\main.py --start 2018-01-01 --output-dir medium_term_alpha\cross_sectional_momentum\output_restructure_baseline
```

That run completed, but Yahoo returned a failed ticker download. Because live-data failures changed between runs, a fixed CSV validation was used for exact before/after comparison.

Fixed CSV baseline command:

```powershell
python medium_term_alpha\cross_sectional_momentum\main.py --csv medium_term_alpha\sample_prices.csv --output-dir medium_term_alpha\cross_sectional_momentum\output_restructure_csv_baseline
```

The fixed sample CSV was later moved to `medium_term_alpha\Results\sample_prices.csv` during presentation cleanup.

## After Restructuring

Command:

```powershell
cd medium_term_alpha
python main.py --csv Results\sample_prices.csv --output-dir Results --plots-dir Plots
```

## Before/After Metric Comparison On Fixed CSV

| Metric | Before | After | Match |
|---|---:|---:|---|
| Assets loaded | 8 | 8 | Yes |
| Rebalances | 18 | 18 | Yes |
| Total return | 0.054707 | 0.054707 | Yes |
| Annualized return | 0.027153 | 0.027153 | Yes |
| Annualized Sharpe | 1.093072 | 1.093072 | Yes |
| Max drawdown | -0.017040 | -0.017040 | Yes |
| Total trading cost | 0.000600 | 0.000600 | Yes |
| Average turnover | 0.133333 | 0.133333 | Yes |
| Benchmark total return | 0.588205 | 0.588205 | Yes |
| Benchmark Sharpe | 1.880614 | 1.880614 | Yes |

## Result

The flat Python project matched the original nested module exactly on a fixed real-price CSV. No signal, weighting, cost, risk-control, or portfolio-construction logic was intentionally changed.

## Live Data Note

The full online `yfinance` runs did not provide a stable exact comparison because different ticker downloads failed across runs. This is a data-availability issue, not a restructure logic change. The fixed CSV validation isolates the code restructure.

## Remaining Manual Review Items

- Add a point-in-time universe if the project is used beyond portfolio presentation.
- Add rebalance holdings export if interview reviewers need exact ticker-level selections.

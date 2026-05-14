# HFT Restructure Validation

## What Was Classified

- HFT source: root C++ files, strategy engines, shared allocation/ablation headers, decision-engine headers, and PowerShell run scripts.
- HFT outputs: `build/final_upgrade`, `build/strategy_mc8_*`, and decision-engine comparison CSVs.
- Excluded artifacts: `build/` executables/objects, large quote folders, `vcpkg/`, logs, and raw quote datasets.

## Before Restructuring

Command:

```powershell
.\build\Portfolio Backtest.exe "Portfolio Quotes\SPY_open60\spy_2026_03_02.csv" --rolling-window 75 --min-edge-bps 0.20 --forecast-weight 0.70 --min-reentry-events 40 --interval-seconds 60 --max-gross-exposure 1.0 --seed 1337 --forecast-mode heuristic --portfolio-mode full --decision-mode off --output-prefix build\restructure_baseline\sample_hft_full_day
```

## After Restructuring

Commands:

```powershell
g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o hft_microstructure\hft_portfolio_validation.exe hft_microstructure\main.cpp
.\hft_microstructure\hft_portfolio_validation.exe "Portfolio Quotes\SPY_open60\spy_2026_03_02.csv" --rolling-window 75 --min-edge-bps 0.20 --forecast-weight 0.70 --min-reentry-events 40 --interval-seconds 60 --max-gross-exposure 1.0 --seed 1337 --forecast-mode heuristic --portfolio-mode full --decision-mode off --output-prefix hft_microstructure\post_restructure_sample_hft_full_day
```

The temporary validation executable was removed after the check.

## Before/After Metric Comparison

| Metric | Before | After | Match |
|---|---:|---:|---|
| Processed quotes | 902935 | 902935 | Yes |
| Completed trades | 656 | 656 | Yes |
| Winning trades | 327 | 327 | Yes |
| Trade win rate | 0.4985 | 0.4985 | Yes |
| Skipped low edge | 32602 | 32602 | Yes |
| Return intervals | 60 | 60 | Yes |
| Total net return | 468.9915 bps | 468.9915 bps | Yes |
| Max drawdown | 3.1490 bps | 3.1490 bps | Yes |
| Minute Sharpe | 0.9625 | 0.9625 | Yes |
| Trade Sharpe reference | 14.4519 | 14.4519 | Yes |
| Market-making sleeve trades | 582 | 582 | Yes |
| Liquidity sleeve trades | 37 | 37 | Yes |
| Momentum sleeve trades | 37 | 37 | Yes |

## Result

The flattened C++ portfolio backtest matched the original executable exactly on the same raw quote file and command-line configuration. No strategy, execution, cost, or portfolio-construction logic was intentionally changed.

## Items Not Fully Re-Run

- The full 30-session HFT pipeline was not re-run after deleting raw-data folders because raw quote files are intentionally excluded from the cleaned repo.
- Completed ablation and latency sweep outputs were not present as real generated artifacts. Template-only CSVs were removed during the recruiter-facing cleanup pass.

## Remaining Manual Review Items

- Optional `microstructure_engine.cpp` data ingestion/downloader builds may require third-party networking dependencies.
- Full raw-data reproduction requires restoring the excluded quote files.

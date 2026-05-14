# HFT Microstructure Research

A C++ HFT-inspired intraday microstructure research framework using top-of-book quote replay, event-driven simulation, execution-aware assumptions, strategy sleeves, risk controls, and retained diagnostics.

This is a research simulator and backtesting exercise. It is not a live production HFT trading system.

![HFT microstructure report dashboard](Plots/hft_report.png)

## Objective

Test whether simple, interpretable intraday microstructure signals remain useful after fill assumptions, transaction costs, adverse-selection controls, and portfolio-level risk limits are applied.

## What The Simulator Does

- Reads top-of-book quote CSVs and replays events through a deterministic event loop.
- Updates portfolio state, sleeve-level strategy state, fills, costs, and risk gates as quotes arrive.
- Compares market-making, liquidity-detection, momentum-ignition, and decision-engine variants.
- Exports retained trade/fill logs and rejected-signal diagnostics for auditability.
- Saves reviewer-facing CSVs in `Results/` and regenerates dark reviewer plots in `Plots/` with `scripts/generate_citadel_plots.py`.

## Data And Quote Replay

Expected quote input columns:

| Column | Meaning |
|---|---|
| `timestamp_ns` | Event timestamp in nanoseconds |
| `symbol` | Instrument symbol |
| `bid_price`, `ask_price` | Top-of-book prices |
| `bid_size`, `ask_size` | Top-of-book sizes |

The preserved historical-style results use SPY open-window quote replay. Full raw quote files are excluded due to size.

The Alpaca real-quote verification workflow downloads raw quotes into the ignored `Portfolio Quotes/` folder, validates them with a manifest, and runs the C++ simulator over verified sessions. Compact recruiter-facing outputs from the restored run are retained:

- `Results/alpaca_real_quote_cross_symbol_manifest_summary.csv`: complete-session coverage summary, currently 51 ok sessions each for SPY, QQQ, and IWM.
- `Results/alpaca_real_quote_cross_symbol_summary.csv`: compact baseline summary for SPY, QQQ, and IWM.
- `Results/real_quote_evidence_ci.csv`: bootstrap confidence intervals for average daily PnL on each symbol and mode.
- `Results/real_quote_robustness_report.md`: generated narrative report covering baseline evidence, latency, stress, and limitations.
- `Results/alpaca_spy_quote_manifest.csv`, `Results/alpaca_qqq_quote_manifest.csv`, `Results/alpaca_iwm_quote_manifest.csv`: per-symbol data-quality manifests.
- `Results/alpaca_spy_real_quote_results_summary.csv`, `Results/alpaca_qqq_real_quote_results_summary.csv`, `Results/alpaca_iwm_real_quote_results_summary.csv`: full-portfolio baseline summaries.
- `Results/alpaca_spy_real_quote_mm_only_summary.csv`, `Results/alpaca_qqq_real_quote_mm_only_summary.csv`, `Results/alpaca_iwm_real_quote_mm_only_summary.csv`: market-making-only baseline summaries.
- `Results/alpaca_spy_real_quote_stress_distribution_summary.csv`, `Results/alpaca_qqq_real_quote_stress_distribution_summary.csv`, and `Results/alpaca_iwm_real_quote_stress_distribution_summary.csv`: real-quote stress distributions across seeds, adverse-selection penalties, and portfolio modes.
- `Results/alpaca_spy_real_quote_latency_sensitivity.csv`, `Results/alpaca_qqq_real_quote_latency_sensitivity.csv`, and `Results/alpaca_iwm_real_quote_latency_sensitivity.csv`: true signal-latency sensitivity on the same real-quote cuts.
- `Results/micro_alpha_quality_sharpe_summary.csv` and `Results/micro_alpha_quality_sharpe_report.md`: selected market-making quality-gate evidence behind the 0.601 combined minute Sharpe and 2.876 combined daily Sharpe.
- `Results/micro_alpha_validation_summary.csv` and `Results/micro_alpha_validation_report.md`: chronological train/OOS sanity check for the baseline, edge-selected, and selected quality-gate variants.
- `Results/micro_alpha_extended_validation_summary.csv`, `Results/micro_alpha_extended_validation_daily_results.csv`, and `Results/micro_alpha_extended_validation_report.md`: post-cutoff SPY/QQQ/IWM fresh-date validation plus no-retune AAPL transfer validation.

Raw quote files are not committed. The restored local raw quote folder is large and should be treated as a local data cache, not a source artifact.

Two small CSVs are included for reproducibility:

- `Results/sample_quotes.csv`: historical-format sample for quote parser smoke testing; it may not generate trades.
- `Results/demo_quotes_synthetic.csv`: deterministic synthetic demo stream used only to verify that the engine produces trades, logs, ablations, and stress diagnostics.

Synthetic demo diagnostics are not compared to the saved 51-session real-quote cross-symbol evidence.

## Strategy Sleeves

| Sleeve | Role |
|---|---|
| Market making | Passive quote-driven edge around the open window |
| Liquidity detection | Imbalance and liquidity-stress style signals |
| Momentum ignition | Short-horizon pressure and continuation signals |
| Decision engine overlays | HMM-style regime filter, Hawkes-style event-intensity filter, and volatility scaling |

## Execution And Risk Assumptions

- Stochastic and partial fill assumptions.
- Spread, slippage, transaction-cost, and adverse-selection controls.
- Minimum expected edge filters.
- Position and gross-exposure limits.
- Per-sleeve portfolio allocation rather than unlimited independent notional.
- Optional decision-engine overlays for regime, event intensity, and volatility risk.
- Optional proxy adverse-selection stress through `--adverse-selection-bps`.

## Saved Historical-Style Results

Primary risk-adjusted metric: minute Sharpe. Annualized Sharpe appears in the CSV as a diagnostic scaling reference only.

| Run | Days | Total PnL | Avg Daily Return | Minute Sharpe | Worst DD | Trades |
|---|---:|---:|---:|---:|---:|---:|
| Full Portfolio Heuristic All Days | 30 | 7,004.7 bps | 233.5 bps | 0.594 | -24.7 bps | 17,690 |
| Market Making Only All Days | 30 | 8,944.5 bps | 298.2 bps | 0.742 | -11.5 bps | 15,352 |
| Full Portfolio Heuristic OOS | 15 | 3,132.5 bps | 208.8 bps | 0.727 | -24.7 bps | 8,454 |
| Full Portfolio ML OOS | 15 | 4,088.1 bps | 272.5 bps | 0.788 | -6.2 bps | 4,952 |

Saved historical-style files:

- `Results/results_summary.csv`
- `Results/daily_results.csv`
- `Results/decision_engine_comparison.csv`
- `Results/strategy_sleeve_monte_carlo.csv`

## Restored Real-Quote Stress Results

The restored Alpaca verification run uses IEX top-of-book quotes from the configured 2026-03-01 through 2026-05-12 range. The current compact evidence covers 51 complete open-window sessions each for SPY, QQQ, and IWM, from 2026-03-02 through 2026-05-12, excluding weekends and the 2026-04-03 market holiday. Raw quotes are excluded, but manifests and result summaries are retained. The full stress grid has been run for SPY, QQQ, and IWM using three fill-randomness seeds, two portfolio modes, and adverse-selection penalties of 0, 0.25, 0.5, 1, and 2 bps per completed trade.

| Portfolio | Adverse Selection | Runs | Mean PnL | Mean Minute Sharpe | 5% Sharpe | Positive Runs |
|---|---:|---:|---:|---:|---:|---:|
| Full portfolio | 0.00 bps | 3 | 11,250.4 bps | 0.659 | 0.632 | 100% |
| Full portfolio | 0.25 bps | 3 | 8,313.4 bps | 0.517 | 0.496 | 100% |
| Full portfolio | 0.50 bps | 3 | 5,517.3 bps | 0.381 | 0.350 | 100% |
| Full portfolio | 1.00 bps | 3 | 782.0 bps | 0.067 | 0.064 | 100% |
| Full portfolio | 2.00 bps | 3 | -2,040.6 bps | -0.230 | -0.257 | 0% |
| Market making only | 0.00 bps | 3 | 14,203.0 bps | 0.690 | 0.622 | 100% |
| Market making only | 0.50 bps | 3 | 7,251.9 bps | 0.465 | 0.412 | 100% |
| Market making only | 1.00 bps | 3 | 1,881.6 bps | 0.131 | 0.112 | 100% |
| Market making only | 2.00 bps | 3 | -1,188.8 bps | -0.164 | -0.174 | 0% |

This is the strongest current validation evidence and also the clearest limitation: the strategy is profitable under moderate adverse-selection stress, but it is not robust to a 2 bps per-trade penalty. The project should be presented as a quote-replay research engine with explicit fragility analysis, not as a finished live HFT strategy.

For QQQ, the same 51-session stress grid is positive through 0.5 bps but turns negative around 1 bps. For IWM, full-mode stress is positive through 0.5 bps, marginal around 1 bps, and negative at 2 bps; market-making-only survives 1 bps and fails at 2 bps. IWM should be treated as a weaker cross-symbol check, not as equal-strength validation.

## Cross-Symbol Baseline Evidence

`Results/alpaca_real_quote_cross_symbol_summary.csv` consolidates the current local real-quote baseline evidence:

| Symbol | Complete Sessions | Backtest Sessions | Full PnL | Full Minute Sharpe | Full Trades | MM PnL | MM Minute Sharpe | MM Trades |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY | 51 | 51 | 11,373.0 bps | 0.635 | 29,632 | 14,323.5 bps | 0.761 | 25,743 |
| QQQ | 51 | 51 | 8,471.4 bps | 0.426 | 39,431 | 11,660.7 bps | 0.453 | 35,247 |
| IWM | 51 | 51 | 4,180.6 bps | 0.255 | 20,656 | 6,209.2 bps | 0.382 | 17,080 |

`Results/real_quote_evidence_ci.csv` adds bootstrap confidence intervals for average daily PnL. These intervals resample days and should be read as descriptive uncertainty, not a proof of future profitability.

## Retained Demo Diagnostics

Because the full raw quote dataset is not committed, the repo now includes a deterministic demo workflow:

```powershell
python run_diagnostics.py
```

This writes real simulator outputs from `Results/demo_quotes_synthetic.csv`:

- `Results/trade_log.csv`: completed trade/fill log with entry/exit timestamps, sleeve, side, fill prices, mid prices, spreads, gross PnL, cost/haircut, net PnL, and portfolio weight.
- `Results/rejected_signals.csv`: lightweight rejected-signal log for fill misses, reentry cooldowns, and edge/probability filters.
- `Results/ablation_results.csv`: demo ablation variants for portfolio modes, decision controls, low-edge gate, and gross-exposure cap.
- `Results/latency_sensitivity.csv`: proxy adverse-selection stress, clearly labelled as not true latency modelling.

Current demo artifact counts:

| Artifact | Rows / Variants |
|---|---:|
| `trade_log.csv` | 92 completed trades |
| `rejected_signals.csv` | 4,505 rejected/missed signals |
| `ablation_results.csv` | 7 variants |
| `latency_sensitivity.csv` | 5 proxy stress scenarios |

## Reading The Plots

- `Plots/hft_report.png` and `Plots/hft_real_quote_dashboard.png`: dark real-quote dashboard for 51-session SPY/QQQ/IWM baseline, selected quality-gate Sharpe, confidence intervals, and stress boundary.
- `Plots/hft_micro_alpha_quality_sharpe.png`: selected market-making quality-gate summary showing the 2.876 combined daily Sharpe and 0.601 combined minute Sharpe.
- `Plots/hft_micro_alpha_validation.png`: chronological train/OOS validation view for the baseline, edge-selected, and selected quality-gate variants.
- `Plots/hft_micro_alpha_extended_validation.png`: post-cutoff core-symbol and no-retune AAPL transfer validation.
- `Plots/hft_cross_symbol_cumulative_pnl.png`: cumulative full and market-making-only PnL curves by symbol.
- `Plots/hft_daily_pnl_bars.png`: daily full-portfolio PnL bars for SPY, QQQ, and IWM.
- `Plots/hft_adverse_selection_stress.png`: PnL and minute Sharpe decay under 0 to 2 bps adverse-selection penalties.
- `Plots/hft_latency_sensitivity.png`: total PnL and expired-signal counts under delayed signal processing.
- `Plots/hft_bootstrap_ci.png`: bootstrap confidence intervals for average daily PnL.
- `Plots/hft_drawdown_comparison.png`: cumulative session drawdown comparison by symbol and mode.

## Why Minute Sharpe Is The Main Metric

The preserved HFT evidence is intraday and open-window focused, so minute-level return stability is more relevant than annualized portfolio Sharpe. Annualized Sharpe can be useful as a rough diagnostic, but it should not be read the same way as a multi-year daily portfolio Sharpe.

## Compile, Run, And Regenerate Diagnostics

Install Python plotting dependencies:

```powershell
pip install -r requirements.txt
```

Compile the primary C++ simulator:

```powershell
g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o hft_portfolio.exe main.cpp
```

On Linux:

```bash
g++ -std=c++17 -O2 -o hft_microstructure/hft_portfolio hft_microstructure/main.cpp
```

Download Alpaca historical quotes and run the one-command real-quote evidence pipeline:

```bash
export APCA_API_KEY_ID=...
export APCA_API_SECRET_KEY=...
python3 scripts/run_citadel_hft_evidence.py --symbols SPY,QQQ,IWM --start-date 2026-03-01 --end-date 2026-05-12 --target-ok-sessions 0 --max-sessions 51
```

The Python downloader uses the actual New York 09:30 market open converted to UTC. Pass `--fixed-1330-utc` only to reproduce legacy fixed-UTC experiments.
The saved local evidence currently uses a uniform 51-session stress/latency cut for SPY, QQQ, and IWM through 2026-05-12.

Run the deterministic demo diagnostics:

```powershell
python run_diagnostics.py
```

Regenerate presentation plots from saved CSVs:

```powershell
python ../scripts/generate_citadel_plots.py
```

Run the quote-format smoke test:

```powershell
.\hft_portfolio.exe Results\sample_quotes.csv --rolling-window 75 --min-edge-bps 0.20 --forecast-weight 0.70 --min-reentry-events 40 --interval-seconds 60 --max-gross-exposure 1.0 --seed 1337 --forecast-mode heuristic --portfolio-mode full --decision-mode off
```

Run the multi-symbol real-quote suite orchestrator:

```bash
python3 scripts/run_real_quote_symbol_suite.py --skip-download --symbols SPY,QQQ,IWM --no-run-stress --no-run-latency
python3 scripts/analyze_real_quote_evidence.py --symbols SPY,QQQ,IWM
```

Rebuild the saved micro-alpha validation report from local saved backtest outputs:

```bash
python3 scripts/analyze_micro_alpha_validation.py
python3 scripts/summarize_micro_alpha_extended_validation.py
```

See `build_instructions.md` for compiler notes and optional tools.

## Limitations

- The preserved historical-style result set is open-window focused.
- Full raw quote files are excluded due to size, so the 51-session result cannot be fully regenerated from committed data alone.
- `Results/demo_quotes_synthetic.csv` is synthetic and should be used only for engine/logging reproducibility.
- A full historical trade/fill log for the 51-session run is not retained yet.
- SPY, QQQ, and IWM have real-quote stress and latency files; IWM is still weaker on minute Sharpe and full-mode adverse-selection stress.
- Market-making dominance is a key validation risk; optimistic fill or spread-capture assumptions could materially affect results.
- The simulator does not model exchange queue position with production-level detail.
- The current real-quote evidence remains open-window focused and ends at 2026-05-12.

## Next Validation Steps

- Regenerate historical trade/fill logs using the full quote dataset.
- Extend the full real-quote stress grid to additional liquid large-cap names and more intraday windows.
- Separate open, midday, and close windows.
- Keep extending the pinned full-date manifest beyond 2026-05-12.
- Add true timestamp-shift latency simulation if quote and order-event data support it.
- Calibrate fill, slippage, and market-impact assumptions against execution data.
- Add exchange/order-event latency modelling if suitable data becomes available.
- Extend validation beyond a single SPY open-window setup without tuning parameters per day.

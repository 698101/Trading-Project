<<<<<<< HEAD
﻿# Quant Trading Research Portfolio

This repository is a recruiter-facing research portfolio for quant trading, HFT-inspired microstructure research, systematic trading, and quantitative research roles. It contains two independent projects:

- `hft_microstructure/`: C++ event-driven quote replay and execution-aware intraday microstructure simulation.
- `medium_term_alpha/`: Python cross-sectional equity alpha research over 1-12 week holding horizons.

The code is research infrastructure, not a live trading system. The focus is on interpretable assumptions, transaction costs, benchmark-aware reporting, robustness checks, and reproducible presentation artifacts.

For a short review path, see `REVIEWER_GUIDE.md`.

## Project Dashboards

![HFT microstructure dashboard](hft_microstructure/Plots/hft_report.png)

![Medium-term alpha dashboard](medium_term_alpha/Plots/medium_term_alpha_report.png)

## Projects At A Glance

| Project | Focus | Language | What It Demonstrates | Saved Headline Evidence |
|---|---|---:|---|---|
| `hft_microstructure/` | Top-of-book quote replay, event-driven intraday simulation, strategy sleeves, execution/risk controls | C++ | Low-latency style data handling, fill/cost assumptions, decision-engine overlays, per-session diagnostics | Alpaca IEX real-quote evidence through 2026-05-12: 51 complete SPY, QQQ, and IWM open-window sessions. Baseline full-mode PnL: SPY 11,373.0 bps, QQQ 8,471.4 bps, IWM 4,180.6 bps. Stress grids show explicit adverse-selection breakpoints: SPY survives 1 bps and fails at 2 bps, QQQ survives 0.5 bps and fails around 1 bps, and IWM full-mode is marginal around 1 bps |
| `medium_term_alpha/` | Cross-sectional medium-term equity alpha with cost-aware portfolio construction | Python | Signal engineering, walk-forward validation, sensitivity/capacity analysis, benchmark comparison, bootstrap/negative-control reporting | Selected default: 1.45 annualized Sharpe vs SPY 0.80, 18.9% annualized return, 322.4% total return, -15.6% max drawdown. Robustness scorecard passes benchmark, walk-forward, cost, capacity, and sign-flip checks; point-in-time universe remains the main fail |

## Repository Structure

```text
quant-trading-research-portfolio/
|-- README.md
|-- .gitignore
|-- LICENSE
|-- REPO_AUDIT.md
|-- REVIEWER_GUIDE.md
|-- hft_microstructure/
|   |-- README.md
|   |-- RESULTS_SUMMARY.md
|   |-- RESTRUCTURE_VALIDATION.md
|   |-- build_instructions.md
|   |-- main.cpp
|   |-- microstructure_engine.cpp
|   |-- strategies.cpp
|   |-- risk_and_execution.cpp
|   |-- ml_edge_model.cpp
|   |-- generate_plots.py
|   |-- run_diagnostics.py
|   |-- config_example.json
|   |-- requirements.txt
|   |-- Results/
|   |   |-- results_summary.csv
|   |   |-- daily_results.csv
|   |   |-- decision_engine_comparison.csv
|   |   |-- strategy_sleeve_monte_carlo.csv
|   |   |-- sample_quotes.csv
|   |   |-- demo_quotes_synthetic.csv
|   |   |-- trade_log.csv
|   |   |-- rejected_signals.csv
|   |   |-- ablation_results.csv
|   |   |-- latency_sensitivity.csv
|   |-- Plots/
|   |   |-- hft_report.png
|   |   |-- hft_real_quote_dashboard.png
|   |   |-- hft_cross_symbol_cumulative_pnl.png
|   |   |-- hft_daily_pnl_bars.png
|   |   |-- hft_adverse_selection_stress.png
|   |   |-- hft_latency_sensitivity.png
|   |   |-- hft_bootstrap_ci.png
|   |   |-- hft_drawdown_comparison.png
|-- medium_term_alpha/
|   |-- README.md
|   |-- RESULTS_SUMMARY.md
|   |-- RESTRUCTURE_VALIDATION.md
|   |-- main.py
|   |-- data_and_features.py
|   |-- strategy_and_portfolio.py
|   |-- backtest_and_metrics.py
|   |-- plots.py
|   |-- reporting.py
|   |-- config_example.yaml
|   |-- default_selection_report.md
|   |-- requirements.txt
|   |-- Results/
|   |   |-- results_summary.csv
|   |   |-- benchmark_comparison.csv
|   |   |-- walk_forward_results.csv
|   |   |-- sensitivity_results.csv
|   |   |-- capacity_simulation.csv
|   |   |-- factor_behavior_summary.csv
|   |   |-- selected_default_metrics.csv
|   |   |-- monthly_results.csv
|   |   |-- medium_alpha_bootstrap_ci.csv
|   |   |-- medium_alpha_negative_controls.csv
|   |   |-- medium_alpha_robustness_scorecard.csv
|   |   |-- medium_alpha_robustness_report.md
|   |   |-- portfolio_weights.csv
|   |   |-- rebalance_log.csv
|   |   |-- daily_strategy_returns.csv
|   |   |-- benchmark_timeseries.csv
|   |   |-- sample_prices.csv
|   |-- Plots/
|   |   |-- medium_term_alpha_report.png
|   |   |-- cumulative_returns.png
|   |   |-- drawdown.png
|   |   |-- rolling_sharpe.png
|   |   |-- annual_returns.png
|   |   |-- walk_forward_yearly_performance.png
|   |   |-- cost_capacity_sensitivity.png
|   |   |-- bootstrap_negative_control.png
|   |   |-- turnover_holdings_concentration.png
|   |   |-- factor_diagnostics.png
```

## HFT Microstructure Project

`hft_microstructure/` is a C++ research simulator for replaying top-of-book quotes through event-driven intraday strategy logic. It includes:

- Market-making, liquidity-detection, and momentum-ignition sleeves.
- Stochastic/partial fill assumptions, spread/slippage costs, adverse-selection controls, and exposure limits.
- Decision-engine overlays using regime, event-intensity, and volatility filters.
- Saved session-level results, sleeve diagnostics, retained demo trade logs, ablation/proxy stress diagnostics, and presentation plots generated from CSV outputs.
- Restored Alpaca real-quote verification workflow with manifest validation, atomic quote downloads, and per-symbol summaries.
- Cross-symbol real-quote baseline evidence for SPY, QQQ, and IWM in `hft_microstructure/Results/alpaca_real_quote_cross_symbol_summary.csv`.
- Bootstrap confidence intervals in `hft_microstructure/Results/real_quote_evidence_ci.csv` and an auto-generated robustness report in `hft_microstructure/Results/real_quote_robustness_report.md`.
- Real-quote stress grid across seeds, adverse-selection penalties, and portfolio modes for SPY, QQQ, and IWM to show robustness boundaries rather than only headline performance.
- True signal-latency sensitivity on SPY, QQQ, and IWM sessions, with explicit expired-signal counts.
- One-command orchestration via `scripts/run_citadel_hft_evidence.py` for repairing quote coverage, running the suite, and regenerating the report.

Minute Sharpe is the primary risk-adjusted metric because the saved evidence is intraday and open-window focused. Annualized Sharpe is retained in the CSVs only as a diagnostic scaling reference.

## Medium-Term Alpha Project

`medium_term_alpha/` is a Python research workflow for cross-sectional equity momentum over 1-12 week horizons. It includes:

- 21, 63, and 126 trading-day momentum signals with a 5-day recent-return skip.
- Short-term reversal penalty and quality/volatility-stability filter.
- Long-only cost-aware portfolio construction with signal-strength filtering, inverse-volatility sizing, turnover gating, max position caps, and market-regime scaling.
- SPY benchmark comparison, walk-forward checks, sensitivity testing, capacity diagnostics, and factor/regime summaries.
- Portfolio audit exports for sample-run weights, rebalances, turnover, costs, and benchmark returns.
- A reproducible full selected-default holdings export path via `scripts/export_medium_alpha_selected_audit.py` when a pinned full price panel is supplied.
- Bootstrap confidence intervals, sign-flip negative control, and a pass/warn/fail robustness scorecard in `medium_term_alpha/Results/medium_alpha_robustness_report.md`.

The selected default is not chosen purely by maximum in-sample Sharpe. It is selected based on Sharpe, drawdown, turnover, cost impact, benchmark comparison, and walk-forward stability.

## Skills Demonstrated

- Event-driven simulation and C++ research engineering.
- Execution-aware backtesting assumptions and risk controls.
- Interpretable alpha signal construction.
- Cost-aware portfolio construction and turnover diagnostics.
- Benchmark-relative reporting and walk-forward validation.
- Clean research packaging: source files, saved CSV evidence, reproducible plotting scripts, and recruiter-readable documentation.

## Reproduce Results And Plots

HFT smoke test and plot generation:

```powershell
cd hft_microstructure
pip install -r requirements.txt
g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o hft_portfolio.exe main.cpp
.\hft_portfolio.exe Results\sample_quotes.csv --rolling-window 75 --min-edge-bps 0.20 --forecast-weight 0.70 --min-reentry-events 40 --interval-seconds 60 --max-gross-exposure 1.0 --seed 1337 --forecast-mode heuristic --portfolio-mode full --decision-mode off
python run_diagnostics.py
python ../scripts/generate_citadel_plots.py
```

Real-quote HFT evidence pipeline:

```bash
export APCA_API_KEY_ID=...
export APCA_API_SECRET_KEY=...
python3 scripts/run_citadel_hft_evidence.py --symbols SPY,QQQ,IWM --start-date 2026-03-01 --end-date 2026-05-12 --target-ok-sessions 0 --max-sessions 51
```

The saved local evidence currently uses 51 complete open-window sessions for SPY, QQQ, and IWM from 2026-03-02 through 2026-05-12, excluding weekends and the 2026-04-03 market holiday. Raw quote CSVs are intentionally ignored because they are large.

Medium-term alpha sample run and plot generation:

```powershell
cd medium_term_alpha
pip install -r requirements.txt
python main.py --csv Results\sample_prices.csv --output-dir Results_sample --plots-dir Plots_sample
python ../scripts/analyze_medium_alpha_evidence.py --results-dir Results
python ../scripts/generate_citadel_plots.py
```

Full selected-default holdings audit from a pinned price panel:

```bash
python3 scripts/export_medium_alpha_selected_audit.py --csv /path/to/pinned_full_prices.csv --benchmark-csv /path/to/pinned_benchmark_prices.csv --output-dir medium_term_alpha/Results_full_selected_default --plots-dir medium_term_alpha/Plots_full_selected_default
```

Dark reviewer plots are regenerated from saved CSVs with `python3 scripts/generate_citadel_plots.py`. HFT demo diagnostics use synthetic quotes for engine/log reproducibility only; full HFT result reproduction requires the excluded raw quote files. Full medium-term alpha runs can use the online data workflow with `python main.py --start 2018-01-01`, subject to data availability.

## Limitations

- This is research code, not production trading infrastructure.
- Full raw quote data is excluded due to size; the committed HFT sample is for smoke testing.
- The strongest real-quote evidence is still open-window focused and uses top-of-book quotes, not full depth-of-book or live fills.
- SPY/QQQ/IWM have 51-session stress and latency grids; IWM is still weaker on minute Sharpe and becomes marginal under 1 bps full-mode adverse-selection stress.
- HFT ablation and adverse-selection diagnostics are reproducible on the committed synthetic demo stream, while the real-quote stress artifacts depend on the excluded raw quote folder.
- The medium-term alpha universe is not point-in-time unless a point-in-time dataset is supplied.
- The medium-term alpha result is momentum-dominated and should not be oversold as a diversified multi-factor edge.
- Medium-term data quality depends on the input source; online downloads can vary.
- Historical results are not evidence of guaranteed future performance.

=======
# Quant-Trading
>>>>>>> c39c18f7556dc27a8c884f586ded34ab8199dc90

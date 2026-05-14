# Reviewer Guide

This guide is a short path through the repo for quant/HFT recruiters and interviewers.

## Start Here

1. `README.md` for the two-project overview and headline metrics.
2. `PROJECT_SCORECARD.md` for the current metric/risk summary and honest rating.
3. `hft_microstructure/README.md` and `hft_microstructure/RESULTS_SUMMARY.md` for the C++ microstructure simulator.
4. `medium_term_alpha/README.md` and `medium_term_alpha/RESULTS_SUMMARY.md` for the Python cross-sectional alpha research.

## Main Evidence Files

| Project | Historical / Selected Evidence | Audit / Demo Evidence |
|---|---|---|
| HFT microstructure | `hft_microstructure/Results/results_summary.csv`, `daily_results.csv`, `decision_engine_comparison.csv`, `strategy_sleeve_monte_carlo.csv`; restored Alpaca verification in `alpaca_real_quote_cross_symbol_summary.csv`, `alpaca_real_quote_cross_symbol_manifest_summary.csv`, `real_quote_evidence_ci.csv`, `real_quote_robustness_report.md`, `micro_alpha_quality_sharpe_report.md`, `micro_alpha_validation_report.md`, `micro_alpha_extended_validation_report.md`, per-symbol manifests/results for SPY, QQQ, and IWM, plus SPY/QQQ/IWM stress and latency files | `trade_log.csv`, `rejected_signals.csv`, `ablation_results.csv`, `latency_sensitivity.csv` generated from `demo_quotes_synthetic.csv` |
| Medium-term alpha | `medium_term_alpha/Results/results_summary.csv`, `benchmark_comparison.csv`, `selected_default_metrics.csv`, `walk_forward_results.csv`, `sensitivity_results.csv`, `capacity_simulation.csv`, `medium_alpha_bootstrap_ci.csv`, `medium_alpha_negative_controls.csv`, `medium_alpha_robustness_scorecard.csv`, `medium_alpha_robustness_report.md` | `portfolio_weights.csv`, `rebalance_log.csv`, `daily_strategy_returns.csv`, `benchmark_timeseries.csv` generated from `sample_prices.csv` |

Pinned selected-run configs live in `configs/`.

## Reproduce Plots And Diagnostics

Current dark reviewer plots:

```bash
python3 scripts/generate_citadel_plots.py
```

HFT diagnostics:

```powershell
cd hft_microstructure
pip install -r requirements.txt
g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o hft_portfolio.exe main.cpp
python run_diagnostics.py
```

Medium-term alpha diagnostics:

```powershell
cd medium_term_alpha
pip install -r requirements.txt
python ..\scripts\analyze_medium_alpha_evidence.py --results-dir Results
```

Sample audit rerun:

```powershell
python main.py --csv Results\sample_prices.csv --output-dir Results_sample --plots-dir Plots_sample
```

Full selected-default holdings audit from a pinned price panel:

```bash
python3 scripts/export_medium_alpha_selected_audit.py --csv /path/to/pinned_full_prices.csv --benchmark-csv /path/to/pinned_benchmark_prices.csv --output-dir medium_term_alpha/Results_full_selected_default --plots-dir medium_term_alpha/Plots_full_selected_default
```

## Evidence Boundaries

- HFT real-quote headline metrics are compact outputs from local Alpaca IEX quote downloads; full raw quote files are excluded.
- Current validated complete-session coverage is 51 SPY, 51 QQQ, and 51 IWM open-window sessions from 2026-03-02 through 2026-05-12, excluding weekends and the 2026-04-03 market holiday.
- The SPY/QQQ/IWM real-quote stress grids show the current robustness boundary: SPY survives through 1 bps per completed trade and fails at 2 bps; QQQ survives through 0.5 bps and fails around 1 bps; IWM full-mode is marginal around 1 bps, while IWM market-making-only survives 1 bps and fails at 2 bps.
- The true latency sensitivity tables show modest delays expiring some signals without collapsing the SPY/QQQ/IWM edge on this 51-session cut; that is useful but should not be oversold.
- IWM now has the same 51-session stress/latency evidence, but its baseline minute Sharpe remains materially weaker than SPY/QQQ.
- The selected micro-alpha quality gate has a chronological OOS sanity check: 0.584 OOS minute Sharpe and 3.733 OOS daily Sharpe over the later 20 sessions.
- Fresh post-cutoff SPY/QQQ/IWM validation on 2026-05-13 and 2026-05-14 is positive, but too small to carry a broad claim; the no-retune AAPL transfer check is positive but weak.
- HFT trade logs, rejected signals, ablations, and adverse-selection stress are real simulator outputs from synthetic demo quotes, not historical performance evidence.
- HFT `latency_sensitivity.csv` is proxy adverse-selection stress, not true timestamp-shift latency modelling.
- Medium-term headline metrics are saved selected-default evidence.
- Medium-term robustness report adds monthly bootstrap intervals, a sign-flip negative control, and a pass/warn/fail scorecard.
- Medium-term scorecard passes benchmark, walk-forward, local sensitivity, cost, capacity, and negative-control checks.
- Medium-term scorecard still warns on momentum dominance and fails point-in-time universe availability.
- Medium-term holdings and benchmark time-series audit files are from the committed sample run; `medium_term_alpha/Results/full_selected_default_audit_status.md` and `scripts/export_medium_alpha_selected_audit.py` document the exact full-audit path once a pinned full data snapshot is supplied.

## Key Limitations

- This is research code, not live trading infrastructure.
- HFT fill/queue assumptions need calibration against execution data.
- HFT validation is still open-window focused and top-of-book only; it does not model full depth-of-book queue position.
- Medium-term alpha uses a non-point-in-time universe unless a point-in-time dataset is supplied.
- Medium-term alpha is momentum-dominated in the saved factor diagnostics.
- Medium-term online runs depend on data-provider availability.
- Historical results do not imply future performance.

## Best Next Improvements

- Retain full historical HFT trade/fill logs and rerun ablations on the full quote set.
- Add true latency tests only with suitable timestamped order/fill data.
- Extend the full stress/latency grid to additional large-cap names and more intraday windows.
- Keep extending the pinned HFT manifest past 2026-05-12 and add more intraday windows.
- Run the scripted full medium-term selected-default holdings export on a pinned data snapshot and retain the resulting manifest.
- Replace survivorship-biased universe data with point-in-time, delisting-aware data.
- Add signal-shuffle negative controls on a pinned full price panel.

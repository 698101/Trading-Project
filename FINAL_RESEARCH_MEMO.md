# Quant Research Portfolio Memo

Last updated: 2026-05-14

This repository contains two independent research projects:

- `hft_microstructure/`: C++ top-of-book quote replay and execution-aware intraday microstructure simulation.
- `medium_term_alpha/`: Python medium-term cross-sectional equity alpha research with benchmark, cost, walk-forward, and robustness reporting.

The strongest framing is research engineering plus empirical validation discipline. This is not production trading infrastructure, and it should not be presented as live-tradable without execution data, queue-position calibration, and point-in-time datasets.

## HFT Microstructure Assessment

The HFT project is now the stronger engineering artifact. It has a real C++ event-driven quote replay engine, retained diagnostics, data-quality manifests, robust Alpaca quote download/repair scripts, cross-symbol summaries, bootstrap confidence intervals, adverse-selection stress, and true signal-latency sweeps.

Current local Alpaca IEX evidence covers 51 complete open-window sessions from 2026-03-02 through 2026-05-12, excluding weekends and the 2026-04-03 market holiday:

| Symbol | OK Sessions | Backtest Sessions | Full PnL | Full Minute Sharpe | MM PnL | MM Minute Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 51 | 51 | 11,373.0 bps | 0.635 | 14,323.5 bps | 0.761 |
| QQQ | 51 | 51 | 8,471.4 bps | 0.426 | 11,660.7 bps | 0.453 |
| IWM | 51 | 51 | 4,180.6 bps | 0.255 | 6,209.2 bps | 0.382 |

The main HFT evidence is not the headline PnL. It is the stress boundary:

- SPY remains positive through 1 bps adverse selection and fails at 2 bps.
- QQQ remains positive through 0.5 bps and fails around 1 bps.
- IWM full-mode is positive through 0.5 bps, marginal around 1 bps, and fails at 2 bps; market-making-only survives 1 bps and fails at 2 bps.
- Signal-latency sweeps exist for SPY, QQQ, and IWM and record expired signals explicitly.

The latest micro-alpha improvement is the selected market-making quality gate. It raises combined SPY/QQQ/IWM minute Sharpe from 0.513 to 0.601 and combined daily Sharpe from 2.529 to 2.876. A chronological train/OOS sanity check now retains 0.584 OOS minute Sharpe and 3.733 OOS daily Sharpe over the later 20 sessions. A post-cutoff two-session SPY/QQQ/IWM check remains positive at 0.702 minute Sharpe, and a no-retune AAPL transfer check is positive but weak at 0.175 minute Sharpe. These should still be treated as local validation checks rather than fully untouched production evidence.

Primary files:

- `hft_microstructure/Results/alpaca_real_quote_cross_symbol_summary.csv`
- `hft_microstructure/Results/alpaca_real_quote_cross_symbol_manifest_summary.csv`
- `hft_microstructure/Results/real_quote_evidence_ci.csv`
- `hft_microstructure/Results/real_quote_robustness_report.md`
- `hft_microstructure/Results/micro_alpha_quality_sharpe_report.md`
- `hft_microstructure/Results/micro_alpha_validation_report.md`
- `hft_microstructure/Results/micro_alpha_extended_validation_report.md`
- `hft_microstructure/Results/alpaca_spy_real_quote_stress_distribution_summary.csv`
- `hft_microstructure/Results/alpaca_qqq_real_quote_stress_distribution_summary.csv`
- `hft_microstructure/Results/alpaca_iwm_real_quote_stress_distribution_summary.csv`
- `hft_microstructure/Results/alpaca_spy_real_quote_latency_sensitivity.csv`
- `hft_microstructure/Results/alpaca_qqq_real_quote_latency_sensitivity.csv`
- `hft_microstructure/Results/alpaca_iwm_real_quote_latency_sensitivity.csv`

Main HFT gaps:

- Top-of-book only, not full depth-of-book.
- No exchange queue-position calibration.
- No real execution/fill dataset.
- Full raw quotes are intentionally excluded from git.
- Evidence is still open-window focused and currently ends at 2026-05-12.

## Medium-Term Alpha Assessment

The medium-term alpha project is a credible systematic research artifact, but it is less differentiated than the HFT project. It has stronger research hygiene now: selected-default reporting, bootstrap confidence intervals, sign-flip negative controls, walk-forward checks, cost/capacity sensitivity, factor diagnostics, and an explicit scorecard.

The saved full run spans 2018-01-02 through 2026-05-06, with walk-forward test years from 2021 through the 2026 partial year. That is sufficient for a recruiter-facing modern-regime research portfolio, but it is not full-cycle institutional proof because it lacks point-in-time/delisting-aware data and pre-2018 regimes.

Saved selected-default evidence:

| Metric | Strategy | SPY |
|---|---:|---:|
| Annualized Sharpe | 1.4505 | 0.8030 |
| Annualized Return | 18.90% | 14.57% |
| Total Return | 322.41% | 210.21% |
| Max Drawdown | -15.64% | -33.72% |
| Annualized Volatility | 12.48% | 19.26% |

The strategy passes the main saved robustness checks:

- Sharpe spread vs SPY: +0.6475.
- Monthly bootstrap Sharpe 95% lower bound: 0.8931.
- Sign-flip negative-control p-value: 0.0000.
- Expanding-window positive Sharpe years: 5/6.
- Selected-candidate positive years: 8/9.
- 10 bps cost Sharpe: 1.4236.
- 20x cost-proxy Sharpe: 1.3568.

The honest weaknesses are also explicit:

- The default universe is not point-in-time, so survivorship bias remains a production-grade fail.
- Saved factor diagnostics show 100% momentum dominance, so this should not be oversold as a diversified multi-factor alpha.
- Committed holdings audit files are sample-run artifacts. `scripts/export_medium_alpha_selected_audit.py` now provides the reproducible full selected-default export path once a pinned full price panel is supplied.

Primary files:

- `medium_term_alpha/Results/results_summary.csv`
- `medium_term_alpha/Results/benchmark_comparison.csv`
- `medium_term_alpha/Results/selected_default_metrics.csv`
- `medium_term_alpha/Results/walk_forward_results.csv`
- `medium_term_alpha/Results/sensitivity_results.csv`
- `medium_term_alpha/Results/capacity_simulation.csv`
- `medium_term_alpha/Results/medium_alpha_bootstrap_ci.csv`
- `medium_term_alpha/Results/medium_alpha_negative_controls.csv`
- `medium_term_alpha/Results/medium_alpha_robustness_scorecard.csv`
- `medium_term_alpha/Results/medium_alpha_robustness_report.md`
- `medium_term_alpha/Results/full_selected_default_audit_status.md`

## Interview Positioning

This is now a strong quant research portfolio if presented with precision:

- Lead with the HFT project for systems, microstructure, and execution-aware research engineering.
- Use the medium-term alpha project to show systematic research process, robustness reporting, and honest data-hygiene discipline.
- Do not claim live HFT tradability or production alpha.
- Be ready to explain why minute Sharpe is used for the intraday HFT evidence and annualized daily Sharpe is used for medium-term alpha.
- Be ready to discuss exactly where each strategy breaks under stress.

The project is much closer to "serious quant research portfolio" than "toy backtest." The remaining gap to institutional production quality is data realism: point-in-time equity data for medium alpha and execution/queue-position data for HFT.

# HFT Results Summary

This note summarizes the saved HFT microstructure evidence in `Results/`. The results come from an execution-aware quote-replay simulator and should be read as research diagnostics, not live trading evidence.

## Research Setup

- Instruments for current real-quote evidence: SPY, QQQ, and IWM.
- Replay style: open-window top-of-book quote replay.
- Preserved generated output: historical-style SPY diagnostics plus current SPY/QQQ/IWM real-quote summaries.
- Full raw quote data: excluded due to size.
- Primary risk-adjusted metric: minute Sharpe.
- Demo reproducibility data: deterministic synthetic quotes in `Results/demo_quotes_synthetic.csv`.

Annualized Sharpe is saved in `Results/results_summary.csv` for diagnostic scaling only. It is not the main performance statistic for this intraday setup.

## Headline Historical-Style Metrics

| Run | Days | Total PnL | Avg Daily Return | Minute Sharpe | Worst DD | Trades | Win Days |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full Portfolio Heuristic All Days | 30 | 7,004.7 bps | 233.5 bps | 0.594 | -24.7 bps | 17,690 | 96.7% |
| Market Making Only All Days | 30 | 8,944.5 bps | 298.2 bps | 0.742 | -11.5 bps | 15,352 | 100.0% |
| Full Portfolio Heuristic OOS | 15 | 3,132.5 bps | 208.8 bps | 0.727 | -24.7 bps | 8,454 | 100.0% |
| Full Portfolio ML OOS | 15 | 4,088.1 bps | 272.5 bps | 0.788 | -6.2 bps | 4,952 | 100.0% |

## Historical-Style Plot Interpretation

- Cumulative PnL: the saved full-portfolio heuristic run compounds to 7,004.7 bps over 30 SPY open-window sessions.
- Daily/session PnL: the full heuristic run has a 96.7% winning-session rate in the saved results; market-making-only is smoother in this run.
- Drawdown: the full heuristic run records a worst drawdown of -24.7 bps, while the market-making-only run records -11.5 bps.
- Sleeve contribution: market making contributes the strongest standalone sleeve evidence; liquidity and momentum sleeves are smaller and less stable.
- Trade diagnostics: the base full-portfolio decision-engine comparison records 17,690 trades and a 52.0% trade win rate.

## Strategy Sleeve Evidence

`Results/strategy_sleeve_monte_carlo.csv` compares sleeves across 24 days with 8 runs per day.

| Sleeve | Avg Sharpe | Win Days | Avg Net Return | Avg Trade PnL | Worst DD | Avg Trades |
|---|---:|---:|---:|---:|---:|---:|
| SPY Open-Only Market Making | 1.511 | 91.7% | 50.36 bps | 0.197 bps | -62.84 bps | 286.76 |
| Liquidity Detection | 0.367 | 75.0% | 3.46 bps | 0.111 bps | -228.27 bps | 160.80 |
| Momentum Ignition | 0.479 | 83.3% | 10.43 bps | 0.120 bps | -49.01 bps | 107.59 |

The sleeve results are useful for attribution: market making is the strongest sleeve in the saved evidence, while liquidity detection and momentum ignition need additional validation before they should be treated as robust standalone edges.

## Restored Alpaca Real-Quote Verification

The restored Alpaca workflow downloads IEX top-of-book quotes into the ignored `Portfolio Quotes/` folder, validates them with manifests, and replays only complete sessions. The current local evidence set covers 51 complete open-window sessions for SPY, QQQ, and IWM from 2026-03-02 through 2026-05-12, excluding weekends and the 2026-04-03 market holiday.

Current complete-session coverage:

| Symbol | Manifest Rows | Complete Sessions | Backtest Sessions |
|---|---:|---:|---:|
| SPY | 52 | 51 | 51 |
| QQQ | 52 | 51 | 51 |
| IWM | 51 | 51 | 51 |

Raw quote files are excluded from git and retained locally under `Portfolio Quotes/`.

| Symbol | Mode | Sessions | Total PnL | Avg Daily PnL | Minute Sharpe | Worst DD | Trades |
|---|---|---:|---:|---:|---:|---:|---:|
| SPY | full | 51 | 11,373.0 bps | 223.0 bps | 0.635 | -20.4 bps | 29,632 |
| SPY | mm-only | 51 | 14,323.5 bps | 280.9 bps | 0.761 | -8.6 bps | 25,743 |
| QQQ | full | 51 | 8,471.4 bps | 166.1 bps | 0.426 | -15.2 bps | 39,431 |
| QQQ | mm-only | 51 | 11,660.7 bps | 228.6 bps | 0.453 | -14.3 bps | 35,247 |
| IWM | full | 51 | 4,180.6 bps | 82.0 bps | 0.255 | -19.0 bps | 20,656 |
| IWM | mm-only | 51 | 6,209.2 bps | 121.7 bps | 0.382 | -12.2 bps | 17,080 |

Market making remains the dominant sleeve, which is why the real-quote stress grid is treated as the main validation artifact rather than the raw headline PnL.

## Cross-Symbol Baseline Summary

`Results/alpaca_real_quote_cross_symbol_summary.csv` is produced by the multi-symbol orchestration script and keeps the current local real-quote baseline evidence in one compact table.

| Symbol | Complete Sessions | Backtest Sessions | Full PnL | Full Minute Sharpe | Full Trades | MM PnL | MM Minute Sharpe | MM Trades |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY | 51 | 51 | 11,373.0 bps | 0.635 | 29,632 | 14,323.5 bps | 0.761 | 25,743 |
| QQQ | 51 | 51 | 8,471.4 bps | 0.426 | 39,431 | 11,660.7 bps | 0.453 | 35,247 |
| IWM | 51 | 51 | 4,180.6 bps | 0.255 | 20,656 | 6,209.2 bps | 0.382 | 17,080 |

The table is useful because it separates the stronger SPY/QQQ evidence from the weaker but still positive IWM baseline. It should be expanded to additional liquid large-cap equities before making a broad robustness claim.

`Results/real_quote_evidence_ci.csv` adds bootstrap confidence intervals for average daily PnL:

| Symbol | Mode | Sessions | Avg Daily PnL | 95% CI |
|---|---|---:|---:|---:|
| SPY | full | 51 | 223.0 bps | 182.0 to 264.3 bps |
| SPY | mm-only | 51 | 280.9 bps | 232.6 to 331.2 bps |
| QQQ | full | 51 | 166.1 bps | 135.0 to 198.1 bps |
| QQQ | mm-only | 51 | 228.6 bps | 190.3 to 269.8 bps |
| IWM | full | 51 | 82.0 bps | 65.1 to 97.7 bps |
| IWM | mm-only | 51 | 121.7 bps | 102.7 to 143.3 bps |

These intervals resample days and are descriptive uncertainty estimates, not a proof of future profitability.

## Micro Alpha Quality Gate And Validation

`Results/micro_alpha_quality_sharpe_summary.csv` captures the selected market-making quality gate after the edge-floor sweep. The combined SPY/QQQ/IWM selected quality gate records:

| Version | Minute Sharpe | Daily Sharpe | Total PnL | Worst DD | Trades |
|---|---:|---:|---:|---:|---:|
| Original mm baseline | 0.513 | 2.529 | 32,193.4 bps | -14.3 bps | 78,070 |
| Selected quality gate | 0.601 | 2.876 | 32,980.4 bps | -13.7 bps | 56,646 |

`Results/micro_alpha_validation_report.md` adds a chronological train/OOS sanity check. The selected quality gate is the best tracked variant on the 31-session train window and keeps positive OOS evidence over the later 20 sessions:

| Split | Dates | Minute Sharpe | Daily Sharpe | Total PnL |
|---|---|---:|---:|---:|
| Train | 2026-03-02 to 2026-04-14 | 0.613 | 2.532 | 20,052.3 bps |
| OOS | 2026-04-15 to 2026-05-12 | 0.584 | 3.733 | 12,928.1 bps |

This reduces pure full-sample tuning risk, but it is still not a substitute for a genuinely new date range, more symbols, and execution-calibrated fills.

## Real-Quote Stress Grid

`Results/alpaca_spy_real_quote_stress_distribution_summary.csv` summarizes the SPY 51-session stress runs across three fill-randomness seeds, five adverse-selection penalties, and two portfolio modes.

| Portfolio | Adverse Selection | Runs | Mean PnL | Mean Minute Sharpe | Positive Runs |
|---|---:|---:|---:|---:|---:|
| Full portfolio | 0.00 bps | 3 | 11,250.4 bps | 0.659 | 100% |
| Full portfolio | 0.25 bps | 3 | 8,313.4 bps | 0.517 | 100% |
| Full portfolio | 0.50 bps | 3 | 5,517.3 bps | 0.381 | 100% |
| Full portfolio | 1.00 bps | 3 | 782.0 bps | 0.067 | 100% |
| Full portfolio | 2.00 bps | 3 | -2,040.6 bps | -0.230 | 0% |
| Market making only | 0.00 bps | 3 | 14,203.0 bps | 0.690 | 100% |
| Market making only | 0.25 bps | 3 | 10,626.7 bps | 0.596 | 100% |
| Market making only | 0.50 bps | 3 | 7,251.9 bps | 0.465 | 100% |
| Market making only | 1.00 bps | 3 | 1,881.6 bps | 0.131 | 100% |
| Market making only | 2.00 bps | 3 | -1,188.8 bps | -0.164 | 0% |

Interpretation: the SPY edge survives moderate adverse-selection penalties but is not robust to a 2 bps per-trade penalty. This is a useful, honest boundary. It should be used in interviews to show awareness of fill realism, queue-position limits, and adverse-selection risk.

## QQQ Real-Quote Stress Grid

The current QQQ stress sweep uses 51 complete sessions and the same seed/adverse-selection grid as SPY. It is positive through 0.5 bps adverse selection and breaks around 1 bps per completed trade. The generated file is `Results/alpaca_qqq_real_quote_stress_distribution_summary.csv`.

| Portfolio | Adverse Selection | Runs | Mean PnL | Mean Minute Sharpe | Positive Runs |
|---|---:|---:|---:|---:|---:|
| Full portfolio | 0.00 bps | 3 | 8,247.2 bps | 0.454 | 100% |
| Full portfolio | 0.50 bps | 3 | 1,603.6 bps | 0.113 | 100% |
| Full portfolio | 1.00 bps | 3 | -1,767.9 bps | -0.189 | 0% |
| Market making only | 0.00 bps | 3 | 11,337.6 bps | 0.484 | 100% |
| Market making only | 0.50 bps | 3 | 3,217.4 bps | 0.167 | 100% |
| Market making only | 1.00 bps | 3 | -891.9 bps | -0.074 | 0% |

## IWM Real-Quote Stress Grid

IWM has now been run through the same seed/adverse-selection grid on 51 retained complete sessions. Its baseline is positive, but full-mode stress is only marginal around 1 bps and fails at 2 bps. The generated file is `Results/alpaca_iwm_real_quote_stress_distribution_summary.csv`.

| Portfolio | Adverse Selection | Runs | Mean PnL | Mean Minute Sharpe | Positive Runs |
|---|---:|---:|---:|---:|---:|
| Full portfolio | 0.00 bps | 3 | 4,301.4 bps | 0.262 | 100% |
| Full portfolio | 0.50 bps | 3 | 1,376.7 bps | 0.082 | 100% |
| Full portfolio | 1.00 bps | 3 | -25.4 bps | -0.003 | 67% |
| Full portfolio | 2.00 bps | 3 | -1,555.6 bps | -0.117 | 0% |
| Market making only | 0.00 bps | 3 | 5,899.1 bps | 0.338 | 100% |
| Market making only | 0.50 bps | 3 | 2,851.2 bps | 0.149 | 100% |
| Market making only | 1.00 bps | 3 | 685.6 bps | 0.046 | 100% |
| Market making only | 2.00 bps | 3 | -826.3 bps | -0.074 | 0% |

## Real-Quote Latency Sensitivity

`Results/alpaca_spy_real_quote_latency_sensitivity.csv`, `Results/alpaca_qqq_real_quote_latency_sensitivity.csv`, and `Results/alpaca_iwm_real_quote_latency_sensitivity.csv` delay the strategy's access to the quote stream by a fixed amount before decisions are processed. The full latency table is retained in `Results/real_quote_robustness_report.md`.

| Symbol | Portfolio | Latency | Mean PnL | Minute Sharpe | Expired Signals |
|---|---|---:|---:|---:|---:|
| SPY | full | 0 us | 11,373.0 bps | 0.635 | 0 |
| SPY | full | 100,000 us | 11,641.0 bps | 0.634 | 799 |
| QQQ | full | 0 us | 8,471.4 bps | 0.426 | 0 |
| QQQ | full | 100,000 us | 8,759.0 bps | 0.429 | 1,222 |
| IWM | full | 0 us | 4,180.6 bps | 0.255 | 0 |
| IWM | full | 100,000 us | 4,241.6 bps | 0.257 | 671 |

The main takeaway is not that latency destroys the edge. It is that modest delays do not collapse the 51-session SPY/QQQ/IWM edge on this dataset, while they do cause some signals to expire past the session window. That is useful, but it is also the sort of result a recruiter may challenge, so it should be presented with care.

## Decision Engine Comparison

`Results/decision_engine_comparison.csv` shows how regime, event-intensity, and volatility overlays change the full portfolio.

| System | Days | Total PnL | Minute Sharpe | Worst DD | Trades | Trade Win Rate |
|---|---:|---:|---:|---:|---:|---:|
| Base system | 30 | 7,004.7 bps | 0.594 | -24.7 bps | 17,690 | 52.0% |
| HMM only | 30 | 3,892.2 bps | 0.592 | -13.0 bps | 17,391 | 52.2% |
| HMM + Hawkes | 30 | 3,852.6 bps | 0.701 | -7.9 bps | 17,361 | 52.8% |
| Full system | 30 | 1,364.2 bps | 0.727 | -2.5 bps | 16,243 | 56.5% |

The decision-engine overlays reduce total PnL in this saved run but improve drawdown, trade win rate, and minute Sharpe. That is useful evidence for risk control, not a claim that the most defensive configuration is always preferable.

## Demo Trade And Rejected-Signal Logs

`Results/trade_log.csv` and `Results/rejected_signals.csv` are generated from the deterministic synthetic demo stream. They are real simulator outputs, but they are not historical performance evidence.

| File | Rows | What It Shows |
|---|---:|---|
| `trade_log.csv` | 92 | Completed trade/fill records with timestamps, sleeve, side, execution type, fill prices, mid prices, spreads, gross PnL, cost/haircut, adverse-selection stress, net PnL, and portfolio weight |
| `rejected_signals.csv` | 4,505 | Signals skipped due to sampled fill misses or reentry cooldowns |

The retained logs make it easier to inspect whether trades are coming from passive spread capture, how costs affect net PnL, and how many signals fail the fill/cooldown gates.

## Demo Ablation Results

`Results/ablation_results.csv` is generated by `run_diagnostics.py` on `Results/demo_quotes_synthetic.csv`.

| Variant | Total PnL | Trades | Avg PnL / Trade | Minute Sharpe | Note |
|---|---:|---:|---:|---:|---|
| Full portfolio default | 10.44 bps | 92 | 0.113 bps | 0.985 | Default demo configuration |
| Market making only | 11.22 bps | 92 | 0.122 bps | 0.986 | Market-making sleeve only |
| Liquidity detection only | 0.00 bps | 0 | 0.000 bps | 0.000 | No trades triggered on the demo stream |
| Momentum ignition only | 0.00 bps | 0 | 0.000 bps | 0.000 | No trades triggered on the demo stream |
| Defensive decision engine | 7.44 bps | 92 | 0.081 bps | 0.963 | HMM, Hawkes-style intensity, and volatility controls |
| Portfolio low-edge gate disabled | 10.44 bps | 92 | 0.113 bps | 0.985 | Strategy-internal edge filters remain active |
| Gross exposure cap relaxed | 10.44 bps | 92 | 0.113 bps | 0.985 | Diagnostic cap relaxation only |

The demo ablation confirms that the committed engine can produce real diagnostics. It also reinforces a key risk: on this synthetic stream, market making dominates and the other sleeves do not trigger.

## Proxy Adverse-Selection Stress

`Results/latency_sensitivity.csv` is a proxy adverse-selection stress file, not true latency modelling. It subtracts additional bps from each completed trade to test how sensitive spread capture is to worse fills.

| Scenario | Total PnL | Trades | Avg PnL / Trade | Degradation vs Base |
|---|---:|---:|---:|---:|
| Base fill assumption | 10.44 bps | 92 | 0.113 bps | 0.0% |
| +0.25 bps adverse selection | -2.42 bps | 92 | -0.026 bps | 123.2% |
| +0.50 bps adverse selection | -15.29 bps | 92 | -0.166 bps | 246.4% |
| +1.00 bps adverse selection | -17.09 bps | 37 | -0.462 bps | 263.7% |
| +2.00 bps adverse selection | -38.53 bps | 37 | -1.041 bps | 469.1% |

This stress test is intentionally conservative for presentation: it shows that market-making-style results are highly sensitive to adverse selection and should be validated on real execution/fill data.

## What The Results Show

- The simulator can replay quote data, apply execution-aware assumptions, and produce retained trade/fill diagnostics.
- Market-making logic dominates the current saved sleeve evidence.
- Defensive decision-engine overlays trade off raw PnL for lower drawdown and better risk-adjusted behavior.
- The deterministic demo workflow makes logging, ablation, and adverse-selection stress reproducible without the full raw quote files.

## What The Results Do Not Prove

- They do not prove live tradability.
- They do not include exchange-accurate queue-position modeling.
- They do not include historical trade/fill logs for the full 51-session run.
- Demo diagnostics are synthetic and should not be treated as historical performance evidence.
- The demo stress test is adverse-selection proxy stress, not true timestamp-shift latency.
- The real-quote stress and latency grid covers SPY, QQQ, and IWM, but IWM has materially weaker minute Sharpe than SPY/QQQ and marginal full-mode robustness around 1 bps adverse selection.
- The saved real-quote evidence remains open-window focused and ends at 2026-05-12.

## Reviewer-Facing Files

- `Results/results_summary.csv`
- `Results/daily_results.csv`
- `Results/decision_engine_comparison.csv`
- `Results/strategy_sleeve_monte_carlo.csv`
- `Results/alpaca_real_quote_manifest.csv`
- `Results/alpaca_real_quote_results_summary.csv`
- `Results/alpaca_real_quote_daily_results.csv`
- `Results/alpaca_real_quote_mm_only_summary.csv`
- `Results/alpaca_real_quote_cross_symbol_summary.csv`
- `Results/alpaca_real_quote_cross_symbol_manifest_summary.csv`
- `Results/real_quote_evidence_ci.csv`
- `Results/real_quote_robustness_report.md`
- `Results/alpaca_spy_quote_manifest.csv`
- `Results/alpaca_qqq_quote_manifest.csv`
- `Results/alpaca_iwm_quote_manifest.csv`
- `Results/alpaca_spy_real_quote_results_summary.csv`
- `Results/alpaca_qqq_real_quote_results_summary.csv`
- `Results/alpaca_iwm_real_quote_results_summary.csv`
- `Results/alpaca_real_quote_stress_combo_results.csv`
- `Results/alpaca_real_quote_stress_distribution_summary.csv`
- `Results/alpaca_real_quote_latency_sensitivity.csv`
- `Results/alpaca_spy_real_quote_latency_sensitivity.csv`
- `Results/alpaca_qqq_real_quote_latency_sensitivity.csv`
- `Results/alpaca_iwm_real_quote_latency_sensitivity.csv`
- `Results/alpaca_spy_real_quote_stress_distribution_summary.csv`
- `Results/alpaca_qqq_real_quote_stress_distribution_summary.csv`
- `Results/alpaca_iwm_real_quote_stress_distribution_summary.csv`
- `Results/alpaca_iwm_real_quote_mm_only_summary.csv`
- `Results/micro_alpha_quality_sharpe_summary.csv`
- `Results/micro_alpha_quality_sharpe_report.md`
- `Results/micro_alpha_validation_summary.csv`
- `Results/micro_alpha_validation_report.md`
- `Results/demo_quotes_synthetic.csv`
- `Results/trade_log.csv`
- `Results/rejected_signals.csv`
- `Results/ablation_results.csv`
- `Results/latency_sensitivity.csv`
- `Plots/hft_report.png`
- `Plots/hft_real_quote_dashboard.png`
- `Plots/hft_micro_alpha_quality_sharpe.png`
- `Plots/hft_micro_alpha_validation.png`
- `Plots/hft_cross_symbol_cumulative_pnl.png`
- `Plots/hft_daily_pnl_bars.png`
- `Plots/hft_adverse_selection_stress.png`
- `Plots/hft_latency_sensitivity.png`
- `Plots/hft_bootstrap_ci.png`
- `Plots/hft_drawdown_comparison.png`

## Next Validation Steps

- Expand the real-quote stress grid to additional symbols and more market windows.
- Regenerate compact historical trade/fill diagnostics from the real-quote stress runs.
- Add true latency modelling if timestamped order/fill data is available.
- Calibrate fill, adverse-selection, and market-impact assumptions against execution data.
- Add exchange/order-event latency modelling if suitable data becomes available.
- Keep extending the pinned full-date manifest beyond 2026-05-12.
- Validate across additional symbols, sessions, and market regimes.

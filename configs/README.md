# Research Configs

These files pin the selected configurations used in the saved headline evidence:

- `micro_alpha_selected_quality.json`: SPY/QQQ/IWM market-making quality-gate configuration behind `hft_microstructure/Results/micro_alpha_quality_sharpe_report.md`, chronological validation reports, and the final research-quality scorecard.
- `medium_alpha_selected_default.json`: selected-default medium-term alpha parameters behind `medium_term_alpha/Results/selected_default_metrics.csv`.

The HFT raw quote files are intentionally excluded from git due to size, so the config records the manifests, date range, and selected parameters needed to rerun the same local evidence when the raw quote folder is available.

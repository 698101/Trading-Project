# Full Selected-Default Holdings Audit Status

Status: reproducible path added, full pinned audit not committed.

The repository currently commits `portfolio_weights.csv`, `rebalance_log.csv`, `daily_strategy_returns.csv`, and `benchmark_timeseries.csv` from `Results/sample_prices.csv`. Those files verify the audit schema and reporting path, but they are not the full selected-default holding history behind the saved headline metrics.

The missing input is a pinned full price panel for the selected universe. Summary result CSVs do not contain enough information to reconstruct historical holdings, final signals, volatility inputs, or daily benchmark-aligned returns.

To generate the full audit from a pinned dataset:

```bash
python3 scripts/export_medium_alpha_selected_audit.py \
  --csv /path/to/pinned_full_prices.csv \
  --benchmark-csv /path/to/pinned_benchmark_prices.csv \
  --output-dir medium_term_alpha/Results_full_selected_default \
  --plots-dir medium_term_alpha/Plots_full_selected_default
```

If benchmark prices are included in the same CSV under `SPY`, `--benchmark-csv` can be omitted. The export script passes the selected-default parameters explicitly and writes `audit_manifest.csv` plus `audit_manifest.md` in the output directory.

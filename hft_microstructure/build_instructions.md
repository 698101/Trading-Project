# Build Instructions

These commands are intended for the flattened C++ research project in `hft_microstructure/`.

## Primary Simulator

Compile with `g++`:

```powershell
g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o hft_portfolio.exe main.cpp
```

Run the deterministic demo diagnostics:

```powershell
python run_diagnostics.py
```

The demo script uses `Results/demo_quotes_synthetic.csv`, writes retained diagnostics, and does not alter the saved historical-style result summary files.

## Demo Outputs

`run_diagnostics.py` writes:

- `Results/demo_quotes_synthetic.csv`
- `Results/trade_log.csv`
- `Results/rejected_signals.csv`
- `Results/ablation_results.csv`
- `Results/latency_sensitivity.csv`

The demo quote stream is synthetic and exists only to verify the engine, trade logging, rejected-signal logging, ablation workflow, and proxy adverse-selection stress.

## Quote-Format Smoke Test

`Results/sample_quotes.csv` is a small quote-format sample. It may generate zero trades, which is acceptable for parser validation.

```powershell
.\hft_portfolio.exe Results\sample_quotes.csv --rolling-window 75 --min-edge-bps 0.20 --forecast-weight 0.70 --min-reentry-events 40 --interval-seconds 60 --max-gross-exposure 1.0 --seed 1337 --forecast-mode heuristic --portfolio-mode full --decision-mode off
```

## Trade And Rejected-Signal Logging

Use explicit log paths when you want retained diagnostics:

```powershell
.\hft_portfolio.exe Results\demo_quotes_synthetic.csv --rolling-window 75 --min-edge-bps 0.20 --forecast-weight 0.70 --min-reentry-events 40 --interval-seconds 60 --max-gross-exposure 1.0 --seed 1337 --forecast-mode heuristic --portfolio-mode full --decision-mode off --trade-log-path Results\trade_log.csv --rejected-signals-path Results\rejected_signals.csv
```

Use proxy adverse-selection stress:

```powershell
.\hft_portfolio.exe Results\demo_quotes_synthetic.csv --adverse-selection-bps 0.50
```

The adverse-selection flag subtracts the specified bps from each completed trade. It is not true latency modelling.

## Optional ML Edge Tool

```powershell
g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o ml_edge_model.exe ml_edge_model.cpp
```

The ML edge tool expects trade-level outputs from simulator runs. It is included as research tooling, not as a required dependency for plotting the saved results.

## Optional Data Tools

`microstructure_engine.cpp` preserves quote-ingestion and downloader utilities behind compile-time switches:

```powershell
g++ -std=c++17 -O2 -DBUILD_DATA_FUNNEL -o data_funnel.exe microstructure_engine.cpp
g++ -std=c++17 -O2 -DBUILD_QUOTE_DOWNLOADER -o quote_downloader.exe microstructure_engine.cpp
```

These optional tools may require Windows networking headers or third-party dependencies that are not needed for the primary simulator build.

## Expected Inputs

- `Results/sample_quotes.csv` for quote-format smoke testing.
- `Results/demo_quotes_synthetic.csv` for deterministic logging/diagnostic reproduction.
- Larger quote CSVs with columns `timestamp_ns,symbol,bid_price,ask_price,bid_size,ask_size` for full validation.

## Expected Outputs

When an output prefix is provided under `Results/`, the simulator writes:

- `Results/{output_prefix}_trades.csv`
- `Results/{output_prefix}_intervals.csv`
- Console summary metrics.

When explicit diagnostic paths are provided, the simulator writes:

- `Results/trade_log.csv`
- `Results/rejected_signals.csv`

## Regenerate Reviewer Plots

```powershell
pip install -r requirements.txt
python generate_plots.py
```

The plotting script reads saved CSVs from `Results/` and writes PNG charts to `Plots/`, including demo ablation, adverse-selection stress, trade PnL distribution, and rejected-signal reason plots when those CSVs are present.

## Troubleshooting

- If a dynamically linked MinGW build fails to launch, use the static flags shown above.
- If `Results/sample_quotes.csv` produces zero trades, use `python run_diagnostics.py`; the sample file is intentionally small.
- If plots fail to regenerate, confirm that `pandas` and `matplotlib` are installed and that the expected CSVs exist in `Results/`.
- Full 30-session result reproduction requires the excluded raw quote files.

#!/usr/bin/env python3
"""Export medium-alpha selected-default audit files from a pinned price panel.

The committed medium-alpha audit CSVs are generated from the small sample price
file. This wrapper makes the full selected-default audit reproducible when a
full price snapshot is supplied, without relying on hidden notebook state.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
MEDIUM_MAIN = ROOT / "medium_term_alpha" / "main.py"
ROBUSTNESS_SCRIPT = ROOT / "scripts" / "analyze_medium_alpha_evidence.py"

AUDIT_FILES = (
    "portfolio_weights.csv",
    "rebalance_log.csv",
    "daily_strategy_returns.csv",
    "benchmark_timeseries.csv",
    "selected_default_metrics.csv",
    "benchmark_comparison.csv",
)

REQUIRED_CHILD_MODULES = ("pandas", "numpy", "matplotlib")

SELECTED_DEFAULT_ARGS = (
    "--top-quantile",
    "0.25",
    "--cost-bps",
    "5.0",
    "--negative-trend-scale",
    "0.40",
    "--high-volatility-scale",
    "0.40",
    "--signal-change-threshold",
    "0.05",
    "--max-position-size",
    "0.06",
    "--short-mode",
    "none",
    "--short-exposure-fraction",
    "0.0",
    "--min-signal-strength",
    "0.85",
    "--multi-momentum-weight",
    "0.55",
    "--mean-reversion-weight",
    "0.25",
    "--quality-weight",
    "0.20",
    "--short-term-reversal-penalty",
    "0.15",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the medium-alpha selected default and export holdings/return audit files."
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Pinned full price CSV or folder. Required unless --allow-online is used.",
    )
    parser.add_argument("--benchmark-csv", default=None, help="Optional pinned benchmark price CSV or folder.")
    parser.add_argument("--tickers", default=None, help="Optional comma-separated universe override.")
    parser.add_argument("--start", default="2018-01-01", help="Start date passed to medium_term_alpha/main.py.")
    parser.add_argument("--end", default=None, help="Optional end date passed to medium_term_alpha/main.py.")
    parser.add_argument("--benchmark", default="SPY", help="Benchmark ticker.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "build" / "medium_alpha_selected_default_audit" / "Results"),
        help="Output directory for selected-default audit CSVs.",
    )
    parser.add_argument(
        "--plots-dir",
        default=str(ROOT / "build" / "medium_alpha_selected_default_audit" / "Plots"),
        help="Output directory for generated plots.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for the child scripts.",
    )
    parser.add_argument(
        "--allow-online",
        action="store_true",
        help="Allow medium_term_alpha/main.py to download online data when --csv is omitted.",
    )
    parser.add_argument(
        "--skip-robustness-report",
        action="store_true",
        help="Skip regenerating bootstrap/negative-control/scorecard files after the audit run.",
    )
    return parser


def build_main_command(args: argparse.Namespace) -> list[str]:
    if not args.csv and not args.allow_online:
        raise ValueError("Provide --csv with a pinned full price panel, or pass --allow-online explicitly.")

    command = [
        args.python,
        str(MEDIUM_MAIN),
        "--start",
        args.start,
        "--benchmark",
        args.benchmark,
        "--output-dir",
        str(args.output_dir),
        "--plots-dir",
        str(args.plots_dir),
    ]
    if args.end:
        command.extend(["--end", args.end])
    if args.tickers:
        command.extend(["--tickers", args.tickers])
    if args.csv:
        command.extend(["--csv", str(args.csv)])
    if args.benchmark_csv:
        command.extend(["--benchmark-csv", str(args.benchmark_csv)])
    command.extend(SELECTED_DEFAULT_ARGS)
    return command


def build_robustness_command(args: argparse.Namespace) -> list[str]:
    return [args.python, str(ROBUSTNESS_SCRIPT), "--results-dir", str(args.output_dir)]


def missing_child_modules(python_executable: str) -> list[str]:
    check_code = (
        "import importlib.util, sys; "
        "missing=[name for name in sys.argv[1:] if importlib.util.find_spec(name) is None]; "
        "print('\\n'.join(missing)); "
        "raise SystemExit(1 if missing else 0)"
    )
    result = subprocess.run(
        [python_executable, "-c", check_code, *REQUIRED_CHILD_MODULES],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        return max(0, sum(1 for _ in csv.reader(handle)) - 1)


def write_manifest(output_dir: Path, source: str, commands: Iterable[Sequence[str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_csv = output_dir / "audit_manifest.csv"
    with manifest_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "rows", "source_dataset"])
        writer.writeheader()
        for filename in AUDIT_FILES:
            writer.writerow(
                {
                    "file": filename,
                    "rows": count_csv_rows(output_dir / filename),
                    "source_dataset": source,
                }
            )

    command_lines = [" ".join(command) for command in commands]
    manifest_md = output_dir / "audit_manifest.md"
    manifest_md.write_text(
        "\n".join(
            [
                "# Medium-Alpha Selected-Default Audit Manifest",
                "",
                f"- Source dataset: `{source}`",
                f"- Output directory: `{output_dir}`",
                "- Selected default parameters are passed explicitly by `scripts/export_medium_alpha_selected_audit.py`.",
                "- The audit is full-run evidence only when the source dataset is a pinned full price panel.",
                "",
                "## Commands",
                "",
                "```bash",
                *command_lines,
                "```",
                "",
                "## Files",
                "",
                "| File | Rows |",
                "|---|---:|",
                *[
                    f"| `{filename}` | {count_csv_rows(output_dir / filename)} |"
                    for filename in AUDIT_FILES
                ],
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output_dir = Path(args.output_dir)
    args.plots_dir = Path(args.plots_dir)

    missing_modules = missing_child_modules(args.python)
    if missing_modules:
        raise ValueError(
            "Missing Python packages for medium_term_alpha/main.py: "
            + ", ".join(missing_modules)
            + ". Install medium_term_alpha/requirements.txt or pass --python pointing to an environment that has them."
        )

    main_command = build_main_command(args)
    commands: list[list[str]] = [main_command]
    subprocess.run(main_command, check=True)

    if not args.skip_robustness_report:
        robustness_command = build_robustness_command(args)
        commands.append(robustness_command)
        subprocess.run(robustness_command, check=True)

    source = str(args.csv) if args.csv else "online_download"
    write_manifest(args.output_dir, source, commands)
    print(f"audit_manifest={args.output_dir / 'audit_manifest.csv'}")
    print(f"audit_summary={args.output_dir / 'audit_manifest.md'}")
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except ValueError as exc:
        print(f"error={exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()

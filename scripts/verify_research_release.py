#!/usr/bin/env python3
"""Verify that the committed research release is internally consistent."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"ghp" + r"_[A-Za-z0-9_]+",
        r"APCA_API_" + r"SECRET_KEY='[^']+'",
        r"APCA_API_" + r"KEY_ID='[^']+'",
        r"PK[A-Z0-9]{20,}",
        r"Gq" + r"wx[A-Za-z0-9]+",
        r"PRIVATE" + r" KEY",
    ]
]

DOCS = [
    "README.md",
    "REVIEWER_GUIDE.md",
    "FINAL_RESEARCH_MEMO.md",
    "PROJECT_SCORECARD.md",
    "hft_microstructure/README.md",
    "hft_microstructure/RESULTS_SUMMARY.md",
    "medium_term_alpha/README.md",
    "medium_term_alpha/RESULTS_SUMMARY.md",
]

REQUIRED_ARTIFACTS = [
    "PROJECT_SCORECARD.md",
    "hft_microstructure/Results/micro_alpha_quality_sharpe_summary.csv",
    "hft_microstructure/Results/micro_alpha_validation_summary.csv",
    "hft_microstructure/Results/micro_alpha_extended_validation_summary.csv",
    "hft_microstructure/Results/micro_alpha_statistical_diagnostics.csv",
    "hft_microstructure/Results/micro_alpha_walk_forward_folds.csv",
    "hft_microstructure/Results/micro_alpha_research_quality_scorecard.csv",
    "hft_microstructure/Results/micro_alpha_research_quality_report.md",
    "hft_microstructure/Plots/hft_micro_alpha_research_quality.png",
    "hft_microstructure/Plots/hft_micro_alpha_quality_sharpe.png",
    "hft_microstructure/Plots/hft_micro_alpha_validation.png",
    "hft_microstructure/Plots/hft_micro_alpha_extended_validation.png",
    "medium_term_alpha/Results/selected_default_metrics.csv",
    "medium_term_alpha/Results/medium_alpha_robustness_scorecard.csv",
    "medium_term_alpha/Plots/medium_term_alpha_report.png",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def safe_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def find_row(rows: list[dict[str, str]], **matches: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in matches.items()):
            return row
    return {}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def verify_required_artifacts(root: Path, errors: list[str]) -> None:
    for relative in REQUIRED_ARTIFACTS:
        path = root / relative
        if not path.exists():
            fail(errors, f"missing required artifact: {relative}")
        elif path.is_file() and path.stat().st_size == 0:
            fail(errors, f"empty required artifact: {relative}")


def verify_docs(root: Path, errors: list[str]) -> None:
    markers = ("<<<<<<<", "=======", ">>>>>>>")
    for relative in DOCS:
        path = root / relative
        if not path.exists():
            fail(errors, f"missing doc: {relative}")
            continue
        text = path.read_text(encoding="utf-8-sig")
        for marker in markers:
            if marker in text:
                fail(errors, f"merge conflict marker {marker!r} in {relative}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                fail(errors, f"possible secret in {relative}: {pattern.pattern}")


def verify_scripts_and_configs(root: Path, errors: list[str]) -> None:
    for folder in ["scripts", "configs"]:
        for path in (root / folder).glob("**/*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.name == "verify_research_release.py":
                continue
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    fail(errors, f"possible secret in {path.relative_to(root)}: {pattern.pattern}")


def verify_metrics(root: Path, errors: list[str]) -> None:
    hft_results = root / "hft_microstructure" / "Results"
    medium_results = root / "medium_term_alpha" / "Results"
    quality_rows = read_csv(hft_results / "micro_alpha_quality_sharpe_summary.csv")
    validation_rows = read_csv(hft_results / "micro_alpha_validation_summary.csv")
    diagnostic_rows = read_csv(hft_results / "micro_alpha_statistical_diagnostics.csv")
    fold_rows = read_csv(hft_results / "micro_alpha_walk_forward_folds.csv")
    gate_rows = read_csv(hft_results / "micro_alpha_research_quality_scorecard.csv")
    medium_rows = read_csv(medium_results / "selected_default_metrics.csv")

    combined = find_row(quality_rows, scope="combined")
    if safe_float(combined.get("minute_sharpe")) < 0.60:
        fail(errors, "selected combined micro-alpha minute Sharpe below 0.60")
    if safe_float(combined.get("daily_sharpe")) < 2.80:
        fail(errors, "selected combined micro-alpha daily Sharpe below 2.80")

    oos = find_row(validation_rows, variant="selected_quality_gate", split="oos", scope="combined")
    if safe_float(oos.get("minute_sharpe")) < 0.58:
        fail(errors, "selected OOS minute Sharpe below 0.58")

    selected_all = find_row(diagnostic_rows, scope="selected_quality_gate_all")
    if safe_float(selected_all.get("bonferroni_confidence_gt_zero")) < 0.95:
        fail(errors, "micro-alpha Bonferroni confidence sanity check below 0.95")

    if len(fold_rows) < 3:
        fail(errors, "micro-alpha chronological fold table has fewer than three folds")
    for row in fold_rows:
        if safe_float(row.get("total_pnl_bps")) <= 0.0:
            fail(errors, f"micro-alpha fold {row.get('fold')} is not PnL-positive")

    pass_count = sum(1 for row in gate_rows if row.get("status") == "pass")
    fail_count = sum(1 for row in gate_rows if row.get("status") == "fail")
    if pass_count < 8:
        fail(errors, "micro-alpha research quality scorecard has fewer than 8 pass gates")
    if fail_count > 1:
        fail(errors, "micro-alpha research quality scorecard has more than one fail gate")

    medium = medium_rows[0] if medium_rows else {}
    if safe_float(medium.get("annualized_sharpe")) < 1.40:
        fail(errors, "medium alpha annualized Sharpe below 1.40")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    errors: list[str] = []
    verify_required_artifacts(root, errors)
    verify_docs(root, errors)
    verify_scripts_and_configs(root, errors)
    verify_metrics(root, errors)
    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("research_release_verification=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

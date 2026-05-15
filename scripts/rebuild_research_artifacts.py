#!/usr/bin/env python3
"""Rebuild the reviewer-facing research artifacts in dependency order."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--skip-build-dependent", action="store_true", help="Skip micro-alpha reports that require local build/ quote replay outputs.")
    parser.add_argument("--skip-plots", action="store_true")
    parser.add_argument("--skip-medium", action="store_true")
    return parser.parse_args()


def run(root: Path, command: list[str]) -> None:
    print("run=" + " ".join(command), flush=True)
    subprocess.run(command, cwd=root, check=True)


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    python = sys.executable
    run(root, [python, "scripts/analyze_real_quote_evidence.py", "--symbols", "SPY,QQQ,IWM"])
    if not args.skip_build_dependent:
        run(root, [python, "scripts/analyze_micro_alpha_validation.py"])
        run(root, [python, "scripts/summarize_micro_alpha_extended_validation.py"])
        run(root, [python, "scripts/analyze_micro_alpha_research_quality.py"])
    if not args.skip_medium:
        run(root, [python, "scripts/analyze_medium_alpha_evidence.py", "--results-dir", "medium_term_alpha/Results"])
    run(root, [python, "scripts/build_project_scorecard.py"])
    if not args.skip_plots:
        run(root, [python, "scripts/generate_citadel_plots.py"])
    run(root, [python, "scripts/verify_research_release.py"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

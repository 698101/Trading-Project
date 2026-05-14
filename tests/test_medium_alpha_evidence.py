from __future__ import annotations

import importlib.util
import random
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analysis = load_script("analyze_medium_alpha_evidence")
audit_export = load_script("export_medium_alpha_selected_audit")


class MediumAlphaMetricTests(unittest.TestCase):
    def test_total_return_and_drawdown(self) -> None:
        returns = [0.10, -0.05, 0.02]
        self.assertAlmostEqual(analysis.total_return(returns), (1.10 * 0.95 * 1.02) - 1.0)
        self.assertAlmostEqual(analysis.max_drawdown(returns), -0.05)

    def test_percentile_interpolates(self) -> None:
        self.assertEqual(analysis.percentile([1.0, 2.0, 3.0], 0.5), 2.0)
        self.assertAlmostEqual(analysis.percentile([1.0, 3.0], 0.25), 1.5)

    def test_sign_flip_control_detects_consistent_positive_returns(self) -> None:
        returns = [0.02] * 24
        rows = analysis.sign_flip_controls(returns, samples=200, rng=random.Random(7))
        self.assertEqual(len(rows), 1)
        self.assertLess(float(rows[0]["p_value_control_total_return_ge_observed"]), 0.05)


class MediumAlphaScorecardTests(unittest.TestCase):
    def test_scorecard_flags_point_in_time_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = Path(tmpdir)
            (results / "results_summary.csv").write_text(
                "metric,value\nannualized_sharpe,1.2\nmax_drawdown,-0.1\n"
            )
            (results / "benchmark_comparison.csv").write_text(
                "metric,momentum_strategy,SPY\nannualized_sharpe,1.2,0.8\nmax_drawdown,-0.1,-0.2\n"
            )
            (results / "selected_default_metrics.csv").write_text(
                "top_quantile,positive_walk_forward_years,walk_forward_year_count,worst_walk_forward_year_sharpe\n"
                "0.25,3,4,-0.5\n"
            )
            (results / "walk_forward_results.csv").write_text(
                "annualized_sharpe\n1.0\n-0.5\n1.2\n"
            )
            (results / "sensitivity_results.csv").write_text(
                "top_quantile,cost_bps,annualized_sharpe\n0.25,5.0,1.1\n0.25,10.0,1.0\n"
            )
            (results / "capacity_simulation.csv").write_text(
                "capital_scale,annualized_sharpe\n20.0,1.1\n"
            )
            (results / "factor_behavior_summary.csv").write_text(
                "metric,value\nmomentum_dominance_share,1.0\n"
            )
            ci_rows = [{"metric": "annualized_sharpe", "ci95_low": "0.8"}]
            control_rows = [{"p_value_control_sharpe_ge_observed": "0.01"}]
            rows = analysis.scorecard_rows(results, ci_rows, control_rows)
            status_by_check = {row["check"]: row["status"] for row in rows}
            self.assertEqual(status_by_check["point_in_time_universe"], "fail")
            self.assertEqual(status_by_check["momentum_dominance_share"], "warn")


class MediumAlphaAuditExportTests(unittest.TestCase):
    def test_requires_pinned_csv_unless_online_is_explicit(self) -> None:
        args = audit_export.build_parser().parse_args([])
        with self.assertRaises(ValueError):
            audit_export.build_main_command(args)

    def test_builds_selected_default_command_with_explicit_parameters(self) -> None:
        args = audit_export.build_parser().parse_args(
            [
                "--csv",
                "prices.csv",
                "--output-dir",
                "out",
                "--plots-dir",
                "plots",
                "--python",
                "python3",
            ]
        )
        command = audit_export.build_main_command(args)
        self.assertIn("--csv", command)
        self.assertIn("prices.csv", command)
        self.assertIn("--min-signal-strength", command)
        self.assertIn("0.85", command)
        self.assertIn("--short-mode", command)
        self.assertIn("none", command)


if __name__ == "__main__":
    unittest.main()

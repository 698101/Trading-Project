from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scorecard = load_script("build_project_scorecard")
micro_validation = load_script("analyze_micro_alpha_validation")
extended_validation = load_script("summarize_micro_alpha_extended_validation")
research_quality = load_script("analyze_micro_alpha_research_quality")
release_verify = load_script("verify_research_release")


class ReviewerDocsTests(unittest.TestCase):
    def test_reviewer_docs_have_no_merge_conflict_markers(self) -> None:
        docs = [
            ROOT / "README.md",
            ROOT / "REVIEWER_GUIDE.md",
            ROOT / "FINAL_RESEARCH_MEMO.md",
        ]
        markers = ("<<<<<<<", "=======", ">>>>>>>")
        for path in docs:
            text = path.read_text(encoding="utf-8-sig")
            for marker in markers:
                self.assertNotIn(marker, text, f"{path} contains {marker}")

    def test_scorecard_is_built_from_saved_metrics(self) -> None:
        text = scorecard.build_scorecard(ROOT)
        self.assertIn("Selected quality gate", text)
        self.assertIn("9/10", text)
        self.assertIn("2.876", text)
        self.assertIn("OOS", text)
        self.assertIn("0.584", text)
        self.assertIn("Fresh core OOS", text)
        self.assertIn("0.702", text)
        self.assertIn("Final research-quality gates", text)
        self.assertIn("8 pass / 3 warn / 1 fail", text)
        self.assertIn("Annualized Sharpe", text)
        self.assertIn("1.4505", text)

    def test_micro_validation_split_keeps_train_and_oos(self) -> None:
        train, oos = micro_validation.split_dates(
            ["2026-03-05", "2026-03-03", "2026-03-04", "2026-03-02"],
            0.60,
        )
        self.assertEqual(train, ["2026-03-02", "2026-03-03", "2026-03-04"])
        self.assertEqual(oos, ["2026-03-05"])

    def test_extended_validation_formats_metrics(self) -> None:
        row = extended_validation.format_metrics(
            scope="demo",
            label="Demo",
            symbol="SPY",
            daily_rows=[{"date": "2026-05-13"}, {"date": "2026-05-14"}],
            daily_pnls=[1.0, 2.0],
            intervals=[0.1, 0.2, 0.3],
            trades=3,
            source="demo.csv",
        )
        self.assertEqual(row["sessions"], 2)
        self.assertEqual(row["start_date"], "2026-05-13")
        self.assertEqual(row["end_date"], "2026-05-14")
        self.assertEqual(row["trade_count"], 3)

    def test_research_quality_fold_split_and_psr(self) -> None:
        folds = research_quality.fold_dates(["2026-01-04", "2026-01-01", "2026-01-02"], 3)
        self.assertEqual(folds, [["2026-01-01"], ["2026-01-02"], ["2026-01-04"]])
        self.assertGreater(research_quality.probabilistic_sharpe_ratio([1.0, 1.2, 0.8, 1.1]), 0.95)

    def test_release_verifier_finds_rows(self) -> None:
        rows = [{"scope": "combined", "minute_sharpe": "0.601"}]
        self.assertEqual(release_verify.find_row(rows, scope="combined")["minute_sharpe"], "0.601")


if __name__ == "__main__":
    unittest.main()

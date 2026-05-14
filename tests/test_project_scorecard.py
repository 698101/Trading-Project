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
        self.assertIn("2.876", text)
        self.assertIn("OOS", text)
        self.assertIn("0.584", text)
        self.assertIn("Annualized Sharpe", text)
        self.assertIn("1.4505", text)

    def test_micro_validation_split_keeps_train_and_oos(self) -> None:
        train, oos = micro_validation.split_dates(
            ["2026-03-05", "2026-03-03", "2026-03-04", "2026-03-02"],
            0.60,
        )
        self.assertEqual(train, ["2026-03-02", "2026-03-03", "2026-03-04"])
        self.assertEqual(oos, ["2026-03-05"])


if __name__ == "__main__":
    unittest.main()

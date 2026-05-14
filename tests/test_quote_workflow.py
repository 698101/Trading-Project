from __future__ import annotations

import datetime as dt
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


download = load_script("download_alpaca_quotes")
repair = load_script("repair_real_quote_data")
analysis = load_script("analyze_real_quote_evidence")
manifest = load_script("build_quote_manifest")
quote_backtests = load_script("run_hft_quote_backtests")


class DownloadWindowTests(unittest.TestCase):
    def test_market_open_handles_dst(self) -> None:
        before_dst = download.market_window_utc(dt.date(2026, 3, 6), 60, False)
        after_dst = download.market_window_utc(dt.date(2026, 3, 9), 60, False)
        self.assertEqual(before_dst, ("2026-03-06T14:30:00Z", "2026-03-06T15:30:00Z"))
        self.assertEqual(after_dst, ("2026-03-09T13:30:00Z", "2026-03-09T14:30:00Z"))

    def test_market_window_offset_starts_after_open(self) -> None:
        midday = download.market_window_utc(dt.date(2026, 3, 9), 30, False, 150)
        self.assertEqual(midday, ("2026-03-09T16:00:00Z", "2026-03-09T16:30:00Z"))

    def test_chunked_windows_cover_full_range(self) -> None:
        windows = download.chunked_market_windows_utc(dt.date(2026, 3, 9), 60, 5, False)
        self.assertEqual(len(windows), 12)
        self.assertEqual(windows[0], ("2026-03-09T13:30:00Z", "2026-03-09T13:35:00Z"))
        self.assertEqual(windows[-1], ("2026-03-09T14:25:00Z", "2026-03-09T14:30:00Z"))

    def test_download_day_removes_temp_file_on_failure(self) -> None:
        original_request_json = download.request_json

        def fake_request_json(**_kwargs):
            raise RuntimeError("simulated api failure")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "spy_2026_03_09.csv"
            download.request_json = fake_request_json
            try:
                with self.assertRaises(RuntimeError):
                    download.download_day(
                        symbol="SPY",
                        day=dt.date(2026, 3, 9),
                        output_path=output_path,
                        key="key",
                        secret="secret",
                        feed="iex",
                        limit=10000,
                        window_minutes=60,
                        chunk_minutes=5,
                        fixed_1330_utc=False,
                        window_start_minutes_after_open=0,
                        sleep_seconds=0.0,
                        request_retries=0,
                        retry_sleep_seconds=0.0,
                        max_retry_sleep_seconds=0.0,
                        timeout_seconds=1.0,
                        progress_pages=0,
                    )
            finally:
                download.request_json = original_request_json
            self.assertFalse(output_path.exists())
            self.assertFalse(output_path.with_name(f"{output_path.name}.tmp").exists())

    def test_download_day_deduplicates_across_chunks(self) -> None:
        original_request_json = download.request_json
        payloads = [
            {
                "quotes": {
                    "SPY": [
                        {"t": "2026-03-09T13:30:00.000000001Z", "bp": 100.0, "ap": 100.1, "bs": 10, "as": 20}
                    ]
                }
            },
            {
                "quotes": {
                    "SPY": [
                        {"t": "2026-03-09T13:30:00.000000001Z", "bp": 100.0, "ap": 100.1, "bs": 10, "as": 20},
                        {"t": "2026-03-09T13:35:00.000000001Z", "bp": 100.2, "ap": 100.3, "bs": 11, "as": 21},
                    ]
                }
            },
        ]

        def fake_request_json(**_kwargs):
            return payloads.pop(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "spy_2026_03_09.csv"
            download.request_json = fake_request_json
            try:
                rows = download.download_day(
                    symbol="SPY",
                    day=dt.date(2026, 3, 9),
                    output_path=output_path,
                    key="key",
                    secret="secret",
                    feed="iex",
                    limit=10000,
                    window_minutes=10,
                    chunk_minutes=5,
                    fixed_1330_utc=False,
                    window_start_minutes_after_open=0,
                    sleep_seconds=0.0,
                    request_retries=0,
                    retry_sleep_seconds=0.0,
                    max_retry_sleep_seconds=0.0,
                    timeout_seconds=1.0,
                    progress_pages=0,
                )
            finally:
                download.request_json = original_request_json
            self.assertEqual(rows, 2)
            self.assertEqual(len(output_path.read_text().strip().splitlines()), 3)


class RepairPlannerTests(unittest.TestCase):
    def test_quote_dir_preserves_legacy_open_name_by_default(self) -> None:
        base = Path("Portfolio Quotes")
        self.assertEqual(repair.quote_dir(base, "SPY", 60), base / "SPY_open60")
        self.assertEqual(repair.quote_dir(base, "SPY", 30, 150), base / "SPY_open_plus_150m_30")

    def test_business_dates_skip_weekends(self) -> None:
        dates = repair.business_dates(dt.date(2026, 3, 1), dt.date(2026, 3, 9))
        self.assertEqual(
            dates,
            [
                dt.date(2026, 3, 2),
                dt.date(2026, 3, 3),
                dt.date(2026, 3, 4),
                dt.date(2026, 3, 5),
                dt.date(2026, 3, 6),
                dt.date(2026, 3, 9),
            ],
        )

    def test_ok_dates_only_accept_exact_ok_status(self) -> None:
        statuses = {"2026-03-02": "ok", "2026-03-03": "empty", "2026-03-04": "partial_window=5.0m"}
        self.assertEqual(repair.ok_dates(statuses), {"2026-03-02"})

    def test_target_limited_repair_days_does_not_add_buffer_when_target_met(self) -> None:
        dates = [dt.date(2026, 3, day) for day in range(2, 7)]
        self.assertEqual(
            repair.target_limited_repair_days(
                dates,
                current_ok_count=20,
                target_ok_sessions=20,
                target_buffer_days=2,
            ),
            [],
        )
        self.assertEqual(
            repair.target_limited_repair_days(
                dates,
                current_ok_count=18,
                target_ok_sessions=20,
                target_buffer_days=2,
            ),
            dates[:4],
        )


class ManifestValidationTests(unittest.TestCase):
    def test_duration_status_flags_partial_non_empty_files(self) -> None:
        self.assertEqual(manifest.status_with_duration("ok", 60.0, 55.0), "ok")
        self.assertEqual(manifest.status_with_duration("ok", 10.0, 55.0), "partial_window=10.00m")
        self.assertEqual(manifest.status_with_duration("empty", 0.0, 55.0), "empty")

    def test_backtest_manifest_reader_filters_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "manifest.csv"
            path.write_text(
                "date,symbol,file_path,row_count,status\n"
                "2026-05-12,SPY,a.csv,1,ok\n"
                "2026-05-13,SPY,b.csv,1,ok\n"
                "2026-05-14,SPY,c.csv,1,partial_window=10.00m\n"
            )
            rows = quote_backtests.read_manifest(
                path,
                max_sessions=10,
                start_date=dt.date(2026, 5, 13),
                end_date=dt.date(2026, 5, 14),
            )
            self.assertEqual([row["date"] for row in rows], ["2026-05-13"])


class EvidenceAnalysisTests(unittest.TestCase):
    def test_percentile_interpolates(self) -> None:
        self.assertEqual(analysis.percentile([1.0, 2.0, 3.0], 0.5), 2.0)
        self.assertAlmostEqual(analysis.percentile([1.0, 3.0], 0.25), 1.5)

    def test_evidence_rows_reads_full_results_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir)
            (results_dir / "alpaca_spy_quote_manifest.csv").write_text(
                "date,symbol,file_path,row_count,first_timestamp_ns,last_timestamp_ns,duration_minutes,"
                "min_bid,max_ask,mean_spread,median_spread,min_spread,max_spread,status\n"
                "2026-03-09,SPY,/tmp/spy.csv,2,1,2,60,1,2,1,1,1,1,ok\n"
            )
            (results_dir / "alpaca_spy_real_quote_results_summary.csv").write_text(
                "label,sessions,total_pnl_bps,avg_daily_return_bps,minute_sharpe,worst_drawdown_bps,"
                "trade_count,trade_sharpe_reference,latency_expired_signals,quote_source\n"
                "full_heuristic,1,12.5,12.5,0.4,-1.0,7,0.1,0,test\n"
            )
            (results_dir / "alpaca_spy_real_quote_daily_results.csv").write_text(
                "date,total_net_return_bps\n2026-03-09,12.5\n"
            )
            (results_dir / "alpaca_spy_real_quote_mm_only_summary.csv").write_text(
                "label,sessions,total_pnl_bps,avg_daily_return_bps,minute_sharpe,worst_drawdown_bps,"
                "trade_count,trade_sharpe_reference,latency_expired_signals,quote_source\n"
                "mm_only,1,10.0,10.0,0.3,-0.5,5,0.1,0,test\n"
            )
            (results_dir / "alpaca_spy_real_quote_mm_only_daily_results.csv").write_text(
                "date,total_net_return_bps\n2026-03-09,10.0\n"
            )
            args = SimpleNamespace(symbols="SPY", results_dir=str(results_dir), bootstrap_samples=10, seed=1)
            rows = analysis.evidence_rows(args)
            full = next(row for row in rows if row["portfolio_mode"] == "full")
            self.assertEqual(full["total_pnl_bps"], "12.5")
            self.assertEqual(full["minute_sharpe"], "0.4")


if __name__ == "__main__":
    unittest.main()

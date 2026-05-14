param(
    [string]$ManifestPath = "build\alpaca_verification\quote_manifest.csv",
    [string]$OutputDir = "build\alpaca_verification\baseline",
    [string]$ComparisonPath = "build\alpaca_verification\baseline_comparison.csv",
    [string]$MlModelPath = "",
    [int]$MaxSessions = 30
)

. "$PSScriptRoot\hft_research_common.ps1"

$root = Get-RepoRoot
$manifest = Join-Path $root $ManifestPath
$out = Join-Path $root $OutputDir
$comparison = Join-Path $root $ComparisonPath
New-Item -ItemType Directory -Force -Path $out,(Split-Path $comparison -Parent) | Out-Null

if (-not (Test-Path -LiteralPath $manifest)) {
    & "$PSScriptRoot\build_quote_manifest.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Quote manifest failed." }
}

$quoteRows = Get-VerifiedQuoteFiles -ManifestPath $manifest -MaxDays $MaxSessions
if ($quoteRows.Count -lt $MaxSessions) {
    $allManifestRows = @(Import-Csv -LiteralPath $manifest)
    $statusCounts = $allManifestRows | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }
    $reason = "Only $($quoteRows.Count) ok quote sessions found; need $MaxSessions. Status counts: $($statusCounts -join ', ')"
    [pscustomobject]@{
        run = "preflight"
        metric = "usable_quote_sessions"
        expected_value = $MaxSessions
        actual_value = $quoteRows.Count
        absolute_difference = [math]::Abs($MaxSessions - $quoteRows.Count)
        percent_difference = ""
        pass_fail = "FAIL"
        notes = $reason
    } | Export-Csv -LiteralPath $comparison -NoTypeInformation
    Write-Host "baseline_comparison=$comparison FAIL $reason"
    exit 1
}

$trainRows = @($quoteRows | Select-Object -First 15)
$oosRows = @($quoteRows | Select-Object -Skip 15 -First 15)

function Invoke-BaselineSet {
    param([object]$Candidate, [object[]]$Rows, [string]$RunName)
    $dayResults = @()
    foreach ($row in $Rows) {
        $prefix = Join-Path $out ("{0}_{1}" -f (($RunName -replace "[^A-Za-z0-9]+","_").Trim("_")), $row.date.Replace("-","_"))
        [void](Invoke-HftBacktest -QuoteFile $row.file_path -Candidate $Candidate -OutputPrefix $prefix)
        $dayResults += [pscustomobject]@{
            date = $row.date
            interval_file = "${prefix}_intervals.csv"
            trade_file = "${prefix}_trades.csv"
        }
    }
    return Get-SetMetrics -DayResults $dayResults
}

$fullHeuristic = [pscustomobject]@{
    variant_name="full_portfolio_heuristic_baseline"; portfolio_mode="full"; decision_mode="off"; window_minutes=60
    min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40
    max_gross_exposure=1.0; adverse_selection_bps=0.0
}
$mmOnly = [pscustomobject]@{
    variant_name="market_making_only_baseline"; portfolio_mode="mm-only"; decision_mode="off"; window_minutes=60
    min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40
    max_gross_exposure=1.0; adverse_selection_bps=0.0
}
$fullMl = [pscustomobject]@{
    variant_name="full_portfolio_ml_baseline"; portfolio_mode="full"; decision_mode="off"; window_minutes=60; forecast_mode="ml"; ml_model_path=$MlModelPath; min_ml_win_probability=0.52
    min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40
    max_gross_exposure=1.0; adverse_selection_bps=0.0
}

$actuals = @{
    "Full Portfolio Heuristic All Days" = Invoke-BaselineSet -Candidate $fullHeuristic -Rows $quoteRows -RunName "Full Portfolio Heuristic All Days"
    "Market Making Only All Days" = Invoke-BaselineSet -Candidate $mmOnly -Rows $quoteRows -RunName "Market Making Only All Days"
    "Full Portfolio Heuristic OOS" = Invoke-BaselineSet -Candidate $fullHeuristic -Rows $oosRows -RunName "Full Portfolio Heuristic OOS"
}
if (-not [string]::IsNullOrWhiteSpace($MlModelPath) -and (Test-Path -LiteralPath (Join-Path $root $MlModelPath))) {
    $fullMl.ml_model_path = Join-Path $root $MlModelPath
    $actuals["Full Portfolio ML OOS"] = Invoke-BaselineSet -Candidate $fullMl -Rows $oosRows -RunName "Full Portfolio ML OOS"
}

$expectedRows = @(
    [pscustomobject]@{ run="Full Portfolio Heuristic All Days"; metric="Total PnL"; expected_value=7004.7369; key="total_pnl_bps" }
    [pscustomobject]@{ run="Full Portfolio Heuristic All Days"; metric="Minute Sharpe"; expected_value=0.5939; key="minute_sharpe" }
    [pscustomobject]@{ run="Full Portfolio Heuristic All Days"; metric="Worst DD"; expected_value=-24.7019; key="worst_drawdown_bps" }
    [pscustomobject]@{ run="Full Portfolio Heuristic All Days"; metric="Trades"; expected_value=17690; key="trade_count" }
    [pscustomobject]@{ run="Market Making Only All Days"; metric="Total PnL"; expected_value=8944.5004; key="total_pnl_bps" }
    [pscustomobject]@{ run="Market Making Only All Days"; metric="Minute Sharpe"; expected_value=0.7419; key="minute_sharpe" }
    [pscustomobject]@{ run="Market Making Only All Days"; metric="Worst DD"; expected_value=-11.4796; key="worst_drawdown_bps" }
    [pscustomobject]@{ run="Market Making Only All Days"; metric="Trades"; expected_value=15352; key="trade_count" }
    [pscustomobject]@{ run="Full Portfolio Heuristic OOS"; metric="Total PnL"; expected_value=3132.4949; key="total_pnl_bps" }
    [pscustomobject]@{ run="Full Portfolio Heuristic OOS"; metric="Minute Sharpe"; expected_value=0.7275; key="minute_sharpe" }
    [pscustomobject]@{ run="Full Portfolio Heuristic OOS"; metric="Worst DD"; expected_value=-24.7019; key="worst_drawdown_bps" }
    [pscustomobject]@{ run="Full Portfolio Heuristic OOS"; metric="Trades"; expected_value=8454; key="trade_count" }
    [pscustomobject]@{ run="Full Portfolio ML OOS"; metric="Total PnL"; expected_value=4088.0824; key="total_pnl_bps" }
    [pscustomobject]@{ run="Full Portfolio ML OOS"; metric="Minute Sharpe"; expected_value=0.7879; key="minute_sharpe" }
    [pscustomobject]@{ run="Full Portfolio ML OOS"; metric="Worst DD"; expected_value=-6.1547; key="worst_drawdown_bps" }
    [pscustomobject]@{ run="Full Portfolio ML OOS"; metric="Trades"; expected_value=4952; key="trade_count" }
)

$rows = @()
foreach ($expected in $expectedRows) {
    if (-not $actuals.ContainsKey($expected.run)) {
        $rows += [pscustomobject]@{
            run = $expected.run
            metric = $expected.metric
            expected_value = $expected.expected_value
            actual_value = ""
            absolute_difference = ""
            percent_difference = ""
            pass_fail = "FAIL"
            notes = "ML baseline requires -MlModelPath pointing to the saved model used for documented ML evidence; no model path was provided or found"
        }
        continue
    }
    $actual = [double]$actuals[$expected.run].PSObject.Properties[$expected.key].Value
    $tol = Test-MetricTolerance -Expected ([double]$expected.expected_value) -Actual $actual -Metric $expected.metric
    $rows += [pscustomobject]@{
        run = $expected.run
        metric = $expected.metric
        expected_value = $expected.expected_value
        actual_value = "{0:F6}" -f $actual
        absolute_difference = "{0:F6}" -f $tol.absolute_difference
        percent_difference = "{0:F8}" -f $tol.percent_difference
        pass_fail = $tol.pass_fail
        notes = if ($tol.pass_fail -eq "PASS") { "within tolerance" } else { "check quote folder, missing days/date range, market window, feed, data revision, simulator config, or compile/runtime command" }
    }
}

$rows | Export-Csv -LiteralPath $comparison -NoTypeInformation
$failed = @($rows | Where-Object { $_.pass_fail -ne "PASS" })
if ($failed.Count -gt 0) {
    Write-Host "baseline_comparison=$comparison FAIL failed_metrics=$($failed.Count)"
    exit 1
}

Write-Host "baseline_comparison=$comparison PASS"

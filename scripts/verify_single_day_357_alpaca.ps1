param(
    [string]$QuoteFile = "Portfolio Quotes\SPY_open60\spy_2026_04_15.csv",
    [string]$OutputPath = "build\alpaca_verification\single_day_357_comparison.csv"
)

. "$PSScriptRoot\hft_research_common.ps1"

$root = Get-RepoRoot
$fullQuote = Join-Path $root $QuoteFile
$fullOutput = Join-Path $root $OutputPath
New-Item -ItemType Directory -Force -Path (Split-Path $fullOutput -Parent) | Out-Null

function New-SingleDayRow {
    param([string]$Metric, [double]$Expected, [double]$Actual, [string]$Notes)
    $tol = Test-MetricTolerance -Expected $Expected -Actual $Actual -Metric $Metric
    return [pscustomobject]@{
        run = "SPY Open-Only Market Making 2026-04-15"
        metric = $Metric
        expected_value = $Expected
        actual_value = "{0:F6}" -f $Actual
        absolute_difference = "{0:F6}" -f $tol.absolute_difference
        percent_difference = "{0:F8}" -f $tol.percent_difference
        pass_fail = $tol.pass_fail
        notes = $Notes
    }
}

if (-not (Test-Path -LiteralPath $fullQuote)) {
    [pscustomobject]@{
        run = "SPY Open-Only Market Making 2026-04-15"
        metric = "quote_file"
        expected_value = "present"
        actual_value = "missing"
        absolute_difference = ""
        percent_difference = ""
        pass_fail = "FAIL"
        notes = "missing quote file: $fullQuote"
    } | Export-Csv -LiteralPath $fullOutput -NoTypeInformation
    Write-Host "single_day_357_comparison=$fullOutput FAIL missing_quote_file"
    exit 1
}

$stats = Read-QuoteStats -Path $fullQuote
if ($stats.status -ne "ok") {
    [pscustomobject]@{
        run = "SPY Open-Only Market Making 2026-04-15"
        metric = "quote_file_status"
        expected_value = "ok"
        actual_value = $stats.status
        absolute_difference = ""
        percent_difference = ""
        pass_fail = "FAIL"
        notes = "single-day reference requires real quote rows; row_count=$($stats.row_count)"
    } | Export-Csv -LiteralPath $fullOutput -NoTypeInformation
    Write-Host "single_day_357_comparison=$fullOutput FAIL status=$($stats.status)"
    exit 1
}

$candidate = [pscustomobject]@{
    variant_name="single_day_mm_357_reference"; portfolio_mode="mm-only"; decision_mode="off"; window_minutes=60
    min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40
    max_gross_exposure=1.0; adverse_selection_bps=0.0
}
$prefix = Join-Path $root "build\alpaca_verification\single_day_357_mm"
$metrics = Invoke-HftBacktest -QuoteFile $fullQuote -Candidate $candidate -OutputPrefix $prefix
$tradeFile = "${prefix}_trades.csv"
$trades = if (Test-Path -LiteralPath $tradeFile) { @(Import-Csv -LiteralPath $tradeFile) } else { @() }

$net = 0.0
$maxDd = 0.0
$peak = 0.0
$equity = 0.0
foreach ($trade in $trades) {
    $pnl = [double]$trade.net_return_bps
    $net += $pnl
    $equity += $pnl
    if ($equity -gt $peak) { $peak = $equity }
    $dd = $peak - $equity
    if ($dd -gt $maxDd) { $maxDd = $dd }
}
$avgTrade = if ($trades.Count -gt 0) { $net / $trades.Count } else { 0.0 }
$tradeSharpe = [double]$metrics["trade_sharpe_reference"]

$rows = @(
    (New-SingleDayRow -Metric "Sharpe" -Expected 3.5793 -Actual $tradeSharpe -Notes "single-day trade-based Monte Carlo reference; not 30-session minute Sharpe")
    (New-SingleDayRow -Metric "Net Return" -Expected 130.3833 -Actual $net -Notes "single-day net return bps")
    (New-SingleDayRow -Metric "Avg Trade" -Expected 0.2537 -Actual $avgTrade -Notes "single-day average trade bps")
    (New-SingleDayRow -Metric "Max DD" -Expected 15.9269 -Actual $maxDd -Notes "single-day max drawdown bps")
    (New-SingleDayRow -Metric "Trades" -Expected 515.3750 -Actual $trades.Count -Notes "actual simulator trade count compared to old Monte Carlo reference")
)
$rows | Export-Csv -LiteralPath $fullOutput -NoTypeInformation
$failed = @($rows | Where-Object { $_.pass_fail -ne "PASS" })
if ($failed.Count -gt 0) {
    Write-Host "single_day_357_comparison=$fullOutput FAIL failed_metrics=$($failed.Count)"
    exit 1
}
Write-Host "single_day_357_comparison=$fullOutput PASS"

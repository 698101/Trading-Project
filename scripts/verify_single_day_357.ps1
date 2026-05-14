param(
    [string]$QuoteFile = "Portfolio Quotes\SPY_open60\spy_2026_04_15.csv",
    [string]$OutputPath = "build\verification\single_day_357_verification.csv"
)

. "$PSScriptRoot\hft_research_common.ps1"

$root = Get-RepoRoot
$fullQuote = Join-Path $root $QuoteFile
$fullOutput = Join-Path $root $OutputPath
New-Item -ItemType Directory -Force -Path (Split-Path $fullOutput -Parent) | Out-Null

if (-not (Test-Path -LiteralPath $fullQuote)) {
    [pscustomobject]@{
        date = "2026-04-15"
        data_source = "Alpaca IEX quotes"
        verified = $false
        observed_trade_sharpe = ""
        observed_net_return_bps = ""
        observed_avg_trade_bps = ""
        observed_max_dd_bps = ""
        observed_trades = ""
        reference_sharpe = 3.5793
        reference_net_return_bps = 130.3833
        reference_avg_trade_bps = 0.2537
        reference_max_dd_bps = 15.9269
        reference_trades = 515.3750
        reason = "missing quote file"
    } | Export-Csv -LiteralPath $fullOutput -NoTypeInformation
    Write-Host "single_day_verification=$fullOutput missing_quote_file"
    exit 0
}

$candidate = [pscustomobject]@{
    variant_name="single_day_mm_reference_check"; portfolio_mode="mm-only"; decision_mode="off"; window_minutes=60
    min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40
    max_gross_exposure=1.0; adverse_selection_bps=0.0
}
$prefix = Join-Path $root "build\verification\single_day_357_mm"
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

$reason = "does not match reference"
if ([math]::Abs($tradeSharpe - 3.5793) -le 0.01) {
    $reason = "matches reference within tolerance"
} elseif ($trades.Count -eq 0) {
    $reason = "parameter/code/feed mismatch or missing usable trades"
} else {
    $reason = "quote data, date/window, feed, parameter, code, or Monte Carlo seed difference"
}

[pscustomobject]@{
    date = "2026-04-15"
    data_source = "Alpaca IEX quotes"
    verified = ([math]::Abs($tradeSharpe - 3.5793) -le 0.01)
    observed_trade_sharpe = "{0:F4}" -f $tradeSharpe
    observed_minute_sharpe = "{0:F4}" -f ([double]$metrics["minute_return_sharpe"])
    observed_net_return_bps = "{0:F4}" -f $net
    observed_avg_trade_bps = "{0:F4}" -f $avgTrade
    observed_max_dd_bps = "{0:F4}" -f $maxDd
    observed_trades = $trades.Count
    reference_sharpe = 3.5793
    reference_net_return_bps = 130.3833
    reference_avg_trade_bps = 0.2537
    reference_max_dd_bps = 15.9269
    reference_trades = 515.3750
    reason = $reason
} | Export-Csv -LiteralPath $fullOutput -NoTypeInformation

Write-Host "single_day_verification=$fullOutput trade_sharpe=$('{0:F4}' -f $tradeSharpe) reason=$reason"

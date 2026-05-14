param(
    [string]$ManifestPath = "build\alpaca_verification\quote_manifest.csv",
    [string]$OutputDir = "build\alpaca_research",
    [int]$MaxSessions = 30
)

. "$PSScriptRoot\hft_research_common.ps1"

$root = Get-RepoRoot
$manifest = Join-Path $root $ManifestPath
$out = Join-Path $root $OutputDir
$work = Join-Path $out "candidate_runs"
$windowDir = Join-Path $out "windowed_quotes"
New-Item -ItemType Directory -Force -Path $out,$work,$windowDir | Out-Null

if (-not (Test-Path -LiteralPath $manifest)) {
    throw "Manifest not found: $manifest. Run scripts\build_quote_manifest.ps1 first."
}

$quoteRows = Get-VerifiedQuoteFiles -ManifestPath $manifest -MaxDays $MaxSessions
if ($quoteRows.Count -lt 30) {
    Write-Warning "Only $($quoteRows.Count) verified sessions available. Results will use the available sessions."
}
$trainRows = @($quoteRows | Select-Object -First ([math]::Min(15, $quoteRows.Count)))
$oosRows = @($quoteRows | Select-Object -Skip $trainRows.Count -First ([math]::Min(15, [math]::Max(0, $quoteRows.Count - $trainRows.Count))))

function Invoke-CandidateSet {
    param([object]$Candidate, [object[]]$Rows, [string]$SetName)
    $dayResults = @()
    foreach ($row in $Rows) {
        $date = $row.date
        $sourceFile = $row.file_path
        $quoteFile = $sourceFile
        if ([int]$Candidate.window_minutes -lt 60) {
            $quoteFile = Join-Path $windowDir ("{0}_{1}_{2}m.csv" -f $Candidate.variant_name, $date.Replace("-","_"), $Candidate.window_minutes)
            if (-not (Test-Path -LiteralPath $quoteFile)) {
                Write-WindowQuoteFile -InputPath $sourceFile -OutputPath $quoteFile -WindowMinutes ([int]$Candidate.window_minutes)
            }
        }
        $prefix = Join-Path $work ("{0}_{1}_{2}" -f $Candidate.variant_name, $SetName, $date.Replace("-","_"))
        [void](Invoke-HftBacktest -QuoteFile $quoteFile -Candidate $Candidate -OutputPrefix $prefix)
        $dayResults += [pscustomobject]@{
            date = $date
            interval_file = "${prefix}_intervals.csv"
            trade_file = "${prefix}_trades.csv"
        }
    }
    return Get-SetMetrics -DayResults $dayResults
}

$candidates = Get-ResearchCandidates
$rawRows = @()
$rankRows = @()

foreach ($candidate in $candidates) {
    Write-Host "candidate $($candidate.variant_name)"
    $train = Invoke-CandidateSet -Candidate $candidate -Rows $trainRows -SetName "train"
    $rankRows += [pscustomobject]@{
        variant_name = $candidate.variant_name
        train_minute_sharpe = $train.minute_sharpe
        train_total_pnl_bps = $train.total_pnl_bps
        train_trade_count = $train.trade_count
    }
    $oos = Invoke-CandidateSet -Candidate $candidate -Rows $oosRows -SetName "oos"
    $all = Invoke-CandidateSet -Candidate $candidate -Rows $quoteRows -SetName "all"
    $rawRows += [pscustomobject]@{
        variant_name = $candidate.variant_name
        quote_source = "Portfolio Quotes/SPY_open60 real Alpaca quotes"
        train_days = $trainRows.Count
        oos_days = $oosRows.Count
        window_minutes = $candidate.window_minutes
        train_total_pnl_bps = "{0:F6}" -f $train.total_pnl_bps
        train_minute_sharpe = "{0:F12}" -f $train.minute_sharpe
        train_trade_count = $train.trade_count
        train_worst_drawdown_bps = "{0:F6}" -f $train.worst_drawdown_bps
        oos_total_pnl_bps = "{0:F6}" -f $oos.total_pnl_bps
        oos_minute_sharpe = "{0:F12}" -f $oos.minute_sharpe
        oos_trade_count = $oos.trade_count
        oos_worst_drawdown_bps = "{0:F6}" -f $oos.worst_drawdown_bps
        oos_trade_win_rate = "{0:F8}" -f $oos.trade_win_rate
        all_days_total_pnl_bps = "{0:F6}" -f $all.total_pnl_bps
        all_days_minute_sharpe = "{0:F12}" -f $all.minute_sharpe
        selected_on_train_only = $false
        notes = $candidate.notes
    }
}

$trainSelected = $rankRows |
    Where-Object { $_.train_trade_count -ge 50 -and $_.train_total_pnl_bps -gt 0 } |
    Sort-Object @{ Expression = "train_minute_sharpe"; Descending = $true }, @{ Expression = "train_total_pnl_bps"; Descending = $true } |
    Select-Object -First 1

if ($null -ne $trainSelected) {
    foreach ($row in $rawRows) {
        if ($row.variant_name -eq $trainSelected.variant_name) {
            $row.selected_on_train_only = $true
        }
    }
}

$gridPath = Join-Path $out "strategy_research_grid.csv"
$rawRows | Export-Csv -LiteralPath $gridPath -NoTypeInformation

& "$PSScriptRoot\compare_research_candidates.ps1" -GridPath $gridPath -OutputDir $OutputDir
Write-Host "research_grid=$gridPath candidates=$($rawRows.Count)"

param(
    [string]$ManifestPath = "build\alpaca_verification\quote_manifest.csv",
    [string]$OutputDir = "build\alpaca_research",
    [int]$MaxSessions = 30
)

. "$PSScriptRoot\hft_research_common.ps1"

$root = Get-RepoRoot
$baselineComparison = Join-Path $root "build\alpaca_verification\baseline_comparison.csv"
$singleDayComparison = Join-Path $root "build\alpaca_verification\single_day_357_comparison.csv"

foreach ($required in @($baselineComparison, $singleDayComparison)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Verification output missing: $required. Run baseline and single-day Alpaca verification before research."
    }
    $failed = @(Import-Csv -LiteralPath $required | Where-Object { $_.pass_fail -ne "PASS" })
    if ($failed.Count -gt 0) {
        throw "Verification did not pass: $required. Stop before research optimization."
    }
}

& "$PSScriptRoot\research_sharpe_357_candidates.ps1" -ManifestPath $ManifestPath -OutputDir $OutputDir -MaxSessions $MaxSessions
if ($LASTEXITCODE -ne 0) { throw "Research candidate run failed." }

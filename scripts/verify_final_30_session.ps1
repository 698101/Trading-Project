param(
    [string]$ManifestPath = "build\verification\quote_manifest.csv",
    [string]$OutputDir = "build\final_upgrade_research"
)

. "$PSScriptRoot\hft_research_common.ps1"

$root = Get-RepoRoot
$grid = Join-Path $root $OutputDir "strategy_research_grid.csv"
if (-not (Test-Path -LiteralPath $grid)) {
    & "$PSScriptRoot\research_sharpe_357_candidates.ps1" -ManifestPath $ManifestPath -OutputDir $OutputDir
    if ($LASTEXITCODE -ne 0) { throw "Research grid failed." }
} else {
    & "$PSScriptRoot\compare_research_candidates.ps1" -GridPath (Join-Path $OutputDir "strategy_research_grid.csv") -OutputDir $OutputDir
    if ($LASTEXITCODE -ne 0) { throw "Candidate comparison failed." }
}

Write-Host "final_30_session_verification=$(Join-Path $root $OutputDir)"

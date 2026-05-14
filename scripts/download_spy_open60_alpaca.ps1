param(
    [string]$Symbol = "SPY",
    [datetime]$StartDate = "2026-03-02",
    [datetime]$EndDate = "2026-04-21",
    [int]$WindowMinutes = 60,
    [string]$OutputDir = "Portfolio Quotes\SPY_open60",
    [string]$ApiKey = $env:APCA_API_KEY_ID,
    [string]$ApiSecret = $env:APCA_API_SECRET_KEY
)

. "$PSScriptRoot\hft_research_common.ps1"

if ([string]::IsNullOrWhiteSpace($ApiKey) -or [string]::IsNullOrWhiteSpace($ApiSecret)) {
    throw "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY, or pass -ApiKey and -ApiSecret."
}

$root = Get-RepoRoot
$downloader = Get-QuoteDownloaderExe
$fullOut = Join-Path $root $OutputDir
New-Item -ItemType Directory -Force -Path $fullOut | Out-Null

$env:APCA_API_KEY_ID = $ApiKey
$env:APCA_API_SECRET_KEY = $ApiSecret

foreach ($date in Get-BusinessDates -Start $StartDate -End $EndDate) {
    $fileDate = $date.ToString("yyyy_MM_dd")
    $path = Join-Path $fullOut ("{0}_{1}.csv" -f $Symbol.ToLowerInvariant(), $fileDate)
    if (Test-Path -LiteralPath $path) {
        $stats = Read-QuoteStats -Path $path
        if ($stats.row_count -gt 100) {
            Write-Host "skip existing $path rows=$($stats.row_count)"
            continue
        }
    }
    $startIso = Get-MarketOpenUtcIso -Date $date
    $endIso = Get-MarketEndUtcIso -Date $date -WindowMinutes $WindowMinutes
    Write-Host "download $Symbol $startIso $endIso -> $path"
    & $downloader $Symbol $startIso $endIso $path
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "download failed for $($date.ToString('yyyy-MM-dd')); leaving any partial file for manifest status."
    }
}

Write-Host "download_complete output_dir=$fullOut"

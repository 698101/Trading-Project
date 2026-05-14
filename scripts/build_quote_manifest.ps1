param(
    [string]$QuoteDir = "Portfolio Quotes\SPY_open60",
    [string]$OutputPath = "build\alpaca_verification\quote_manifest.csv"
)

. "$PSScriptRoot\hft_research_common.ps1"

$root = Get-RepoRoot
$fullQuoteDir = Join-Path $root $QuoteDir
$fullOutput = Join-Path $root $OutputPath
New-Item -ItemType Directory -Force -Path (Split-Path $fullOutput -Parent) | Out-Null

$rows = @()
if (Test-Path -LiteralPath $fullQuoteDir) {
    foreach ($file in Get-ChildItem -LiteralPath $fullQuoteDir -Filter "*.csv" | Sort-Object Name) {
        $dateText = ""
        if ($file.BaseName -match "(\d{4})_(\d{2})_(\d{2})") {
            $dateText = "$($Matches[1])-$($Matches[2])-$($Matches[3])"
        }
        try {
            $stats = Read-QuoteStats -Path $file.FullName
            $rows += [pscustomobject]@{
                date = $dateText
                file_path = $file.FullName
                row_count = $stats.row_count
                first_timestamp_ns = $stats.first_timestamp_ns
                last_timestamp_ns = $stats.last_timestamp_ns
                min_bid = "{0:F6}" -f $stats.min_bid
                max_ask = "{0:F6}" -f $stats.max_ask
                mean_spread = "{0:F8}" -f $stats.mean_spread
                median_spread = "{0:F8}" -f $stats.median_spread
                min_spread = "{0:F8}" -f $stats.min_spread
                max_spread = "{0:F8}" -f $stats.max_spread
                status = $stats.status
            }
        } catch {
            $rows += [pscustomobject]@{
                date = $dateText
                file_path = $file.FullName
                row_count = 0
                first_timestamp_ns = ""
                last_timestamp_ns = ""
                min_bid = "0.000000"
                max_ask = "0.000000"
                mean_spread = "0.00000000"
                median_spread = "0.00000000"
                min_spread = "0.00000000"
                max_spread = "0.00000000"
                status = "read_error: $($_.Exception.Message)"
            }
        }
    }
}

$rows | Export-Csv -LiteralPath $fullOutput -NoTypeInformation
Write-Host "manifest=$fullOutput rows=$($rows.Count)"

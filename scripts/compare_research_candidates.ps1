param(
    [string]$GridPath = "build\alpaca_research\strategy_research_grid.csv",
    [string]$OutputDir = "build\alpaca_research"
)

. "$PSScriptRoot\hft_research_common.ps1"

$root = Get-RepoRoot
$grid = Join-Path $root $GridPath
$out = Join-Path $root $OutputDir
$plots = Join-Path $out "plots"
New-Item -ItemType Directory -Force -Path $out,$plots | Out-Null

if (-not (Test-Path -LiteralPath $grid)) {
    throw "Grid not found: $grid"
}

$rows = @(Import-Csv -LiteralPath $grid)
$selected = @($rows | Where-Object { $_.selected_on_train_only -eq "True" -or $_.selected_on_train_only -eq "true" } | Select-Object -First 1)
if ($selected.Count -eq 0) {
    $selected = @($rows | Sort-Object @{ Expression = { [double]$_.train_minute_sharpe }; Descending = $true } | Select-Object -First 1)
}
$bestOosDiagnostic = $rows | Sort-Object @{ Expression = { [double]$_.oos_minute_sharpe }; Descending = $true } | Select-Object -First 1
$bestAllDiagnostic = $rows | Sort-Object @{ Expression = { [double]$_.all_days_minute_sharpe }; Descending = $true } | Select-Object -First 1

$summary = @(
    [pscustomobject]@{ metric="selected_variant_train_only"; value=$selected[0].variant_name }
    [pscustomobject]@{ metric="train_minute_sharpe"; value=$selected[0].train_minute_sharpe }
    [pscustomobject]@{ metric="oos_minute_sharpe"; value=$selected[0].oos_minute_sharpe }
    [pscustomobject]@{ metric="all_days_minute_sharpe"; value=$selected[0].all_days_minute_sharpe }
    [pscustomobject]@{ metric="oos_total_pnl_bps"; value=$selected[0].oos_total_pnl_bps }
    [pscustomobject]@{ metric="oos_worst_drawdown_bps"; value=$selected[0].oos_worst_drawdown_bps }
    [pscustomobject]@{ metric="oos_trade_count"; value=$selected[0].oos_trade_count }
    [pscustomobject]@{ metric="target_3_57_achieved_honestly"; value=([double]$selected[0].oos_minute_sharpe -ge 3.57) }
    [pscustomobject]@{ metric="best_oos_diagnostic_not_train_selected"; value=$bestOosDiagnostic.variant_name }
    [pscustomobject]@{ metric="best_oos_diagnostic_sharpe"; value=$bestOosDiagnostic.oos_minute_sharpe }
)
$summary | Export-Csv -LiteralPath (Join-Path $out "best_candidate_summary.csv") -NoTypeInformation

$comparison = @(
    [pscustomobject]@{ label="Full Portfolio Heuristic OOS Baseline"; oos_minute_sharpe=0.7275; oos_total_pnl_bps=""; oos_worst_drawdown_bps="-24.7019"; oos_trade_count=8454; notes="Prior saved baseline." }
    [pscustomobject]@{ label="Full Portfolio ML OOS Baseline"; oos_minute_sharpe=0.7879; oos_total_pnl_bps="4088.0824"; oos_worst_drawdown_bps="-6.1547"; oos_trade_count=4952; notes="Prior saved baseline." }
    [pscustomobject]@{ label="Selected Train-Only Candidate"; oos_minute_sharpe=$selected[0].oos_minute_sharpe; oos_total_pnl_bps=$selected[0].oos_total_pnl_bps; oos_worst_drawdown_bps=$selected[0].oos_worst_drawdown_bps; oos_trade_count=$selected[0].oos_trade_count; notes=$selected[0].variant_name }
    [pscustomobject]@{ label="Best OOS Diagnostic"; oos_minute_sharpe=$bestOosDiagnostic.oos_minute_sharpe; oos_total_pnl_bps=$bestOosDiagnostic.oos_total_pnl_bps; oos_worst_drawdown_bps=$bestOosDiagnostic.oos_worst_drawdown_bps; oos_trade_count=$bestOosDiagnostic.oos_trade_count; notes="Diagnostic only; not train-selected if different." }
)
$comparison | Export-Csv -LiteralPath (Join-Path $out "oos_comparison.csv") -NoTypeInformation

function New-BarPlot {
    param([object[]]$Rows, [string]$ValueColumn, [string]$Title, [string]$Path)
    Add-Type -AssemblyName System.Drawing
    $width = 1200
    $height = 720
    $bmp = [System.Drawing.Bitmap]::new($width, $height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::White)
    $font = [System.Drawing.Font]::new("Arial", 11)
    $titleFont = [System.Drawing.Font]::new("Arial", 18, [System.Drawing.FontStyle]::Bold)
    $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(42, 91, 130))
    $axisPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(70,70,70), 1)
    $g.DrawString($Title, $titleFont, [System.Drawing.Brushes]::Black, 40, 22)
    $topRows = @($Rows | Sort-Object @{ Expression = { [math]::Abs([double]$_.$ValueColumn) }; Descending = $true } | Select-Object -First 12)
    if ($topRows.Count -eq 0) {
        $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
        return
    }
    $values = @($topRows | ForEach-Object { [double]$_.$ValueColumn })
    $maxAbs = [math]::Max(0.0001, (@($values | ForEach-Object { [math]::Abs($_) }) | Measure-Object -Maximum).Maximum)
    $left = 330
    $baseY = 90
    $barH = 34
    $gap = 13
    $plotW = 760
    $zeroX = $left + 20
    $g.DrawLine($axisPen, $zeroX, $baseY - 10, $zeroX, $height - 70)
    for ($i = 0; $i -lt $topRows.Count; $i++) {
        $row = $topRows[$i]
        $value = [double]$row.$ValueColumn
        $y = $baseY + ($i * ($barH + $gap))
        $label = $row.variant_name
        if ($label.Length -gt 38) { $label = $label.Substring(0, 38) }
        $g.DrawString($label, $font, [System.Drawing.Brushes]::Black, 20, $y + 7)
        $barW = [int]([math]::Abs($value) / $maxAbs * ($plotW - 80))
        $x = if ($value -ge 0) { $zeroX } else { $zeroX - $barW }
        $barBrush = if ($value -ge 0) { $brush } else { [System.Drawing.Brushes]::IndianRed }
        $g.FillRectangle($barBrush, $x, $y, $barW, $barH)
        $g.DrawString(("{0:F4}" -f $value), $font, [System.Drawing.Brushes]::Black, ($zeroX + $barW + 8), $y + 7)
    }
    $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose()
    $bmp.Dispose()
}

try {
    New-BarPlot -Rows $rows -ValueColumn "oos_minute_sharpe" -Title "OOS Minute Sharpe" -Path (Join-Path $plots "candidate_oos_sharpe_comparison.png")
    New-BarPlot -Rows $rows -ValueColumn "oos_total_pnl_bps" -Title "OOS Total PnL Bps" -Path (Join-Path $plots "candidate_oos_pnl_comparison.png")
    New-BarPlot -Rows $rows -ValueColumn "oos_worst_drawdown_bps" -Title "OOS Worst Drawdown Bps" -Path (Join-Path $plots "candidate_drawdown_comparison.png")
    New-BarPlot -Rows $rows -ValueColumn "oos_trade_count" -Title "OOS Trade Count" -Path (Join-Path $plots "candidate_trade_count_comparison.png")
    New-BarPlot -Rows $rows -ValueColumn "all_days_minute_sharpe" -Title "Baseline vs Best Candidate Equity Proxy" -Path (Join-Path $plots "baseline_vs_best_candidate_equity.png")
} catch {
    Write-Warning "Plot creation failed: $($_.Exception.Message)"
}

$notes = @"
# Sharpe 3.57 Research Notes

Data source: real Alpaca historical quote data exported in simulator CSV format.

Validation rule: no synthetic data is used for performance validation in this research folder.

Train/OOS split: first 15 verified sessions are train/research, final 15 verified sessions are OOS validation. Candidate parameters are fixed before OOS evaluation. The selected candidate is marked by selected_on_train_only.

Prior reference:
- Single-day SPY 2026-04-15 market-making trade Sharpe target: 3.5793.
- Prior 30-session baselines: heuristic OOS 0.7275 minute Sharpe, ML OOS 0.7879 minute Sharpe, market-making all-days 0.7419 minute Sharpe.

Selected train-only candidate: $($selected[0].variant_name)
- Train minute Sharpe: $($selected[0].train_minute_sharpe)
- OOS minute Sharpe: $($selected[0].oos_minute_sharpe)
- All-days minute Sharpe: $($selected[0].all_days_minute_sharpe)
- OOS PnL bps: $($selected[0].oos_total_pnl_bps)
- OOS worst drawdown bps: $($selected[0].oos_worst_drawdown_bps)
- OOS trades: $($selected[0].oos_trade_count)

Best OOS diagnostic candidate: $($bestOosDiagnostic.variant_name), OOS minute Sharpe $($bestOosDiagnostic.oos_minute_sharpe). This is diagnostic if it differs from the train-selected candidate.

Target achieved honestly: $([double]$selected[0].oos_minute_sharpe -ge 3.57)

Method notes:
- The Sharpe formula in the C++ simulator was not changed.
- New outputs are written under build/alpaca_research.
- Raw quote CSVs are not committed by these scripts.
"@
$notes | Set-Content -LiteralPath (Join-Path $out "research_notes.md") -Encoding ASCII

Write-Host "best_candidate_summary=$(Join-Path $out 'best_candidate_summary.csv') selected=$($selected[0].variant_name)"

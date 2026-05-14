Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-PortfolioExe {
    $root = Get-RepoRoot
    $exe = Join-Path $root "hft_microstructure\hft_portfolio.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        Push-Location (Join-Path $root "hft_microstructure")
        try {
            & g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o hft_portfolio.exe main.cpp
            if ($LASTEXITCODE -ne 0) { throw "Simulator compile failed." }
        } finally {
            Pop-Location
        }
    }
    return $exe
}

function Get-QuoteDownloaderExe {
    $root = Get-RepoRoot
    $exe = Join-Path $root "hft_microstructure\quote_downloader.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        & g++ -std=c++17 -O2 -DBUILD_QUOTE_DOWNLOADER -o $exe (Join-Path $root "hft_microstructure\microstructure_engine.cpp") -lwinhttp
        if ($LASTEXITCODE -ne 0) { throw "Quote downloader compile failed." }
    }
    return $exe
}

function Get-MarketOpenUtcIso {
    param([datetime]$Date)
    return $Date.ToString("yyyy-MM-dd") + "T13:30:00Z"
}

function Get-MarketEndUtcIso {
    param([datetime]$Date, [int]$WindowMinutes = 60)
    return $Date.AddHours(13).AddMinutes(30 + $WindowMinutes).ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Get-BusinessDates {
    param([datetime]$Start, [datetime]$End)
    $dates = @()
    for ($d = $Start.Date; $d -le $End.Date; $d = $d.AddDays(1)) {
        if ($d.DayOfWeek -ne [DayOfWeek]::Saturday -and $d.DayOfWeek -ne [DayOfWeek]::Sunday) {
            $dates += $d
        }
    }
    return $dates
}

function Read-QuoteStats {
    param([string]$Path)
    $expectedHeader = "timestamp_ns,symbol,bid_price,ask_price,bid_size,ask_size"
    $reader = [System.IO.StreamReader]::new($Path)
    try {
        $header = $reader.ReadLine()
        $headerOk = ($header -eq $expectedHeader)
        $count = 0L
        $firstTs = ""
        $lastTs = ""
        $minBid = [double]::PositiveInfinity
        $maxAsk = [double]::NegativeInfinity
        $spreads = New-Object System.Collections.Generic.List[double]
        $invalidRows = 0L
        while (-not $reader.EndOfStream) {
            $line = $reader.ReadLine()
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            $cols = $line.Split(",")
            if ($cols.Count -ne 6) {
                $invalidRows++
                continue
            }
            try {
                $ts = $cols[0]
                $bid = [double]$cols[2]
                $ask = [double]$cols[3]
            } catch {
                $invalidRows++
                continue
            }
            if ($bid -le 0 -or $ask -le $bid) {
                $invalidRows++
                continue
            }
            if ($count -eq 0) { $firstTs = $ts }
            $lastTs = $ts
            $count++
            if ($bid -lt $minBid) { $minBid = $bid }
            if ($ask -gt $maxAsk) { $maxAsk = $ask }
            $mid = ($bid + $ask) * 0.5
            [void]$spreads.Add((($ask - $bid) / $mid) * 10000.0)
        }
        $meanSpread = 0.0
        $medianSpread = 0.0
        $minSpread = 0.0
        $maxSpread = 0.0
        if ($spreads.Count -gt 0) {
            $sumSpread = 0.0
            foreach ($spread in $spreads) { $sumSpread += $spread }
            $meanSpread = $sumSpread / $spreads.Count
            $sortedSpreads = @($spreads | Sort-Object)
            $middle = [int]($sortedSpreads.Count / 2)
            if (($sortedSpreads.Count % 2) -eq 0) {
                $medianSpread = ([double]$sortedSpreads[$middle - 1] + [double]$sortedSpreads[$middle]) / 2.0
            } else {
                $medianSpread = [double]$sortedSpreads[$middle]
            }
            $minSpread = [double]$sortedSpreads[0]
            $maxSpread = [double]$sortedSpreads[$sortedSpreads.Count - 1]
        }
        $statusParts = New-Object System.Collections.Generic.List[string]
        if (-not $headerOk) { [void]$statusParts.Add("bad_header") }
        if ($count -eq 0) {
            [void]$statusParts.Add("empty")
        } elseif ($count -le 100) {
            [void]$statusParts.Add("thin")
        }
        if ($invalidRows -gt 0) { [void]$statusParts.Add("invalid_rows=$invalidRows") }
        $status = if ($statusParts.Count -eq 0) { "ok" } else { $statusParts -join ";" }
        return [pscustomobject]@{
            row_count = $count
            first_timestamp_ns = $firstTs
            last_timestamp_ns = $lastTs
            min_bid = if ($count -gt 0) { $minBid } else { 0.0 }
            max_ask = if ($count -gt 0) { $maxAsk } else { 0.0 }
            mean_spread = $meanSpread
            median_spread = $medianSpread
            min_spread = $minSpread
            max_spread = $maxSpread
            status = $status
        }
    } finally {
        $reader.Close()
    }
}

function Test-MetricTolerance {
    param(
        [double]$Expected,
        [double]$Actual,
        [string]$Metric
    )
    $absoluteDifference = [math]::Abs($Actual - $Expected)
    $denominator = [math]::Max([math]::Abs($Expected), 1e-12)
    $percentDifference = $absoluteDifference / $denominator
    $pass = $false
    switch -Regex ($Metric) {
        "Sharpe" { $pass = $absoluteDifference -le 0.02; break }
        "PnL" { $pass = $percentDifference -le 0.02; break }
        "Trades" { $pass = $percentDifference -le 0.02; break }
        "DD|Drawdown" { $pass = $percentDifference -le 0.05; break }
        default { $pass = $absoluteDifference -le 1e-9 }
    }
    return [pscustomobject]@{
        absolute_difference = $absoluteDifference
        percent_difference = $percentDifference
        pass_fail = if ($pass) { "PASS" } else { "FAIL" }
    }
}

function Write-WindowQuoteFile {
    param([string]$InputPath, [string]$OutputPath, [int]$WindowMinutes)
    New-Item -ItemType Directory -Force -Path (Split-Path $OutputPath -Parent) | Out-Null
    $reader = [System.IO.StreamReader]::new($InputPath)
    $writer = [System.IO.StreamWriter]::new($OutputPath, $false)
    try {
        $header = $reader.ReadLine()
        $writer.WriteLine($header)
        $firstTs = $null
        $limit = $null
        while (-not $reader.EndOfStream) {
            $line = $reader.ReadLine()
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            $ts = [uint64]($line.Split(",")[0])
            if ($null -eq $firstTs) {
                $firstTs = $ts
                $limit = $firstTs + ([uint64]$WindowMinutes * [uint64]60 * [uint64]1000000000)
            }
            if ($ts -lt $limit) { $writer.WriteLine($line) } else { break }
        }
    } finally {
        $writer.Close()
        $reader.Close()
    }
}

function Invoke-HftBacktest {
    param(
        [string]$QuoteFile,
        [object]$Candidate,
        [string]$OutputPrefix
    )
    $exe = Get-PortfolioExe
    $forecastMode = if ($Candidate.PSObject.Properties.Name -contains "forecast_mode") { $Candidate.forecast_mode } else { "heuristic" }
    $args = @(
        $QuoteFile,
        "--rolling-window", "$($Candidate.rolling_window)",
        "--min-edge-bps", "$($Candidate.min_edge_bps)",
        "--forecast-weight", "$($Candidate.forecast_weight)",
        "--min-reentry-events", "$($Candidate.min_reentry_events)",
        "--interval-seconds", "60",
        "--max-gross-exposure", "$($Candidate.max_gross_exposure)",
        "--seed", "1337",
        "--forecast-mode", "$forecastMode",
        "--portfolio-mode", "$($Candidate.portfolio_mode)",
        "--decision-mode", "$($Candidate.decision_mode)",
        "--adverse-selection-bps", "$($Candidate.adverse_selection_bps)",
        "--output-prefix", $OutputPrefix
    )
    if ($forecastMode -eq "ml") {
        if (-not ($Candidate.PSObject.Properties.Name -contains "ml_model_path") -or
            [string]::IsNullOrWhiteSpace($Candidate.ml_model_path)) {
            throw "ML forecast mode requires Candidate.ml_model_path."
        }
        $args += @("--ml-model", "$($Candidate.ml_model_path)")
        if ($Candidate.PSObject.Properties.Name -contains "min_ml_win_probability") {
            $args += @("--min-ml-win-prob", "$($Candidate.min_ml_win_probability)")
        }
    }
    $lines = & $exe @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Backtest failed for $QuoteFile with candidate $($Candidate.variant_name): $($lines -join ' ')"
    }
    $metrics = @{}
    foreach ($line in $lines) {
        if ($line -match "^[A-Za-z_]+=" -and $line -notmatch "^sleeve=") {
            $parts = $line -split "=", 2
            $metrics[$parts[0]] = $parts[1]
        }
    }
    return $metrics
}

function Get-IntervalReturns {
    param([string[]]$IntervalFiles)
    $values = New-Object System.Collections.Generic.List[double]
    foreach ($file in $IntervalFiles) {
        if (-not (Test-Path -LiteralPath $file)) { continue }
        Import-Csv -LiteralPath $file | ForEach-Object {
            $values.Add([double]$_.interval_return_bps)
        }
    }
    return $values
}

function Get-TradeRows {
    param([string[]]$TradeFiles)
    $rows = @()
    foreach ($file in $TradeFiles) {
        if (Test-Path -LiteralPath $file) {
            $rows += Import-Csv -LiteralPath $file
        }
    }
    return $rows
}

function Get-SetMetrics {
    param([object[]]$DayResults)
    $intervalFiles = @($DayResults | ForEach-Object { $_.interval_file })
    $tradeFiles = @($DayResults | ForEach-Object { $_.trade_file })
    $returns = Get-IntervalReturns -IntervalFiles $intervalFiles
    $mean = 0.0
    $std = 0.0
    $sharpe = 0.0
    if ($returns.Count -gt 0) {
        $sum = 0.0
        foreach ($v in $returns) { $sum += $v }
        $mean = $sum / $returns.Count
        if ($returns.Count -gt 1) {
            $var = 0.0
            foreach ($v in $returns) { $var += (($v - $mean) * ($v - $mean)) }
            $std = [math]::Sqrt($var / ($returns.Count - 1))
            if ($std -ne 0.0) { $sharpe = $mean / $std }
        }
    }
    $trades = Get-TradeRows -TradeFiles $tradeFiles
    $totalPnl = 0.0
    $wins = 0
    foreach ($trade in $trades) {
        $pnl = [double]$trade.net_return_bps
        $totalPnl += $pnl
        if ($pnl -gt 0) { $wins++ }
    }
    $equity = 0.0
    $peak = 0.0
    $worstDd = 0.0
    foreach ($trade in $trades) {
        $equity += [double]$trade.net_return_bps
        if ($equity -gt $peak) { $peak = $equity }
        $dd = $equity - $peak
        if ($dd -lt $worstDd) { $worstDd = $dd }
    }
    return [pscustomobject]@{
        total_pnl_bps = $totalPnl
        minute_sharpe = $sharpe
        scaled_daily_sharpe = $sharpe * [math]::Sqrt(60.0)
        worst_drawdown_bps = $worstDd
        trade_count = $trades.Count
        trade_win_rate = if ($trades.Count -gt 0) { $wins / $trades.Count } else { 0.0 }
    }
}

function Get-ResearchCandidates {
    $rows = @()
    $rows += [pscustomobject]@{ variant_name="full_default_open60"; portfolio_mode="full"; decision_mode="off"; window_minutes=60; min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40; max_gross_exposure=1.0; adverse_selection_bps=0.0; notes="Original full heuristic baseline parameters." }
    $rows += [pscustomobject]@{ variant_name="mm_only_open60"; portfolio_mode="mm-only"; decision_mode="off"; window_minutes=60; min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40; max_gross_exposure=1.0; adverse_selection_bps=0.0; notes="Market-making sleeve only." }
    foreach ($edge in @(0.25,0.30,0.40,0.55,0.75)) {
        $rows += [pscustomobject]@{ variant_name=("mm_edge_{0:0.00}_open60" -f $edge); portfolio_mode="mm-only"; decision_mode="off"; window_minutes=60; min_edge_bps=$edge; rolling_window=75; forecast_weight=0.70; min_reentry_events=40; max_gross_exposure=1.0; adverse_selection_bps=0.0; notes="Market making with stricter portfolio edge gate." }
    }
    foreach ($cool in @(20,40,60,90,120)) {
        $rows += [pscustomobject]@{ variant_name=("mm_cooldown_$cool`_open60"); portfolio_mode="mm-only"; decision_mode="off"; window_minutes=60; min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=$cool; max_gross_exposure=1.0; adverse_selection_bps=0.0; notes="Market making re-entry cooldown sweep." }
    }
    foreach ($win in @(5,10,15,30,45,60)) {
        $rows += [pscustomobject]@{ variant_name=("mm_window_$win"); portfolio_mode="mm-only"; decision_mode="off"; window_minutes=$win; min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40; max_gross_exposure=1.0; adverse_selection_bps=0.0; notes="Training-selected time-window candidate." }
    }
    foreach ($mode in @("hmm","hmm-hawkes","full")) {
        $rows += [pscustomobject]@{ variant_name=("mm_decision_$mode"); portfolio_mode="mm-only"; decision_mode=$mode; window_minutes=60; min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40; max_gross_exposure=1.0; adverse_selection_bps=0.0; notes="Decision-engine variant." }
    }
    foreach ($adv in @(0.05,0.10,0.20)) {
        $rows += [pscustomobject]@{ variant_name=("mm_cost_buffer_{0:0.00}" -f $adv); portfolio_mode="mm-only"; decision_mode="off"; window_minutes=60; min_edge_bps=0.20; rolling_window=75; forecast_weight=0.70; min_reentry_events=40; max_gross_exposure=1.0; adverse_selection_bps=$adv; notes="Execution-cost buffer proxy via adverse-selection stress." }
    }
    return $rows
}

function Get-VerifiedQuoteFiles {
    param([string]$ManifestPath, [int]$MaxDays = 30)
    $rows = Import-Csv -LiteralPath $ManifestPath | Where-Object { $_.status -eq "ok" } | Sort-Object date
    return @($rows | Select-Object -First $MaxDays)
}

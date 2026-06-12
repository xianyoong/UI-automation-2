# dashboard.ps1 — Launch the test-case dashboard.
#
# Default: starts a local web server at http://localhost:8765 with working
# Run / Hold / Resume / Delete buttons, and opens it in your browser.
# Press Ctrl+C in this window to stop the server.
#
# Usage:
#   .\dashboard.ps1                    # serve + open (recommended)
#   .\dashboard.ps1 -Port 9000         # use a different port
#   .\dashboard.ps1 -Static            # just write dashboard.html (no server)
#   .\dashboard.ps1 -Static -NoOpen    # generate file, don't open browser
param(
    [switch]$Static,
    [switch]$NoOpen,
    [int]$Port = 8765
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-PythonRunner {
    if (Get-Command uv -ErrorAction SilentlyContinue) { return @("uv","run","python") }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @("python") }
    if (Get-Command py -ErrorAction SilentlyContinue) { return @("py","-3") }
    return $null
}

$runner = Find-PythonRunner
if (-not $runner) {
    Write-Host "ERROR: neither 'uv', 'python', nor 'py' was found on PATH." -ForegroundColor Red
    Write-Host "Install one of them, then re-run .\dashboard.ps1" -ForegroundColor Yellow
    exit 2
}
Write-Host ("Using runner: " + ($runner -join " ")) -ForegroundColor DarkGray

if ($Static) {
    & $runner[0] $runner[1..($runner.Length-1)] scripts/dashboard.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $html = Join-Path $PSScriptRoot "dashboard.html"
    if ($NoOpen) { Write-Host "Dashboard generated: $html"; exit 0 }
    Write-Host "Opening $html ..."
    try { Start-Process $html } catch {
        foreach ($exe in @("msedge.exe","chrome.exe","firefox.exe")) {
            try { Start-Process $exe -ArgumentList $html -ErrorAction Stop; break } catch {}
        }
    }
    exit 0
}

# Live server mode
$url = "http://localhost:$Port/"
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  ui-auto dashboard:  $url" -ForegroundColor Cyan
Write-Host "  (Keep this window open. Press Ctrl+C to stop the server.)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

if (-not $NoOpen) {
    # Open browser after a short delay so the server has time to bind
    Start-Job -ScriptBlock {
        param($u)
        Start-Sleep -Milliseconds 1500
        try { Start-Process $u } catch {
            foreach ($exe in @("msedge.exe","chrome.exe","firefox.exe")) {
                try { Start-Process $exe -ArgumentList $u -ErrorAction Stop; return } catch {}
            }
        }
    } -ArgumentList $url | Out-Null
    Write-Host "If your browser doesn't open automatically, paste this into it:" -ForegroundColor Yellow
    Write-Host "  $url" -ForegroundColor Yellow
    Write-Host ""
}

& $runner[0] $runner[1..($runner.Length-1)] scripts/dashboard.py --serve --port $Port
exit $LASTEXITCODE

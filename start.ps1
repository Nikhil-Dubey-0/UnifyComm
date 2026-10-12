# UnifyComm: start everything in separate windows.
#   .\start.ps1             tunnel + api + worker + web (real WhatsApp needs the tunnel)
#   .\start.ps1 -NoTunnel   api + worker + web only (simulator and email)
# The tunnel address changes on every start: this script writes it into .env
# (PUBLIC_BASE_URL) and prints the webhook URL to paste into Twilio.
param([switch]$NoTunnel)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$envFile = Join-Path $root ".env"

function Test-Port([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if ((Test-Port 8000) -or (Test-Port 3000)) {
    Write-Host "Port 8000 or 3000 is already in use: UnifyComm (or something else) is running." -ForegroundColor Yellow
    Write-Host "Run .\stop.ps1 first, then .\start.ps1 again."
    exit 1
}

$webhook = $null
if (-not $NoTunnel) {
    $cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if (-not (Test-Path $cloudflared)) {
        $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
        if (-not $cmd) { throw "cloudflared not found: winget install --id Cloudflare.cloudflared --source winget" }
        $cloudflared = $cmd.Source
    }
    $log = Join-Path $env:TEMP "unifycomm-tunnel.log"
    Remove-Item $log -ErrorAction SilentlyContinue
    Write-Host "Starting the tunnel..."
    Start-Process -FilePath $cloudflared -WindowStyle Hidden -RedirectStandardError $log `
        -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://localhost:8000" | Out-Null

    $url = $null
    for ($i = 0; $i -lt 60 -and -not $url; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $log) {
            $match = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
            if ($match) { $url = $match.Matches[0].Value }
        }
    }
    if (-not $url) { throw "The tunnel did not report an address within 60 s. See $log" }

    # Rewrite PUBLIC_BASE_URL as UTF-8 without a BOM (a BOM would corrupt the first key).
    $text = [IO.File]::ReadAllText($envFile)
    if ($text -match "(?m)^PUBLIC_BASE_URL=.*$") {
        $text = [regex]::Replace($text, "(?m)^PUBLIC_BASE_URL=.*$", "PUBLIC_BASE_URL=$url")
    } else {
        $text = $text.TrimEnd() + "`r`nPUBLIC_BASE_URL=$url`r`n"
    }
    [IO.File]::WriteAllText($envFile, $text, (New-Object System.Text.UTF8Encoding($false)))
    $webhook = "$url/api/webhooks/twilio/whatsapp"
}

function Start-Window([string]$title, [string]$dir, [string]$command) {
    $full = "`$host.UI.RawUI.WindowTitle = 'UnifyComm $title'; Set-Location '$dir'; $command"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $full | Out-Null
}

Write-Host "Starting api, worker and web app in their own windows..."
Start-Window "api" (Join-Path $root "backend") "uv run uvicorn app.main:app --port 8000"
Start-Window "worker" (Join-Path $root "backend") "uv run python -m app.worker"
Start-Window "web" (Join-Path $root "frontend") "npm run dev"

Write-Host ""
Write-Host "Web app: http://localhost:3000  (agent@unifycomm.local / demo1234)" -ForegroundColor Green
Write-Host "The worker needs about 40 s to load the AI models."
if ($webhook) {
    Write-Host ""
    Write-Host "Paste this into Twilio > WhatsApp Sandbox settings > 'When a message comes in' (POST):" -ForegroundColor Cyan
    Write-Host "  $webhook" -ForegroundColor Cyan
    Set-Clipboard -Value $webhook
    Write-Host "(already copied to the clipboard)"
}
Write-Host ""
Write-Host "Stop everything with .\stop.ps1"

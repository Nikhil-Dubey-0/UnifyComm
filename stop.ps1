# UnifyComm: stop the tunnel, api, worker and web app (including a leftover `next dev`).
$patterns = @(
    "cloudflared.*trycloudflare|cloudflared.*--url http://localhost:8000",
    "uvicorn(\.exe)?\W.*app\.main:app",
    "-m app\.worker",
    "UnifyComm\\frontend.*next"
)
$stopped = 0
Get-CimInstance Win32_Process | Where-Object {
    $cmd = $_.CommandLine
    $cmd -and ($patterns | Where-Object { $cmd -match $_ })
} | ForEach-Object {
    try {
        taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null
        $stopped++
    } catch {}
}
Start-Sleep -Seconds 1
$busy = @(8000, 3000) | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue }
if ($busy) {
    Write-Host "Still in use: port(s) $($busy -join ', '). Close those windows, or end the process in Task Manager." -ForegroundColor Yellow
} else {
    Write-Host "UnifyComm stopped ($stopped process(es))." -ForegroundColor Green
}

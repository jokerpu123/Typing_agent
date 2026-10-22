$ErrorActionPreference = 'Stop'
$statusFile = 'D:\typing-agent\rime-user\typing-agent-ipc\worker-status.json'
if (Test-Path -LiteralPath $statusFile) {
    $workerStatus = Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json
    $workerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($workerStatus.pid)"
    if ($workerProcess) {
        if ($workerProcess.CommandLine -notmatch 'typing_agent\.rime_service') { throw 'PID does not belong to our model service' }
        Stop-Process -Id $workerStatus.pid
        Wait-Process -Id $workerStatus.pid -Timeout 10 -ErrorAction SilentlyContinue
    }
}
& (Join-Path $PSScriptRoot 'start-rime-model.ps1')

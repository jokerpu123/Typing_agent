$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$runtime = 'D:\typing-agent'
New-Item -ItemType Directory -Force -Path "$runtime\logs", "$runtime\rime-user\typing-agent-ipc" | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$env:HF_HUB_OFFLINE = '1'
$env:HF_DEACTIVATE_ASYNC_LOAD = '1'
Start-Process -FilePath "$project\.venv\Scripts\python.exe" -ArgumentList '-u','-m','typing_agent.rime_service' -WorkingDirectory $project -WindowStyle Hidden -RedirectStandardOutput "$runtime\logs\model.stdout.log" -RedirectStandardError "$runtime\logs\model.stderr.log" -PassThru | Select-Object Id

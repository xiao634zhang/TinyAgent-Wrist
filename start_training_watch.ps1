$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskScript = Join-Path $taskRoot 'training_watch.py'
Start-Process -FilePath $taskPython -ArgumentList @('-X', 'utf8', ('"' + $taskScript + '"'), '--interval', '30') -WorkingDirectory $taskRoot -WindowStyle Hidden
Write-Output 'Training watcher started in background; status: logs\training-watch-status.json'

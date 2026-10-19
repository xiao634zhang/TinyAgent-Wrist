param([string]$Serial, [string]$Scrcpy, [string]$Adb)
$ErrorActionPreference = 'Stop'
if (-not $Adb) { $Adb = $env:ANDROID_ADB }
if (-not $Adb) {
    $taskLocalAdb = Join-Path $PSScriptRoot 'tools\platform-tools\adb.exe'
    if (Test-Path -LiteralPath $taskLocalAdb) { $Adb = $taskLocalAdb }
}
if ($Adb) { $env:ADB = $Adb }
if (-not $Scrcpy) { $Scrcpy = (Get-Command scrcpy -ErrorAction Stop).Source }
$taskArgs = @('--no-audio', '--no-clipboard-autosync', '--window-title=Codex Android')
if ($Serial) { $taskArgs += @('--serial', $Serial) } else { $taskArgs += '--select-usb' }
& $Scrcpy @taskArgs

param(
    [string]$ScriptPath = "C:\apps\pontolentx-auto-deploy\pontolentx-auto-deploy.ps1",
    [string]$RepoPath = "C:\apps\pontolentx-main",
    [string]$TaskName = "Pontolentx Auto Deploy"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Deploy script not found: $ScriptPath"
}

if (-not (Test-Path -LiteralPath $RepoPath)) {
    throw "Repository path not found: $RepoPath"
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -RepoPath `"$RepoPath`""

$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory (Split-Path -Parent $ScriptPath)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Checks Pontolentx origin/main on even minutes and applies fast-forward updates." -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName

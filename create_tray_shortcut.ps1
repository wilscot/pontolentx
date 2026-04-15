param(
    [string]$ShortcutPath = "$env:USERPROFILE\Desktop\Ponto TolentX Launcher.lnk"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcherPath = Join-Path $root "start_pontolentx.cmd"

if (-not (Test-Path $launcherPath)) {
    throw "Launcher principal nao encontrado em $launcherPath."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $launcherPath
$shortcut.Arguments = ""
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = $launcherPath
$shortcut.Save()

Write-Host "Atalho criado em: $ShortcutPath"
Write-Host "Target: $launcherPath"

param(
    [string]$ShortcutPath = "$env:USERPROFILE\Desktop\Ponto TolentX Launcher.lnk"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $root "dist\PontoTolentX-Launcher.exe"

if (Test-Path $exePath) {
    $targetPath = $exePath
    $arguments = ""
}
else {
    $pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
    if (-not $pythonw) {
        throw "pythonw.exe nao encontrado no PATH e o EXE ainda nao foi gerado."
    }
    $targetPath = $pythonw
    $arguments = "`"$root\tray_launcher.py`""
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = $targetPath
$shortcut.Save()

Write-Host "Atalho criado em: $ShortcutPath"

param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if ($Clean) {
    Remove-Item -Recurse -Force .\build -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
    Remove-Item -Force .\PontoTolentX-Launcher.spec -ErrorAction SilentlyContinue
}

python -m PyInstaller `
  --noconfirm `
  --onefile `
  --windowed `
  --name "PontoTolentX-Launcher" `
  --add-data "templates;templates" `
  --add-data "static;static" `
  --hidden-import app `
  --hidden-import db `
  --hidden-import scheduler `
  --hidden-import holidays `
  --hidden-import punch `
  tray_launcher.py

Write-Host ""
Write-Host "Build finalizado. EXE em: $root\dist\PontoTolentX-Launcher.exe"

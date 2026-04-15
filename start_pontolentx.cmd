@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW="
set "PYTHON_EXE="

for /f "delims=" %%I in ('where pythonw 2^>nul') do (
    set "PYTHONW=%%I"
    goto run_python
)

for /f "delims=" %%I in ('where python 2^>nul') do (
    set "PYTHON_EXE=%%I"
    goto derive_pythonw
)

goto run_exe

:derive_pythonw
for %%I in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpI"
if exist "%PYTHON_DIR%pythonw.exe" (
    set "PYTHONW=%PYTHON_DIR%pythonw.exe"
    goto run_python
)

:run_exe
if exist "%~dp0dist\PontoTolentX-Launcher.exe" (
    start "" "%~dp0dist\PontoTolentX-Launcher.exe"
    exit /b 0
)

echo [ERRO] Nao foi encontrado um launcher utilizavel.
echo.
echo Opcoes verificadas:
echo - pythonw.exe no PATH
echo - pythonw.exe ao lado do python.exe
echo - dist\PontoTolentX-Launcher.exe
echo.
echo Para ambiente de desenvolvimento, instale os requisitos e garanta o Python no PATH.
pause
exit /b 1

:run_python
if not exist "%~dp0tray_launcher.py" (
    echo [ERRO] tray_launcher.py nao encontrado em "%~dp0".
    pause
    exit /b 1
)

start "" "%PYTHONW%" "%~dp0tray_launcher.py"
exit /b 0

@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW="
set "PYTHON_EXE="

for /f "delims=" %%I in ('where pythonw 2^>nul') do (
    set "PYTHONW=%%I"
    goto validate_launcher
)

for /f "delims=" %%I in ('where python 2^>nul') do (
    set "PYTHON_EXE=%%I"
    goto derive_pythonw
)

goto derive_python_from_pythonw

:derive_pythonw
for %%I in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpI"
if exist "%PYTHON_DIR%pythonw.exe" (
    set "PYTHONW=%PYTHON_DIR%pythonw.exe"
)
goto derive_python_from_pythonw

:derive_python_from_pythonw
if not defined PYTHON_EXE if defined PYTHONW (
    for %%I in ("%PYTHONW%") do set "PYTHONW_DIR=%%~dpI"
    if exist "%PYTHONW_DIR%python.exe" set "PYTHON_EXE=%PYTHONW_DIR%python.exe"
)
goto validate_launcher

:validate_launcher
if defined PYTHONW goto run_pythonw
if defined PYTHON_EXE goto run_python

:no_python
echo [ERRO] Nao foi encontrado um launcher utilizavel.
echo.
echo Opcoes verificadas:
echo - pythonw.exe no PATH
echo - pythonw.exe ao lado do python.exe
echo - python.exe no PATH
echo.
echo Se esta for a primeira execucao, rode antes:
echo   instalar_pontolentx.cmd
pause
exit /b 1

:launcher_missing
if not exist "%~dp0tray_launcher.py" (
    echo [ERRO] tray_launcher.py nao encontrado em "%~dp0".
    pause
    exit /b 1
)

:run_pythonw
if not exist "%~dp0tray_launcher.py" goto launcher_missing
start "" "%PYTHONW%" "%~dp0tray_launcher.py"
exit /b 0

:run_python
if not exist "%~dp0tray_launcher.py" goto launcher_missing
start "" "%PYTHON_EXE%" "%~dp0tray_launcher.py"
exit /b 0

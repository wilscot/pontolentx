@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="

for /f "delims=" %%I in ('where python 2^>nul') do (
    set "PYTHON_EXE=%%I"
    goto run_install
)

echo [ERRO] Python nao encontrado no PATH.
echo.
echo Instale o Python e marque a opcao para adicionar ao PATH.
pause
exit /b 1

:run_install
if not exist "%~dp0requirements.txt" (
    echo [ERRO] requirements.txt nao encontrado em "%~dp0".
    pause
    exit /b 1
)

echo Instalando dependencias Python...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao instalar as dependencias do projeto.
    pause
    exit /b 1
)

echo.
echo Instalando componentes do Playwright...
"%PYTHON_EXE%" -m playwright install chrome
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao instalar o Chrome/controlador do Playwright.
    pause
    exit /b 1
)

echo.
echo Instalacao concluida.
echo Para iniciar o sistema, execute:
echo   start_pontolentx.cmd
pause
exit /b 0

@echo off
REM ============================================================
REM  CFI Market Finder - inicializacao no Windows
REM  1. Cria o ambiente virtual (venv) se nao existir
REM  2. Instala/atualiza dependencias quando requirements.txt muda
REM  3. Cria o .env a partir do .env.example se nao existir
REM  4. Inicia o servidor e abre o navegador
REM ============================================================
setlocal
cd /d "%~dp0"
title CFI Market Finder

set "VENV_PY=venv\Scripts\python.exe"
set "STAMP=venv\.requirements.installed"

REM --- Localiza o Python (python ou launcher py) ---
set "SYS_PY="
python --version >nul 2>nul && set "SYS_PY=python"
if not defined SYS_PY (
    py -3 --version >nul 2>nul && set "SYS_PY=py -3"
)

REM --- Ambiente virtual ---
if not exist "%VENV_PY%" (
    if not defined SYS_PY (
        echo [ERRO] Python 3.10+ nao encontrado. Instale em https://www.python.org/downloads/
        echo        e marque "Add python.exe to PATH" durante a instalacao.
        goto :fail
    )
    echo Criando ambiente virtual...
    %SYS_PY% -m venv venv || goto :fail
    if exist "%STAMP%" del "%STAMP%"
)

"%VENV_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo [ERRO] O ambiente virtual usa Python anterior ao 3.10. Apague a pasta venv e instale Python 3.10+.
    goto :fail
)

REM --- Dependencias (reinstala so quando requirements.txt muda) ---
fc /b requirements.txt "%STAMP%" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias...
    "%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
    copy /y requirements.txt "%STAMP%" >nul
)

REM --- Configuracao ---
if not exist ".env" (
    copy .env.example .env >nul
    echo [AVISO] Arquivo .env criado a partir do .env.example. Preencha suas chaves de API.
)

REM --- Servidor ---
"%VENV_PY%" -m app %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Falha ao iniciar o CFI Market Finder.
pause
exit /b 1

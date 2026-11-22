@echo off
REM ============================================================
REM  CFI Market Finder - inicializacao no Windows
REM  1. Encontra um Python 3.12+ (python ou launcher py)
REM  2. Cria o ambiente virtual (venv) se nao existir
REM  3. Instala/atualiza dependencias quando requirements.txt muda
REM  4. Cria o .env a partir do .env.example se nao existir
REM  5. Inicia o servidor e abre o navegador
REM
REM  Opcoes:  run.bat --no-browser   (nao abre o navegador)
REM           run.bat --reload       (recarrega ao editar o codigo)
REM           run.bat --diagnostico  (verifica ambiente, chaves e conexoes)
REM ============================================================
setlocal
cd /d "%~dp0"
title CFI Market Finder

set "VENV_PY=venv\Scripts\python.exe"
set "STAMP=venv\.requirements.installed"
set "VERSION_CHECK=import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"

REM --- Ambiente virtual ---
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "%VERSION_CHECK%" >nul 2>nul
    if errorlevel 1 (
        echo [ERRO] A pasta venv foi criada com um Python anterior ao 3.12.
        echo        Apague a pasta "venv" e execute o run.bat novamente.
        goto :fail
    )
    goto :deps
)

REM --- Localiza um Python 3.12+ ---
set "SYS_PY="
for %%C in ("py -3.13" "py -3.12" "py -3" "python") do (
    if not defined SYS_PY (
        %%~C -c "%VERSION_CHECK%" >nul 2>nul && set "SYS_PY=%%~C"
    )
)
if not defined SYS_PY (
    echo [ERRO] Python 3.12 ou mais novo nao encontrado.
    echo        Instale em https://www.python.org/downloads/ e marque
    echo        "Add python.exe to PATH" durante a instalacao.
    goto :fail
)
echo Criando ambiente virtual com: %SYS_PY%
%SYS_PY% -m venv venv
if errorlevel 1 goto :fail
if exist "%STAMP%" del "%STAMP%"

:deps
REM --- Dependencias (reinstala so quando requirements.txt muda) ---
fc /b requirements.txt "%STAMP%" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias ^(pode levar alguns minutos na primeira vez^)...
    "%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRO] Nao foi possivel instalar as dependencias.
        echo        Verifique a conexao com a internet ^(ou o proxy da rede^) e tente de novo.
        goto :fail
    )
    copy /y requirements.txt "%STAMP%" >nul
)

REM --- Configuracao ---
if not exist ".env" (
    copy .env.example .env >nul
    echo [AVISO] Arquivo .env criado a partir do .env.example.
    echo         Preencha COMTRADE_API_KEY e GROQ_API_KEY no arquivo .env ^(veja o README^).
)

REM --- Diagnostico ---
if /i "%~1"=="--diagnostico" (
    "%VENV_PY%" -m app.tools.doctor
    echo.
    pause
    exit /b 0
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

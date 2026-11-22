@echo off
REM Verifica Python, dependencias, chaves do .env, banco e conexao com as APIs.
cd /d "%~dp0"
call run.bat --diagnostico

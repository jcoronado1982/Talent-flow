@echo off
title TalentFlow - Dashboard Server
echo ====================================================
echo  📊 Iniciando Dashboard de TalentFlow (FastAPI)...
echo ====================================================
echo.

REM Activar entorno virtual
call .venv\Scripts\activate.bat

REM Configurar PYTHONPATH y ejecutar servidor FastAPI
set PYTHONPATH=.
python dashboard\main.py

pause

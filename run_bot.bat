@echo off
title TalentFlow - Bot de Busqueda
echo ====================================================
echo  🚀 Iniciando TalentFlow Bot de Busqueda...
echo ====================================================
echo.

REM Limpiar candados anteriores si existen
if exist "user_data\SingletonLock" (
    echo 🧹 Eliminando SingletonLock previo...
    del /f /q "user_data\SingletonLock"
)

REM Activar entorno virtual
call .venv\Scripts\activate.bat

REM Ejecutar bot principal
set PYTHONPATH=.
python -m src.main

pause

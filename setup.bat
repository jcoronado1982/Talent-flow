@echo off
title Instalador de TalentFlow - Windows
echo ====================================================
echo  🚀 Instalando TalentFlow para Windows
echo ====================================================
echo.

REM 1. Crear entorno virtual
echo 📦 1. Creando entorno virtual de Python...
python -m venv .venv
if %errorlevel% neq 0 (
    echo ❌ Error al crear el entorno virtual. Asegurate de tener Python instalado y agregado al PATH.
    pause
    exit /b %errorlevel%
)

REM 2. Activar entorno virtual
echo 🔄 2. Activando entorno virtual...
call .venv\Scripts\activate.bat

REM 3. Instalar dependencias
echo 📥 3. Instalando librerias desde requirements.txt...
pip install --upgrade pip
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ❌ Error instalando librerias.
    pause
    exit /b %errorlevel%
)

REM 4. Instalar navegador Chromium para Playwright
echo 🌐 4. Instalando navegador Chromium para Playwright...
playwright install chromium
if %errorlevel% neq 0 (
    echo ❌ Error instalando Chromium.
    pause
    exit /b %errorlevel%
)

echo.
echo ====================================================
echo  ✅ Instalacion completada exitosamente!
echo ====================================================
echo.
echo Siguientes pasos para la persona en Windows:
echo  1. Edita 'config\profile_config.json' con tus datos personales.
echo  2. Ejecuta 'run_bot.bat' para iniciar la busqueda.
echo  3. Ejecuta 'run_dashboard.bat' para ver el panel de control.
echo.
pause

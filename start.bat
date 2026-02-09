@echo off
REM RAG-OCR Startup Script
REM This script starts both backend and frontend servers

echo ================================================
echo           RAG-OCR Startup Script
echo ================================================
echo.

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Check if we're in the correct directory
if not exist "backend\manage.py" (
    echo ERROR: backend\manage.py not found!
    echo Please run this script from the RAG-OCR root directory
    pause
    exit /b 1
)

REM Start Backend Server in new window
echo [1/3] Starting Backend Server...
start "RAG-OCR Backend" cmd /k "cd /d "%SCRIPT_DIR%backend" && ..\v1\Scripts\activate && echo Backend server starting... && python manage.py runserver"

REM Wait a moment for backend to initialize
timeout /t 3 /nobreak >nul

REM Start Frontend Server in new window
echo [2/3] Starting Frontend Server...
start "RAG-OCR Frontend" cmd /k "cd /d "%SCRIPT_DIR%frontend" && echo Frontend server starting... && npm run dev"

REM Check if Ollama is running
echo [3/3] Checking Ollama status...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Ollama is already running
) else (
    echo [WARNING] Ollama is not running. Starting Ollama...
    start "Ollama" cmd /k "ollama serve"
    timeout /t 2 /nobreak >nul
)

echo.
echo ================================================
echo                Startup Complete!
echo ================================================
echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo Ollama:   http://localhost:11434
echo.
echo Press any key to close this window...
echo (The servers will continue running in separate windows)
pause >nul

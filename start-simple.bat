@echo off
REM Simple startup - opens everything in one window with tabs

echo Starting RAG-OCR...
echo.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:5173
echo.

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Start backend in background
start /B cmd /c "cd /d "%SCRIPT_DIR%backend" && ..\v1\Scripts\activate && python manage.py runserver" 

REM Start frontend in background
start /B cmd /c "cd /d "%SCRIPT_DIR%frontend" && npm run dev"

REM Check Ollama
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if not "%ERRORLEVEL%"=="0" (
    echo Starting Ollama...
    start /B ollama serve
)

echo.
echo Servers are starting in background...
echo Press Ctrl+C to stop all servers
pause

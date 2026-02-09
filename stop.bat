@echo off
REM RAG-OCR Stop Script
REM This script stops all running servers

echo ================================================
echo            RAG-OCR Stop Script
echo ================================================
echo.

echo Stopping Backend Server (Python/Django)...
taskkill /F /FI "WindowTitle eq RAG-OCR Backend*" 2>NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Backend stopped
) else (
    echo [INFO] Backend was not running
)

echo.
echo Stopping Frontend Server (Node/Vite)...
taskkill /F /FI "WindowTitle eq RAG-OCR Frontend*" 2>NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Frontend stopped
) else (
    echo [INFO] Frontend was not running
)

echo.
echo Checking Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [INFO] Ollama is running (not stopped - may be needed by other apps)
    echo If you want to stop Ollama manually, run: taskkill /F /IM ollama.exe
) else (
    echo [INFO] Ollama is not running
)

echo.
echo ================================================
echo              All Servers Stopped
echo ================================================
echo.
pause

@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5500"
set "PYTHON=C:/Users/aadit/AppData/Local/Programs/Python/Python311/python.exe"

echo ================================================
echo  JobMatch AI - Local Launcher
echo ================================================

:: Check for .env file
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Please copy .env.example to .env and add your API keys.
    echo.
    pause
    exit /b 1
)

:: Check for Python
if not exist "%PYTHON%" (
    for /f "delims=" %%P in ('where python 2^>nul') do set "PYTHON=%%P"
)

if not exist "%PYTHON%" (
    echo [ERROR] Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

:: Install dependencies if needed
echo Checking dependencies...
"%PYTHON%" -m pip install -r requirements.txt -q

:: Stop anything already listening on the backend/frontend ports
for %%P in (%BACKEND_PORT% %FRONTEND_PORT%) do (
    for /f "tokens=5" %%I in ('netstat -aon ^| findstr /R /C:":%%P .*LISTENING"') do (
        echo Stopping process %%I on port %%P...
        taskkill /PID %%I /F >nul 2>&1
    )
)

echo.
echo Starting backend on http://127.0.0.1:%BACKEND_PORT%
echo Starting frontend on http://127.0.0.1:%FRONTEND_PORT%
echo On first run, job indexing will begin automatically (~5 min).
echo.
echo The browser will open automatically.
echo Press Ctrl+C in the server windows to stop.
echo ================================================
echo.

start "JobMatch Backend" cmd /c ""%PYTHON%" -m uvicorn backend:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"
timeout /t 3 /nobreak >nul
start "JobMatch Frontend" cmd /c ""%PYTHON%" -m http.server %FRONTEND_PORT% --directory frontend"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:%FRONTEND_PORT%/index.html"

endlocal

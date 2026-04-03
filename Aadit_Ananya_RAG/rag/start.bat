@echo off
echo ================================================
echo  JobMatch AI - Backend Startup
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
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

:: Install dependencies if needed
echo Checking dependencies...
pip install -r requirements.txt -q

echo.
echo Starting backend on http://localhost:8000
echo On first run, job indexing will begin automatically (~5 min).
echo Open frontend\index.html in your browser once the server is ready.
echo.
echo Press Ctrl+C to stop.
echo ================================================
echo.

uvicorn backend:app --host 0.0.0.0 --port 8000 --reload

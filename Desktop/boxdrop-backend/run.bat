@echo off
REM One-click launcher for BoxDrop: sets up a venv if needed, installs
REM dependencies, then starts the FastAPI backend and the Streamlit frontend
REM in separate windows.
REM
REM Prerequisites: Python on PATH, and a MongoDB instance reachable at
REM MONGO_URI (defaults to mongodb://localhost:27017/ - see backend/database/connection.py).

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [BoxDrop] Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [BoxDrop] Failed to create a virtual environment. Is Python installed and on PATH?
        pause
        exit /b 1
    )
)

echo [BoxDrop] Installing/updating dependencies from requirements.txt ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [BoxDrop] Dependency installation failed - see the output above.
    pause
    exit /b 1
)

echo [BoxDrop] Starting FastAPI backend on http://localhost:8000 ...
start "BoxDrop Backend" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

echo [BoxDrop] Waiting a few seconds for the backend to come up ...
timeout /t 5 /nobreak >nul

echo [BoxDrop] Starting Streamlit frontend on http://localhost:8501 ...
start "BoxDrop Frontend" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe -m streamlit run frontend\app.py"

echo.
echo [BoxDrop] Both services are launching in separate windows:
echo   Backend docs : http://localhost:8000/docs
echo   Frontend UI  : http://localhost:8501
echo.
echo Close those windows (or Ctrl+C inside them) to stop each service.
echo.
pause
endlocal

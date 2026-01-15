@echo off
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

echo ========================================
echo Starting CoinSwarm FastAPI
echo ========================================

:: Launch dashboard
echo Opening: http://localhost:8000/dashboard
start http://localhost:8000/dashboard

:: Launch Swagger docs
echo Opening: http://localhost:8000/docs
start http://localhost:8000/docs

:: Start Server
echo Starting uvicorn...
:: Run from parent directory so Fast_Swarm package imports work
cd /d "%PROJECT_ROOT%"
:: Ensure `local_agents` and other Fast_Swarm subpackages are importable as top-level modules
set "PYTHONPATH=%PROJECT_ROOT%\Fast_Swarm;%PYTHONPATH%"
echo PYTHONPATH=%PYTHONPATH%
python -m uvicorn Fast_Swarm.Main:app --reload

pause

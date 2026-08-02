@echo off
REM start-dev.bat - Local development startup script for Windows

setlocal enabledelayedexpansion

REM Load environment variables from .env
if exist .env (
    for /f "delims==" %%A in (.env) do (
        if not "%%A"=="" (
            set "%%A"
        )
    )
) else (
    echo Warning: .env file not found. Using defaults.
)

REM Set development environment
set FLASK_ENV=development
set FLASK_DEBUG=True

REM Create virtual environment if it doesn't exist
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Initialize database if needed
if not exist danu_perfume.db (
    echo Initializing database...
    flask init-db
)

REM Start development server
echo Starting development server on http://localhost:5000
python -m flask run --host=0.0.0.0 --port=5000

pause

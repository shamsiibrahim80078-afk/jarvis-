@echo off
echo ============================================
echo   JARVIS Setup - Installing dependencies
echo ============================================
cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Installing Python packages...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

if not exist .env (
    copy .env.example .env
    echo.
    echo Created .env file - ADD YOUR API KEY before running Jarvis!
)

echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo NEXT STEPS:
echo   1. Edit .env and add GEMINI_API_KEY or ANTHROPIC_API_KEY
echo   2. Run: start.bat          (text mode)
echo   3. Run: start-voice.bat    (voice mode)
echo.
pause

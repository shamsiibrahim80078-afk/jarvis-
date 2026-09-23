@echo off
title Jarvis Web Server
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo.
echo  ============================================
echo    JARVIS Web UI - http://127.0.0.1:8765
echo  ============================================
echo.
python run_server.py
pause

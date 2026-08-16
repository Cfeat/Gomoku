@echo off
chcp 65001 >nul
cd /d "%~dp0wuziqi_web"
echo.
echo   ♟  Wuziqi Web - AI Gomoku
echo   ═══════════════════════════
echo.
python server.py
pause

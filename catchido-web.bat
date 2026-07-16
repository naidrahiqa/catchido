@echo off
title Catchido Web GUI Launcher
echo ===================================================
echo   🎯 Catchido — Smart HD Media Scraper and Organizer
echo ===================================================
echo.
echo Starting backend server...

:: Check if Python virtual environment exists and activate it
if exist .venv\Scripts\activate.bat (
    echo Activating Python virtual environment...
    call .venv\Scripts\activate.bat
)

:: Run catchido web command
catchido web

echo.
echo Server stopped. Press any key to exit...
pause >nul

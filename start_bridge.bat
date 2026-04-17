@echo off
title DIRCON Bridge
cd /d "%~dp0"
echo Starting DIRCON proxy bridge...
echo Connect MyWhoosh to "LloydLabs TRNR" on the trainer list.
echo Open index.html in Chrome — it will connect automatically.
echo.
py -3 dircon_bridge.py -v
echo.
echo Bridge stopped.
pause

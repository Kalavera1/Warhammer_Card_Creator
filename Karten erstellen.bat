@echo off
REM ===================================================================
REM  Warhammer Card Generator - Windows-Starter (Doppelklick)
REM  Startet den Generator in WSL (Ubuntu) und verarbeitet alle Listen
REM  im Ordner lists\. Ergebnisse landen in output\.
REM ===================================================================
title Warhammer Card Generator

echo Erzeuge Karten und Plaene aus allen Listen in lists\ ...
echo.

wsl -d Ubuntu bash -lc "cd '/home/ironhard/projects/Warhammer_Card_Creator' && ./run.sh"

echo.
echo Fertig. Die Ergebnisse liegen im Ordner: output
echo.
pause

@echo off
setlocal
cd /d "%~dp0"
start "" pythonw "%~dp0background_removal_app.py"

@echo off
setlocal
cd /d "%~dp0"
py -3 hallows_eve_macro.py
if errorlevel 1 pause

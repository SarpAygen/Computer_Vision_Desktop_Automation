@echo off
setlocal
cd /d "%~dp0"
echo Building Hallows Eve Macro. This may take several minutes.
echo Detailed progress is being written to build.log.
py -3 build_windows.py %* > build.log 2>&1
if errorlevel 1 (
    echo Build failed. Open build.log in this folder for details.
    echo Make sure Python for Windows is installed with the py launcher.
    pause
    exit /b 1
)
echo Ready: dist\HallowsEveMacro-Windows.zip
echo Extract the ZIP and run HallowsEveMacro.exe. Share the WHOLE ZIP.
pause

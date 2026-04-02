@echo off
REM pedeanjo_go — UK100 ORB Pre-Open Institutional Filter (Windows)
REM Double-click this file or type "pedeanjo_go" in any terminal.

setlocal

REM --- Find the script directory (where this .bat lives) ---
set "SCRIPT_DIR=%~dp0"

REM --- If run from Desktop shortcut, the actual code is in the pedeanjo folder ---
if exist "%SCRIPT_DIR%pedeanjo\uk100_orb_filter.py" (
    set "PROJECT_DIR=%SCRIPT_DIR%pedeanjo"
) else if exist "%SCRIPT_DIR%uk100_orb_filter.py" (
    set "PROJECT_DIR=%SCRIPT_DIR%"
) else (
    echo ERRO: uk100_orb_filter.py nao encontrado.
    echo Certifica-te que a pasta pedeanjo esta no Desktop.
    pause
    exit /b 1
)

REM --- Check venv exists ---
if not exist "%PROJECT_DIR%\venv\Scripts\python.exe" (
    echo ERRO: Virtual environment nao encontrado.
    echo Corre o install.bat primeiro.
    pause
    exit /b 1
)

REM --- Run the tool, passing any arguments ---
"%PROJECT_DIR%\venv\Scripts\python.exe" "%PROJECT_DIR%\uk100_orb_filter.py" %*

REM --- Keep window open if double-clicked ---
if "%1"=="" pause

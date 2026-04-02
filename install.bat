@echo off
REM ============================================================
REM  PEDEANJO — UK100 ORB Pre-Open Filter — Windows Installer
REM  Just double-click this file or paste the install command
REM  in PowerShell and everything happens automatically.
REM ============================================================

echo.
echo  ========================================
echo   PEDEANJO — A instalar...
echo  ========================================
echo.

REM --- Go to Desktop ---
cd /d "%USERPROFILE%\Desktop"

REM --- Clone repo (creates pedeanjo folder automatically) ---
echo  [1/4] A clonar o repositorio...
git clone https://github.com/hallosoares/pedeanjo.git
if errorlevel 1 (
    echo.
    echo  ERRO: git nao encontrado. Instala o Git primeiro:
    echo  https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)

cd pedeanjo

REM --- Create virtual environment ---
echo  [2/4] A criar ambiente Python...
python -m venv venv
if errorlevel 1 (
    python3 -m venv venv
)
if errorlevel 1 (
    echo.
    echo  ERRO: Python nao encontrado. Instala Python 3.10+ primeiro:
    echo  https://www.python.org/downloads/
    echo  IMPORTANTE: marca "Add Python to PATH" durante a instalacao!
    echo.
    pause
    exit /b 1
)

REM --- Install dependencies ---
echo  [3/4] A instalar dependencias...
venv\Scripts\pip install -r requirements.txt

REM --- Create desktop shortcut (pedeanjo_go.bat) ---
echo  [4/4] A criar atalho no Desktop...
copy pedeanjo_go.bat "%USERPROFILE%\Desktop\pedeanjo_go.bat" >nul 2>&1

echo.
echo  ========================================
echo   INSTALACAO COMPLETA!
echo  ========================================
echo.
echo   Para usar:
echo     1. Abre o Command Prompt ou PowerShell
echo     2. Escreve: pedeanjo_go
echo.
echo   Ou faz duplo-clique no ficheiro
echo   "pedeanjo_go.bat" no Desktop.
echo.
echo  ========================================
echo.

REM --- Run it once to test ---
echo  A correr a primeira analise...
echo.
venv\Scripts\python uk100_orb_filter.py

pause

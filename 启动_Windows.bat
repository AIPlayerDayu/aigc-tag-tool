@echo off
rem =====================================================================
rem  AIGC label detector / remover  --  Windows launcher
rem  Double-click this file to start the tool. It opens in your browser.
rem =====================================================================
setlocal
cd /d "%~dp0"

rem --- locate Python (prefer windowless pythonw) ---
set "PYW="
where pythonw.exe >nul 2>&1 && set "PYW=pythonw"
if not defined PYW ( where pyw.exe >nul 2>&1 && set "PYW=pyw" )
if not defined PYW ( where python.exe >nul 2>&1 && set "PYW=python" )

if not defined PYW (
  echo.
  echo  [X] Python was not found.
  echo.
  echo  Please install Python first:
  echo    1. Open  https://www.python.org/downloads/
  echo    2. Download and run the installer
  echo    3. IMPORTANT: tick "Add python.exe to PATH" on the first screen
  echo    4. After installing, double-click this file again.
  echo.
  pause
  exit /b 1
)

rem --- start the local server (detached) and open the page ---
start "" %PYW% "%~dp0src\server.py"
rem small delay so the server can bind the port
ping -n 2 127.0.0.1 >nul
start "" "http://127.0.0.1:8765/"
exit /b 0

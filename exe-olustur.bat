@echo off
rem Cift tiklayarak exe uretmek icin: PowerShell betigini politika engeline
rem takilmadan calistirir, bitince pencere acik kalir.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0exe-olustur.ps1" %*
pause

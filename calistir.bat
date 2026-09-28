@echo off
rem EX30 Yolculuk Goruntuleyici - cift tiklayarak calistir.
rem Konsol penceresi acilmasin diye pyw/pythonw tercih ediliyor; yoksa py ile
rem calisir ve hata konsolda gorunur.
setlocal
cd /d "%~dp0"

where pyw >nul 2>&1
if %errorlevel%==0 (
    start "" pyw -3 -m ex30trips %*
    goto :eof
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw -m ex30trips %*
    goto :eof
)

py -3 -m ex30trips %*
if errorlevel 1 pause

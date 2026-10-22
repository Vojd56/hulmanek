@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate.bat
rem Volitelny PIN pro pristup z telefonu:  set HULMANY_PIN=1234
python -m app.main %*
pause

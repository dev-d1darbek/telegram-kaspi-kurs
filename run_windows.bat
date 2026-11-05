@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
if not exist .env (
  copy .env.example .env
  echo Edit .env and add your Telegram bot token and admin ID, then run this file again.
  notepad .env
  pause
  exit /b 1
)
.venv\Scripts\python.exe main.py
pause

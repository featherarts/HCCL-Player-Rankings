@echo off
title HCCL Telegram Bot
cd /d "%~dp0"
echo ================================================
echo        Starting HCCL Telegram Bot
echo ================================================
echo.
if not exist .env (
  echo Missing .env file.
  echo Copy .env.example to .env and add your Telegram/Supabase keys.
  pause
  exit /b 1
)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python telegram_bot.py
pause

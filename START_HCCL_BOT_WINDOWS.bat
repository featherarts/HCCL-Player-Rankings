@echo off
cd /d "%~dp0"
echo ================================================
echo       Starting HCCL Rankings Dashboard v3
echo ================================================
echo.
echo Installing required packages. This may take a minute the first time.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Opening HCCL Rankings Dashboard...
python -m streamlit run streamlit_app.py
pause

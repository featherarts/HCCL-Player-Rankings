@echo off
cd /d "%~dp0"
echo Starting HCCL Dashboard v3 using Python Launcher...
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m streamlit run streamlit_app.py
pause

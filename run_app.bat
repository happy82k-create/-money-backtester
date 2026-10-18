@echo off
cd /d "%~dp0"
rem 내 컴퓨터에서는 "최신 데이터 갱신" 버튼을 켭니다 (공개 사이트에서는 꺼짐)
set ENABLE_REFRESH=1
.venv\Scripts\python -m streamlit run app.py
pause

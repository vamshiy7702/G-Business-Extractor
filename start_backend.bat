@echo off
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
if not exist leadx\data\locations.db python scripts\build_locations.py
echo.
echo  Edit backend\.env and set CONTACT_EMAIL to your real address (OpenStreetMap servers require it).
echo  Backend: http://localhost:8000   Docs: http://localhost:8000/docs
echo.
python -m uvicorn leadx.api:app --reload --port 8000

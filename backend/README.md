# Backend (FastAPI)

See the project `README.md`. Quick commands:

```bash
pip install -r requirements.txt
python -m uvicorn leadx.api:app --reload --port 8000      # API docs: http://localhost:8000/docs
python -m pytest -q                                       # 40+ tests (no network needed)
python scripts/build_locations.py                         # rebuild the Country/State/City/ZIP database
```

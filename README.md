# Lead Extractor (G-Business style)

Find business leads by **category + location** and export them to CSV/XLSX. Next.js frontend + FastAPI backend.
Data sources: **OpenStreetMap (free, default)** or **Google Places** (optional, needs your API key).

> Read `CHANGES.md` for what was fixed in this version and what is verified vs not.

## Quick start (Windows)
See `RUN_WINDOWS.md`. In short: run `start_backend.bat`, set `CONTACT_EMAIL` in `backend\.env`, run `start_frontend.bat`, open http://localhost:3000.

## Quick start (any OS)
```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then set CONTACT_EMAIL=your real address
python -m uvicorn leadx.api:app --reload --port 8000
# frontend (second terminal)
cd frontend && cp .env.example .env.local && npm install && npm run dev      # http://localhost:3000
```
**First thing to do in the app:** Settings → Connection → **Test connections**. Red lines tell you exactly why data would not be extracted (blocked OpenStreetMap servers, missing contact e-mail, …).

## Using it
1. **Categories**: *Add Category* (autocomplete lists the ~275 names/synonyms mapped to OpenStreetMap tags; other words are searched by business name).
2. **Locations**: *Add Location* → Country → State → City → ZIP. Each list only contains children of the level above; leave a level on "All …" to search wider. Tick several states to add them in one go.
3. **Get data**. Tasks appear in *Task to do* with Status and Found counts; click a task to see its results. *Stop* pauses; *Get data* on a paused/failed task resumes it.
4. Filter results, then export (CSV/XLSX). Settings control columns, e-mail extraction, results per ZIP/tile, max results per task, threads.

## Configuration (`backend/.env`)
| Variable | Meaning |
|---|---|
| `CONTACT_EMAIL` | **Set this.** Sent in the User-Agent to OpenStreetMap servers. Placeholder values are ignored. |
| `GOOGLE_PLACES_API_KEY` | Optional. Enables the Google source. Stays on the server. |
| `ALLOWED_ORIGINS` | CORS origins (default `localhost:3000` and `127.0.0.1:3000`). |
| `LEADX_MAX_TILES`, `LEADX_MAX_CONCURRENT` | Safety cap on search tiles per task; tasks run one at a time by default. |
| `EMAIL_ENRICHMENT_ENABLED`, `EMAIL_*` | E-mail lookup on business websites (public pages, robots.txt respected, SSRF-protected). |
| `LEADX_LOCATIONS_DB` | Path to the location database (default `backend/leadx/data/locations.db`). |

Settings are read once at startup; restart the backend after editing `.env`.

## Location data
`backend/leadx/data/locations.db`: 250 countries, 5,308 states, 153,312 cities, 340,342 city→ZIP links (121 countries have postal data;
see `CHANGES.md` for per-country coverage and the exact matching rule). Sources/licences: `DATA_LICENSES.md`.
Rebuild: `python backend/scripts/build_locations.py`.

## Tests
```bash
cd backend && pip install -r requirements.txt pytest && python -m pytest -q          # backend: no network needed
cd frontend && npm test                                                              # needs the backend running on :8000
cd frontend && npx tsc --noEmit && npm run build
```

## Legal / ethical note
Respect each data source's terms: Google Places results have storage/caching limits; OpenStreetMap servers expect modest, identifiable use;
e-mail addresses collected from websites are personal data in many jurisdictions (GDPR, CAN-SPAM, India's DPDP Act). Use leads lawfully.

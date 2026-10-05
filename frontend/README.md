# Lead Extractor Frontend

Next.js 14 App Router + TypeScript + Tailwind + TanStack Query/Table.

## Run locally

```bash
cp .env.example .env.local
# set NEXT_PUBLIC_API_URL if the backend is not on localhost:8000
npm install
npm run dev
```

Open http://localhost:3000.

## Pages

- `/` — dashboard and **Tasks to do** list
- `/new` — create a search task, select OSM or Google, configure limits, and see Google usage estimates
- `/jobs/[id]` — live progress, filters, pause/resume, email enrichment, CSV/XLSX export
- `/settings` — source/configuration status
- `/terms` and `/privacy` — starter policy pages for production customization

## Checks

```bash
npm run typecheck
npm run build
```


## Desktop-style G-Business Extractor UI

The root route (`/`) now uses a desktop-style extractor workspace modeled on the documented/reference interface: toolbar, Categories/keywords panel, Locations panel, Task to do queue, command bar, and wide results grid. Add/Edit dialogs and Settings are implemented in the browser, while extraction continues to use the existing FastAPI endpoints.

The `.tsk` Save/Load controls use a JSON-compatible task format produced by this frontend.


## Location controls

The G-Business-style Add Location dialog supports **All countries**, **All states**, **All cities**, and **All zip codes**. Selecting a concrete country resets child levels to All; selecting a concrete state resets city and ZIP to All; selecting a concrete city resets ZIP to All.

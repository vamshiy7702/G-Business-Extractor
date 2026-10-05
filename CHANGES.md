# What was wrong and what changed

This is a review of the supplied project (`lead-extractor-gbusiness-reference-full-final.zip`) against your two problems.
Everything below was found by reading the code and confirmed with tests; items I could **not** verify are listed at the end.

## Problem 1: "task is added but no data is extracted"

There was no single cause; several independent defects could each produce exactly that symptom, and the UI hid all of them
(the task table had no Status or error column, and error messages disappeared after 6 seconds).

| # | Defect | Fix |
|---|---|---|
| 1 | **`backend/.env` was never read.** Nothing in the backend loads it (`python-dotenv` is not even a dependency) and `start_backend.bat` only copies `.env.example`. Contact e-mail, User-Agent, Google key, limits were all silently ignored. | `config.py` now loads `.env` (real environment variables still win). Placeholder e-mails like `example.com` are ignored. |
| 2 | **Overpass failures looked like "0 results".** Overpass reports query timeouts / out-of-memory inside a normal HTTP 200 reply (a `remark` field) with an empty list (documented Overpass behaviour; I could not reproduce it live from here). The adapter returned that as "no businesses", so whole tiles were lost silently. | The remark is detected. The tile is split into 4 quadrants (up to 3 levels) and re-queried; if it still fails the task is marked **failed with the reason**. |
| 3 | **A job could stay `queued` forever.** The data-source adapter was created outside any error handling; if that raised (e.g. Google selected without a key) the background task died silently. | Adapter creation happens inside the guarded runner; the task ends `failed` with a readable message. |
| 4 | **Only 16 categories were mapped to OpenStreetMap tags.** Anything else (e.g. `plumber`, `dental clinic`, `chartered accountant`) was searched as "business *name* contains the word", which finds very little. | `categories.py`: 124 categories + 151 synonyms mapped to real OSM tags; unlisted words fall back to name + tag-value search. The Add Category box autocompletes the mapped names. |
| 5 | **Fragile geocoding.** The area was found by gluing names into one free-text string, e.g. `Canneto, Lazio / RI, Italy` (the seed data used the non-existent state `Lazio / RI`; multi-state selection produced `A / B / C`). Any Nominatim failure killed the task with no fallback. | Structured Nominatim queries, then **offline fallbacks from the bundled dataset** (ZIP centroid, city centre, state/country extent). Seed data removed. |
| 6 | **Default source was Google** with no key configured. | Default is OpenStreetMap; Google is flagged "(needs API key)" and blocked with a clear message when unconfigured. |
| 7 | **"Get data" twice created duplicate tasks** for every category×location. | Existing identical tasks are reused (failed/paused ones are resumed). |
| 8 | **Huge areas silently hung the queue.** One country-wide task (hundreds of very large Overpass tiles, one task at a time) blocked every other task behind it. | Timeout splitting (above), a tile cap, and visible status/progress per task; Stop works between tiles and between e-mail batches. |
| 9 | **E-mail enrichment could not be stopped** (Delete/Stop waited for the whole phase) and **was an SSRF hole**: it fetched any URL found in map data and followed redirects, including `localhost` and cloud-metadata addresses. | Enrichment runs in small checkpointed batches. Only public `http(s)` hosts on ports 80/443 are fetched, every redirect hop is re-checked. |
| 10 | Auto Restart retried a failed task every 0.8 s forever. | At most 3 retries with growing delay. |
| 11 | CORS only allowed `localhost:3000`; opening the app as `127.0.0.1:3000` gave "Cannot reach API". | Both are allowed by default. |
| 12 | TypeScript errors in `loadTasks` / location helpers. | Fixed; `tsc` and `next build` are clean. |

New: **Task table shows Status and Found**, error/zero-result banners, **Settings → Connection → Test connections**
(checks Nominatim, Overpass, contact e-mail, location database from *your* machine), and a "Max results per task" setting.

## Problem 2: Country → State → City → ZIP

The old dialog had 15 hard-coded countries, partial hard-coded state lists, a free-text city box (with 11 Indian cities that
did not depend on the state) and a free-text ZIP box. It is replaced by a cascading, searchable picker backed by a real database:

* **250 countries** → each country's own **5,308 states/regions** → each state's own **153,312 cities** → that city's **ZIP codes**.
* Choosing a level resets the levels below; each list is filtered by the one above (verified by tests: no US states under India,
  no Surat under Karnataka, no Mumbai PIN under Bengaluru).
* "All states / All cities / All zip codes" are available at every level. You can also tick several states at once.
* A selected ZIP is searched using its own centroid (no network needed). "All zip codes" searches the whole city.

### How ZIP codes are tied to a city (and the limits)
There is no free worldwide dataset that gives exact city polygons, so a ZIP is attached to a city only when the postal record's
settlement name is **exactly equal** to the city name **and** lies within 50 km (80 km for India) of it. I tested looser rules and
rejected them because they leaked other cities' ZIPs (Chicago picked up East/North Chicago; Los Angeles picked up 496 county ZIPs;
Germany's company-specific ZIPs leaked into Munich/Berlin). Consequences you should know:

* 121 of 250 countries have postal data; the others show only "All zip codes".
* Of cities in those countries, **97,511 of 139,456 (70%)** have a ZIP list. Coverage varies: FR 95%, BR 95%, IT 92%, AU 92%, DE 91%, ES 90%, GB 88%, MX 71%, US 70%, JP 65%, IN 64%, **CA 26%** (GeoNames lists Canadian codes only at 3-character level).
* A city without a list gets a text box where you can type a ZIP, or you can search the whole city. Nothing is invented.
* Some metros are listed under a different name than you may expect: e.g. in India `Delhi` has no list but `New Delhi` has 7.
* ZIP lists are only as accurate as the source data; they reflect GeoNames' records, not postal authorities.

## What I could not verify here
* **Live OpenStreetMap services** (Overpass, Nominatim) and **Google Places**: my sandbox cannot reach them. Their behaviour is simulated in the tests
  (including Overpass's timeout reply), and `Test connections` lets *you* confirm the real thing in one click.
* **Visual layout in a real browser** (no browser can be installed here). The dialog and the full add-category → add-location → Get data flow *are* tested with Testing Library against the real backend and real data, but I have not seen the pixels.
* **Docker** files were left as they were; I could not run Docker here.
* **Google pricing/caps** (`.env.example` mentions India-specific free caps). I did not change these, but note your field mask requests phone/website/rating, which Google bills under a higher SKU than "Pro"; check the caps on Google's pricing page before relying on the built-in guard.
* OpenStreetMap simply has fewer listings than Google for many niche categories; empty results there are expected, not a bug.

---

# Second review (final check of this zip)

Everything below was found by reading the code and, where marked, **reproduced by running it**. Fixed in this version:

| # | File | Defect | Fix |
|---|---|---|---|
| 1 | `backend/leadx/geo.py` | In the structured Nominatim query the country **name was left out whenever a country code was known**. For "All states / All cities" the request then had no search term at all (only `countrycodes`) and Nominatim could not answer, so country-level tasks always fell back to a rough dataset extent. | The country name is always sent when known; a structured query with no search term is never sent. A blank country (CLI `--country` omitted) still works. |
| 2 | `backend/leadx/email_enricher.py` | **Fake e-mails (reproduced):** the obfuscation pattern accepted a bare " at ", so "Visit us at acme.com" produced `us@acme.com`. | Only bracketed forms (`[at]`, `(at)`, `[dot]`, `(dot)`) are decoded. IPv4-mapped IPv6 addresses are normalised in the SSRF check. |
| 3 | `backend/leadx/adapters/osm_overpass.py` | The per-tile limit (`out ... N`) also counted **unnamed** OSM objects, which are discarded afterwards, so a tile could return fewer usable businesses than asked. | Every query requires `["name"]`. |
| 4 | `backend/leadx/adapters/google_places.py` | A Google failure showed only "403 Forbidden", hiding Google's actual reason (key invalid, *Places API (New)* not enabled, billing). | Google's own error message is shown in the task's error banner (the key is never included). |
| 5 | `backend/leadx/area.py` | A saved `city_id` was trusted even if it belonged to another country (e.g. an old `.tsk` file). | The id is ignored unless it belongs to the selected country; the name lookup is used instead. |
| 6 | `backend/leadx/api.py`, `db.py` | The live stream only emitted an update when tiles/places changed, so e-mails found during the e-mail phase did not appear until the task ended. | E-mail progress is part of the stream signature. |
| 7 | `frontend/app/page.tsx` | **Auto-export downloaded a file every time the app was opened in a new tab** (for the latest finished task, even with 0 results, using whatever filter was active). | It now exports only a task that is seen *finishing* during the session, only if it has results, and exports all rows. |
| 8 | `frontend/app/page.tsx` | Editing a location that had several states silently kept only the first. | All edited rows are kept. |
| 9 | `frontend/app/page.tsx` | If one task could not be created (e.g. a location the geocoder cannot resolve) **all remaining tasks were skipped** and the reason vanished after 12 s. | The remaining tasks are still created and every failure stays on screen until dismissed. |

Checked and found **correct** (so left unchanged): the bundled `locations.db` (250 / 5,308 / 153,312 rows as documented; no orphans, no cross-country links, no bad coordinates, no state with more than 5,000 cities, no ZIP farther than 100 km from its city); the cascading picker logic; the e-mail `robots.txt` handling (checked on Python 3.12); duplicate-task handling; Stop/Delete during e-mail lookup.

## Known limits (not code errors)
* **India ZIP lists can include a few nearby towns** (e.g. Pune lists Lonavala/Khandala, ~58 km away). GeoNames' Indian coordinates are approximate, so tightening the radius would also remove legitimate codes. Treat ZIP lists as helpful, not authoritative.
* **Google billing guard:** the field mask requests phone, website and rating, which Google bills under a higher SKU than "Pro", but the built-in guard counts everything as "Pro" with a 35,000 free cap. I could not verify the correct cap/SKU from here; check Google's pricing page before relying on the guard, and also set a daily quota in Google Cloud Console.
* Live OpenStreetMap / Google services, a real browser, `next build`, and Docker could not be run in my environment. Use Settings → Connection → Test connections to confirm your network.
* The window title and buttons imitate the commercial "G-Business Extractor" UI that you asked to follow; "Buy Full Version"/"Get updates" open that vendor's website. Rename these if you distribute the app.

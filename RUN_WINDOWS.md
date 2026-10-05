# Run on Windows

1. Install **Python 3.11+** and **Node.js 20+**.
2. Double-click `start_backend.bat`. The first run creates `backend\.env`.
   **Open `backend\.env` and put your real e-mail in `CONTACT_EMAIL=`**, save, and let the backend restart
   (it reloads automatically; restart the window if it doesn't). OpenStreetMap's servers ask for a contact address.
3. Double-click `start_frontend.bat`, then open **http://localhost:3000**.
4. In the app: **Settings → Connection → Test connections**. All lines should be green. If Nominatim/Overpass
   is red, your network, VPN or firewall is blocking OpenStreetMap, which is the usual cause of tasks that finish with no data.
5. Add a category (e.g. `dentist`) and a location (Country → State → City → ZIP), then press **Get data**.

Google Maps is optional: put `GOOGLE_PLACES_API_KEY=` in `backend\.env` and restart. Without it, use the default
**OpenStreetMap (free)** source.

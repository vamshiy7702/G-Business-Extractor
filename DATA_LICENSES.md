# Data sources and licences

The Country → State → City → ZIP picker uses `backend/leadx/data/locations.db`, a database **derived from two open datasets**:

| Data | Source | Licence |
|---|---|---|
| Countries, states/regions, cities (250 / 5,308 / 153,312) | [dr5hn/countries-states-cities-database](https://github.com/dr5hn/countries-states-cities-database) | Open Database License (ODbL) 1.0, attribution required |
| Postal codes (GeoNames) | [GeoNames postal codes](https://download.geonames.org/export/zip/), via the conversion in [zauberware/postal-codes-json-xml-csv](https://github.com/zauberware/postal-codes-json-xml-csv) | Creative Commons Attribution 4.0 |

`locations.db` is a derivative database of these sources and is therefore offered under the **ODbL 1.0** as well; keep this attribution if you redistribute it.
Business data fetched from OpenStreetMap is © OpenStreetMap contributors (ODbL). Google Places data is subject to Google's terms (limits on storing/caching results).

Rebuild or refresh the database at any time: `python backend/scripts/build_locations.py` (downloads ~120 MB).

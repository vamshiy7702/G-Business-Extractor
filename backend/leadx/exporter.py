from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import quote

from .models import PlaceDTO

VIRTUAL_COLUMNS = ["map_link", "details_link"]


def _map_link(row: dict) -> str:
    lat, lng = row.get("lat"), row.get("lng")
    if lat is None or lng is None:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={quote(f'{lat},{lng}') }"


def _details_link(row: dict) -> str:
    source = row.get("source", "")
    source_id = row.get("source_place_id", "")
    lat, lng = row.get("lat"), row.get("lng")
    if source == "google" and source_id:
        return f"https://www.google.com/maps/search/?api=1&query=Google+Maps+place&query_place_id={quote(str(source_id))}"
    if lat is not None and lng is not None:
        return f"https://www.openstreetmap.org/?mlat={quote(str(lat))}&mlon={quote(str(lng))}#map=18/{quote(str(lat))}/{quote(str(lng))}"
    return ""


def _selected_columns(columns: list[str] | None) -> list[str]:
    allowed = [*PlaceDTO.columns(), *VIRTUAL_COLUMNS]
    if not columns:
        # Preserve the original API/export contract when the UI does not pass a column list.
        return PlaceDTO.columns()
    chosen = [c for c in columns if c in allowed]
    return chosen or PlaceDTO.columns()


def _row_value(row: dict, column: str):
    if column == "map_link":
        return _map_link(row)
    if column == "details_link":
        return _details_link(row)
    return row.get(column)


def to_csv(places: list[PlaceDTO], path: str | Path) -> Path:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=PlaceDTO.columns())
        w.writeheader()
        for p in places:
            w.writerow(p.as_row())
    return path


def rows_to_csv_bytes(rows: list[dict], columns: list[str] | None = None, separator: str = ",") -> bytes:
    import io
    buf = io.StringIO(newline="")
    cols = _selected_columns(columns)
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", delimiter=separator)
    w.writeheader()
    for row in rows:
        w.writerow({c: _row_value(row, c) for c in cols})
    return buf.getvalue().encode("utf-8-sig")


def rows_to_xlsx_bytes(rows: list[dict], columns: list[str] | None = None) -> bytes:
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    cols = _selected_columns(columns)
    ws.append(cols)
    for row in rows:
        ws.append([_row_value(row, c) for c in cols])
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

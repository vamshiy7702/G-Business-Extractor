import asyncio
import csv

from leadx.adapters.osm_overpass import build_query, parse_element
from leadx.exporter import to_csv
from leadx.geo import Tile, adaptive_tile_deg, build_geocode_query, count_tiles, make_tiles
from leadx.models import PlaceDTO, dedup

NODE = {"type": "node", "id": 1, "lat": 12.97, "lon": 77.59, "tags": {
    "name": "Smile Dental", "amenity": "dentist", "phone": "+91 80 1111 2222",
    "website": "https://smile.example", "addr:housenumber": "12", "addr:street": "MG Road",
    "addr:city": "Bengaluru", "addr:postcode": "560001"}}
WAY = {"type": "way", "id": 2, "center": {"lat": 12.97, "lon": 77.59},
       "tags": {"name": "Smile Dental", "amenity": "dentist", "phone": "+91 80 1111 2222"}}


def test_parse_element():
    p = parse_element(NODE)
    assert p.name == "Smile Dental" and p.category == "dentist"
    assert p.source_place_id == "node/1" and p.postal_code == "560001"
    assert p.address.startswith("12 MG Road") and p.lat == 12.97


def test_parse_skips_unnamed_and_uses_center():
    assert parse_element({"type": "node", "id": 9, "tags": {"amenity": "dentist"}}) is None
    assert parse_element(WAY).lat == 12.97


def test_dedup_same_business_node_and_way():
    places = [parse_element(NODE), parse_element(WAY), parse_element(NODE)]
    assert len(dedup(places)) == 1


def test_adaptive_tile_size_keeps_broad_areas_within_cap():
    bbox = (8.0, 68.0, 38.0, 98.0)
    effective = adaptive_tile_deg(bbox, 0.05, 400)
    assert effective > 0.05
    assert count_tiles(*bbox, effective) <= 400


def test_all_location_geocode_queries():
    assert build_geocode_query("All cities", "Telangana", "India", "All zip codes") == "Telangana, India"
    assert build_geocode_query("All cities", "All states", "India", "All zip codes") == "India"
    assert build_geocode_query("Bangalore", "Karnataka", "India", "All zip codes") == "Bangalore, Karnataka, India"
    assert build_geocode_query("Bangalore", "Karnataka", "India", "560001") == "Bangalore, Karnataka, 560001, India"
    try:
        build_geocode_query("All cities", "All states", "All countries", "All zip codes")
    except ValueError as exc:
        assert "All countries" in str(exc)
    else:
        raise AssertionError("Expected unbounded global location to be rejected")


def test_tiles_cover_bbox():
    tiles = make_tiles(12.8, 77.4, 13.1, 77.8, 0.1)
    assert len(tiles) == 3 * 4
    assert min(t.south for t in tiles) == 12.8 and max(t.east for t in tiles) == 77.8


def test_build_query():
    t = Tile(12.9, 77.5, 13.0, 77.6)
    q = build_query("Dentists", t, 50)
    assert '"amenity"="dentist"' in q and "12.900000,77.500000,13.000000,77.600000" in q
    assert '"name"~"yoga studio",i' in build_query("yoga studio", t, 50)
    assert '"' not in build_query('a"b', t, 5).split('"name"~"')[1].split('",i')[0]


def test_csv_export(tmp_path):
    out = to_csv([parse_element(NODE)], tmp_path / "x.csv")
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert rows[0]["name"] == "Smile Dental" and set(rows[0]) == set(PlaceDTO.columns())

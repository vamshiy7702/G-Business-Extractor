"""Map business categories/keywords to OpenStreetMap tag filters.

The previous version knew only 16 categories; anything else fell back to "business NAME
contains the word", so e.g. "plumber" or "dental clinic" returned almost nothing.
Unlisted keywords still work through a broad fallback (name + tag-value search), but
OpenStreetMap category coverage is inherently smaller than Google Maps': for niche
categories the Google source gives more complete results.
"""
from __future__ import annotations

import re
from typing import Iterable


def _eq(key: str, value: str) -> str:
    return f'"{key}"="{value}"'


def _rx(key: str, value: str) -> str:
    return f'"{key}"~"{value}",i'


def _tags(*pairs: tuple[str, str]) -> list[str]:
    return [_eq(k, v) for k, v in pairs]


# canonical name -> list of tag filters (OR-ed together)
CATEGORIES: dict[str, list[str]] = {
    # food & drink
    "restaurant": _tags(("amenity", "restaurant")),
    "cafe": _tags(("amenity", "cafe")),
    "fast food": _tags(("amenity", "fast_food")),
    "bar": _tags(("amenity", "bar")),
    "pub": _tags(("amenity", "pub")),
    "night club": _tags(("amenity", "nightclub")),
    "ice cream": _tags(("amenity", "ice_cream"), ("shop", "ice_cream")),
    "bakery": _tags(("shop", "bakery")),
    "butcher": _tags(("shop", "butcher")),
    "pizza": [_rx("cuisine", "pizza"), _rx("name", "pizza|pizzeria")],
    "chinese restaurant": [_rx("cuisine", "chinese")],
    "indian restaurant": [_rx("cuisine", "indian")],
    "italian restaurant": [_rx("cuisine", "italian")],
    "sweet shop": _tags(("shop", "confectionery")),
    "grocery": _tags(("shop", "convenience"), ("shop", "supermarket"), ("shop", "greengrocer")),
    "supermarket": _tags(("shop", "supermarket")),
    "convenience store": _tags(("shop", "convenience")),
    "liquor store": _tags(("shop", "alcohol")),
    # health
    "dentist": _tags(("amenity", "dentist"), ("healthcare", "dentist")),
    "doctor": _tags(("amenity", "doctors"), ("healthcare", "doctor")),
    "clinic": _tags(("amenity", "clinic"), ("healthcare", "clinic")),
    "hospital": _tags(("amenity", "hospital"), ("healthcare", "hospital")),
    "pharmacy": _tags(("amenity", "pharmacy"), ("healthcare", "pharmacy")),
    "veterinary": _tags(("amenity", "veterinary")),
    "physiotherapist": _tags(("healthcare", "physiotherapist")),
    "optician": _tags(("shop", "optician"), ("healthcare", "optometrist")),
    "diagnostic lab": _tags(("healthcare", "laboratory")),
    "psychologist": _tags(("healthcare", "psychotherapist")),
    "massage": _tags(("shop", "massage")),
    # beauty & fitness
    "hair salon": _tags(("shop", "hairdresser")),
    "beauty salon": _tags(("shop", "beauty")),
    "tattoo": _tags(("shop", "tattoo")),
    "gym": _tags(("leisure", "fitness_centre")),
    "sports centre": _tags(("leisure", "sports_centre")),
    "swimming pool": _tags(("leisure", "swimming_pool")),
    "yoga": [_rx("sport", "yoga"), _rx("name", "yoga")],
    "dance school": _tags(("leisure", "dance")),
    # lodging & travel
    "hotel": _tags(("tourism", "hotel")),
    "hostel": _tags(("tourism", "hostel")),
    "guest house": _tags(("tourism", "guest_house")),
    "motel": _tags(("tourism", "motel")),
    "apartment rental": _tags(("tourism", "apartment")),
    "travel agency": _tags(("shop", "travel_agency"), ("office", "travel_agent")),
    "car rental": _tags(("amenity", "car_rental")),
    "taxi": _tags(("amenity", "taxi")),
    "museum": _tags(("tourism", "museum")),
    "tourist attraction": _tags(("tourism", "attraction")),
    # education
    "school": _tags(("amenity", "school")),
    "college": _tags(("amenity", "college")),
    "university": _tags(("amenity", "university")),
    "kindergarten": _tags(("amenity", "kindergarten")),
    "driving school": _tags(("amenity", "driving_school")),
    "language school": _tags(("amenity", "language_school")),
    "music school": _tags(("amenity", "music_school")),
    "coaching center": _tags(("amenity", "prep_school"), ("office", "educational_institution")),
    "library": _tags(("amenity", "library")),
    # finance & professional
    "bank": _tags(("amenity", "bank")),
    "atm": _tags(("amenity", "atm")),
    "money exchange": _tags(("amenity", "bureau_de_change")),
    "insurance": _tags(("office", "insurance")),
    "accountant": _tags(("office", "accountant")),
    "tax advisor": _tags(("office", "tax_advisor")),
    "lawyer": _tags(("office", "lawyer")),
    "notary": _tags(("office", "notary")),
    "real estate": _tags(("office", "estate_agent")),
    "architect": _tags(("office", "architect")),
    "it company": _tags(("office", "it")),
    "software company": _tags(("office", "it")),
    "company": _tags(("office", "company")),
    "consulting": _tags(("office", "consulting")),
    "advertising agency": _tags(("office", "advertising_agency")),
    "employment agency": _tags(("office", "employment_agency")),
    "coworking": _tags(("amenity", "coworking_space")),
    "ngo": _tags(("office", "ngo")),
    "government office": _tags(("office", "government")),
    # shops
    "clothing store": _tags(("shop", "clothes")),
    "shoe store": _tags(("shop", "shoes")),
    "jewelry": _tags(("shop", "jewelry")),
    "electronics": _tags(("shop", "electronics")),
    "mobile phone shop": _tags(("shop", "mobile_phone")),
    "computer store": _tags(("shop", "computer")),
    "furniture": _tags(("shop", "furniture")),
    "hardware store": _tags(("shop", "hardware"), ("shop", "doityourself")),
    "florist": _tags(("shop", "florist")),
    "book store": _tags(("shop", "books")),
    "stationery": _tags(("shop", "stationery")),
    "gift shop": _tags(("shop", "gift")),
    "toy store": _tags(("shop", "toys")),
    "sports shop": _tags(("shop", "sports")),
    "pet shop": _tags(("shop", "pet")),
    "bicycle shop": _tags(("shop", "bicycle")),
    "mall": _tags(("shop", "mall")),
    "department store": _tags(("shop", "department_store")),
    "photo studio": _tags(("shop", "photo"), ("craft", "photographer")),
    "print shop": _tags(("shop", "copyshop")),
    "tailor": _tags(("shop", "tailor"), ("craft", "tailor")),
    "laundry": _tags(("shop", "laundry"), ("shop", "dry_cleaning")),
    "interior design": _tags(("shop", "interior_decoration")),
    "funeral services": _tags(("shop", "funeral_directors")),
    # vehicles
    "car dealer": _tags(("shop", "car")),
    "car repair": _tags(("shop", "car_repair")),
    "car parts": _tags(("shop", "car_parts")),
    "tyre shop": _tags(("shop", "tyres")),
    "motorcycle dealer": _tags(("shop", "motorcycle")),
    "petrol station": _tags(("amenity", "fuel")),
    "car wash": _tags(("amenity", "car_wash")),
    "ev charging": _tags(("amenity", "charging_station")),
    # trades
    "plumber": _tags(("craft", "plumber")),
    "electrician": _tags(("craft", "electrician")),
    "carpenter": _tags(("craft", "carpenter")),
    "painter": _tags(("craft", "painter")),
    "builder": _tags(("craft", "builder")),
    "hvac": _tags(("craft", "hvac")),
    "roofer": _tags(("craft", "roofer")),
    "locksmith": _tags(("craft", "locksmith")),
    "caterer": _tags(("craft", "caterer")),
    "gardener": _tags(("craft", "gardener")),
    # public
    "post office": _tags(("amenity", "post_office")),
    "police": _tags(("amenity", "police")),
    "place of worship": _tags(("amenity", "place_of_worship")),
    "cinema": _tags(("amenity", "cinema")),
    "theatre": _tags(("amenity", "theatre")),
    "bowling": _tags(("leisure", "bowling_alley")),
    "golf course": _tags(("leisure", "golf_course")),
}

# synonyms / spellings -> canonical key
ALIASES: dict[str, str] = {
    "restaurants": "restaurant", "cafes": "cafe", "coffee shop": "cafe", "coffee": "cafe",
    "dentists": "dentist", "dental clinic": "dentist", "dental": "dentist", "orthodontist": "dentist",
    "doctors": "doctor", "physician": "doctor", "gp": "doctor", "clinics": "clinic",
    "hospitals": "hospital", "chemist": "pharmacy", "drugstore": "pharmacy", "medical store": "pharmacy",
    "pharmacies": "pharmacy", "vet": "veterinary", "veterinarian": "veterinary", "animal hospital": "veterinary",
    "hotels": "hotel", "lodging": "hotel", "gyms": "gym", "fitness": "gym", "fitness center": "gym",
    "fitness centre": "gym", "health club": "gym", "salon": "hair salon", "hairdresser": "hair salon",
    "barber": "hair salon", "barber shop": "hair salon", "spa": "beauty salon", "beauty parlour": "beauty salon",
    "beauty parlor": "beauty salon", "lawyers": "lawyer", "attorney": "lawyer", "advocate": "lawyer",
    "law firm": "lawyer", "accountants": "accountant", "chartered accountant": "accountant", "ca": "accountant",
    "cpa": "accountant", "estate agent": "real estate", "real estate agent": "real estate",
    "realtor": "real estate", "property dealer": "real estate", "banks": "bank", "schools": "school",
    "colleges": "college", "universities": "university", "preschool": "kindergarten", "nursery school": "kindergarten",
    "playschool": "kindergarten", "pizzeria": "pizza", "bakeries": "bakery", "supermarkets": "supermarket",
    "grocery store": "grocery", "kirana": "grocery", "general store": "convenience store",
    "clothes": "clothing store", "clothing": "clothing store", "garments": "clothing store",
    "boutique": "clothing store", "shoes": "shoe store", "footwear": "shoe store", "jeweller": "jewelry",
    "jeweler": "jewelry", "jewellery": "jewelry", "jewelry store": "jewelry", "mobile shop": "mobile phone shop",
    "cell phone store": "mobile phone shop", "computer shop": "computer store", "laptop shop": "computer store",
    "furniture store": "furniture", "hardware": "hardware store", "books": "book store", "bookshop": "book store",
    "bookstore": "book store", "pet store": "pet shop", "optical": "optician", "optical store": "optician",
    "eye clinic": "optician", "car showroom": "car dealer", "car dealership": "car dealer", "garage": "car repair",
    "auto repair": "car repair", "mechanic": "car repair", "workshop": "car repair", "gas station": "petrol station",
    "fuel station": "petrol station", "petrol pump": "petrol station", "plumbers": "plumber", "plumbing": "plumber",
    "electricians": "electrician", "electrical": "electrician", "carpenters": "carpenter", "painters": "painter",
    "contractor": "builder", "construction": "builder", "construction company": "builder",
    "air conditioning": "hvac", "ac repair": "hvac", "software": "software company", "it services": "it company",
    "digital marketing": "advertising agency", "marketing agency": "advertising agency",
    "travel agent": "travel agency", "tours": "travel agency", "tour operator": "travel agency",
    "guesthouse": "guest house", "bnb": "guest house", "bed and breakfast": "guest house", "inn": "guest house",
    "co-working": "coworking", "coworking space": "coworking", "temple": "place of worship", "church": "place of worship",
    "mosque": "place of worship", "masjid": "place of worship", "gurdwara": "place of worship",
    "movie theater": "cinema", "movie theatre": "cinema", "multiplex": "cinema", "tyre": "tyre shop",
    "tire shop": "tyre shop", "laundromat": "laundry", "dry cleaner": "laundry", "dry cleaning": "laundry",
    "photographer": "photo studio", "photography": "photo studio", "xerox": "print shop", "printing": "print shop",
    "interior designer": "interior design", "undertaker": "funeral services", "sweet": "sweet shop",
    "sweets": "sweet shop", "mithai": "sweet shop", "ice-cream": "ice cream", "icecream": "ice cream",
    "chinese": "chinese restaurant", "indian": "indian restaurant", "italian": "italian restaurant",
    "diagnostic center": "diagnostic lab", "pathology": "diagnostic lab", "path lab": "diagnostic lab",
    "psychiatrist": "psychologist", "therapist": "psychologist", "physio": "physiotherapist",
    "tuition": "coaching center", "coaching": "coaching center", "tutoring": "coaching center",
}


def normalize(keyword: str) -> str:
    s = re.sub(r"[^a-z0-9&\- ]", " ", keyword.lower()).replace("&", " and ")
    return re.sub(r"\s+", " ", s).strip()


def _singular(s: str) -> str:
    if s.endswith("ies") and len(s) > 4:
        return s[:-3] + "y"
    if s.endswith("ses") or s.endswith("xes"):
        return s[:-2]
    if s.endswith("s") and not s.endswith("ss") and len(s) > 3:
        return s[:-1]
    return s


def canonical(keyword: str) -> str | None:
    n = normalize(keyword)
    for cand in (n, _singular(n)):
        if cand in CATEGORIES:
            return cand
        if cand in ALIASES:
            return ALIASES[cand]
    return None


def _safe(s: str) -> str:
    """Characters that are safe inside an Overpass regex string literal."""
    return re.sub(r"[^a-z0-9\u00c0-\u024f \-]", "", s.lower()).strip()


def filters_for(keyword: str) -> tuple[list[str], str]:
    """Return (tag filters, mode). mode is 'mapped' for known categories, 'generic' for the fallback."""
    canon = canonical(keyword)
    if canon:
        return CATEGORIES[canon], "mapped"
    kw = _safe(keyword)
    if not kw:
        return [], "generic"
    val = re.sub(r"[ \-]+", ".", kw)       # "dental clinic" also matches tag values like dental_clinic
    clauses = [_rx("name", kw), _rx("brand", kw), _rx("cuisine", val)]
    clauses += [_rx(k, f"^{val}$") for k in ("amenity", "shop", "office", "craft", "tourism", "leisure", "healthcare")]
    return clauses, "generic"


def suggestions() -> list[str]:
    return sorted(set(CATEGORIES) | set(ALIASES))


def known(keywords: Iterable[str]) -> dict[str, bool]:
    return {k: canonical(k) is not None for k in keywords}

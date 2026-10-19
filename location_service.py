"""Location lookup backed by Photon, which indexes OpenStreetMap places."""

import json
import logging
import threading
import time
from functools import lru_cache
from urllib.parse import urlencode
import urllib.request

logger = logging.getLogger("uvicorn.error")
_nominatim_lock = threading.Lock()
_nominatim_last_request = 0.0
_PHOTON_LOCATION_LAYERS = ("locality", "district", "city", "county", "state")
_PHOTON_PLACE_VALUES = {
    "city", "town", "village", "hamlet", "suburb", "neighbourhood",
    "quarter", "municipality", "county", "district", "region", "state",
    "province", "administrative",
}
_NOMINATIM_PLACE_TYPES = {
    "city", "town", "village", "hamlet", "suburb", "neighbourhood",
    "quarter", "municipality", "county", "state", "province", "administrative",
}

def photon_locations(query: str) -> list[str]:
    normalized = " ".join(query.casefold().split())
    return list(_photon_locations_cached(normalized))


@lru_cache(maxsize=1024)
def _photon_locations_cached(query: str) -> tuple[str, ...]:
    params = urlencode([
        ("q", query),
        ("limit", "10"),
        ("lang", "en"),
        ("bbox", "68.1,6.7,97.4,35.7"),
        *(("layer", layer) for layer in _PHOTON_LOCATION_LAYERS),
    ])
    request = urllib.request.Request(
        f"https://photon.komoot.io/api/?{params}",
        headers={"User-Agent": "ProfilentPropertyEnquiry/1.0"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        data = json.loads(response.read().decode("utf-8"))

    labels, seen = [], set()
    for feature in data.get("features", []):
        place = feature.get("properties", {})
        if place.get("countrycode", "").upper() != "IN":
            continue
        layer = str(place.get("type", "")).casefold()
        osm_place_value = (
            str(place.get("osm_value", "")).casefold()
            if str(place.get("osm_key", "")).casefold() == "place"
            else ""
        )
        if layer not in _PHOTON_LOCATION_LAYERS and osm_place_value not in _PHOTON_PLACE_VALUES:
            continue
        parts = []
        for key in ("name", "locality", "district", "city", "county", "state"):
            value = place.get(key)
            if value and value.casefold() not in {part.casefold() for part in parts}:
                parts.append(value)
        label = ", ".join(parts)
        if label and label.casefold() not in seen:
            labels.append(label)
            seen.add(label.casefold())
    return tuple(labels)


@lru_cache(maxsize=512)
def _nominatim_locations_cached(query: str) -> tuple[str, ...]:
    """Low-volume fallback lookup; called only for submit/reply validation, never autocomplete."""
    global _nominatim_last_request
    params = urlencode({
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 10,
        "countrycodes": "in",
    })
    request = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/search?{params}",
        headers={
            "User-Agent": "ProfilentPropertyEnquiry/1.0",
            "Accept-Language": "en",
        },
    )
    with _nominatim_lock:
        wait = 1.0 - (time.monotonic() - _nominatim_last_request)
        if wait > 0:
            time.sleep(wait)
        _nominatim_last_request = time.monotonic()
        with urllib.request.urlopen(request, timeout=5) as response:
            results = json.loads(response.read().decode("utf-8"))

    labels, seen = [], set()
    keys = ("city", "town", "village", "municipality", "suburb", "hamlet", "county", "state")
    for result in results:
        address = result.get("address") or {}
        if address.get("country_code", "").casefold() != "in":
            continue
        result_class = str(result.get("class", "")).casefold()
        result_type = str(result.get("type", "")).casefold()
        is_place = result_class == "place" and result_type in _NOMINATIM_PLACE_TYPES
        is_administrative_boundary = result_class == "boundary" and result_type == "administrative"
        if not (is_place or is_administrative_boundary):
            continue
        parts = []
        for value in (result.get("name"), *(address.get(key) for key in keys)):
            if value and value.casefold() not in {part.casefold() for part in parts}:
                parts.append(value)
        label = ", ".join(parts)
        if label and label.casefold() not in seen:
            labels.append(label)
            seen.add(label.casefold())
    return tuple(labels)


def verified_locations(query: str) -> list[str]:
    normalized = " ".join(query.casefold().split())
    return list(_verified_locations_cached(normalized))


@lru_cache(maxsize=1024)
def _verified_locations_cached(query: str) -> tuple[str, ...]:
    """Use Photon first, then a rate-limited Nominatim lookup for validation only."""
    photon_error = None
    try:
        locations = photon_locations(query)
        if locations:
            return tuple(locations)
    except Exception as exc:
        photon_error = exc
        logger.warning("Photon location lookup failed; trying validation fallback: %s", exc)

    try:
        return _nominatim_locations_cached(query)
    except Exception as fallback_error:
        logger.exception("Nominatim location validation fallback failed")
        raise RuntimeError("Location providers are unavailable") from (fallback_error or photon_error)


def is_verified_place(query: str, labels: list[str]) -> bool:
    """Require a meaningful exact match to a returned place component."""
    normalized = " ".join(query.casefold().split())
    if len(normalized) < 3:
        return False
    return any(
        normalized == " ".join(part.casefold().split())
        for label in labels
        for part in label.split(",")
    )

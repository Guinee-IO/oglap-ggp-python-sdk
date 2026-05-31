"""
OGLAP Protocol Core Engine — public API.

Exposes 16 functions mirroring the JavaScript SDK.
"""

from __future__ import annotations

import re
import math
from typing import Any, Callable

from ._constants import MAX_ZONE_CODE_LENGTH, PACKAGE_VERSION
from ._download import init_oglap_download
from ._geo import (
    bbox_from_geometry,
    centroid_from_bbox,
    point_in_geometry,
)
from ._grid import (
    decode_macroblock,
    decode_microspot,
    meters_per_degree_lat,
    meters_per_degree_lon,
    wrap_lon,
)
from ._spatial import (
    build_lap_search_index,
    build_oglap_result,
    build_places_rtree,
    reverse_geocode,
)
from ._state import state
from ._validate import validate_and_apply


ZONE_CODE_RE = re.compile(rf"^[A-Z0-9]{{1,{MAX_ZONE_CODE_LENGTH}}}$")
LOCAL_MACROBLOCK_RE = re.compile(r"^[A-J]\d[A-J]\d$", re.IGNORECASE)
NATIONAL_MACROBLOCK_RE = re.compile(r"^[A-Z]{6}$")
MICROSPOT_RE = re.compile(r"^\d{4}$")


# ── Simple getters ──────────────────────────────────────────────────

def get_package_version() -> str:
    """Current OGLAP package version."""
    return PACKAGE_VERSION


def get_country_profile() -> dict[str, Any]:
    """Current active country profile."""
    return state.country_profile


def get_country_code() -> str:
    """2-letter Country OGLAP code (e.g. ``"GN"``)."""
    return state.country_code


def get_country_sw() -> list[float]:
    """The SW boundary constraint ``[lat, lon]`` for the country."""
    return state.country_sw


def get_oglap_prefectures() -> dict[str, str]:
    """Map of prefecture codes."""
    return state.oglap_country_prefectures


def check_oglap() -> dict[str, Any]:
    """Quick status check. Returns the last init report, or a not-initialized stub."""
    if state.init_report is not None:
        return state.init_report
    return {
        "ok": False,
        "countryCode": None,
        "countryName": None,
        "bounds": None,
        "checks": [],
        "error": "initOglap has not been called yet.",
    }


# ── Initialization ──────────────────────────────────────────────────

async def init_oglap(
    profile_or_options: dict[str, Any] | None = None,
    localities_naming: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Initialize the OGLAP engine.

    **Download mode** (recommended)::

        report = await init_oglap()
        # or with options:
        report = await init_oglap({
            "version": "v1.0.0",
            "data_dir": "./oglap-data",
            "force_download": False,
            "on_progress": my_callback,
        })

    **Direct mode** (when data is already loaded)::

        report = await init_oglap(profile_obj, localities_naming_obj)
        load_oglap(places_array)
    """
    state.initialized = False
    state.init_report = None
    state.reset_loaded_data(clear_places=True)

    # ── Direct mode: init_oglap(profile, localities) ──
    is_direct = (
        localities_naming is not None
        or (
            profile_or_options is not None
            and isinstance(profile_or_options, dict)
            and "schema_id" in profile_or_options
        )
    )
    if is_direct:
        report = validate_and_apply(profile_or_options, localities_naming)
        state.initialized = report["ok"]
        state.init_report = report
        return report

    # ── Download mode ──
    opts = profile_or_options or {}
    on_progress: Callable[..., None] = opts.get("on_progress") or (lambda **kw: None)

    dl = await init_oglap_download(opts)
    checks: list[dict[str, str]] = dl["checks"]
    version_dir = dl["version_dir"]

    if dl.get("error"):
        report = {
            "ok": False,
            "countryCode": None,
            "countryName": None,
            "bounds": None,
            "checks": checks,
            "error": dl["error"],
            "dataDir": version_dir,
        }
        state.init_report = report
        return report

    # Validate profile + localities
    on_progress(
        file="", label="Validating configuration",
        step=0, totalSteps=0,
        status="validating", loaded=0, total=0, percent=0,
    )
    report = validate_and_apply(dl["profile"], dl["localities"], checks)
    if not report["ok"]:
        state.init_report = report
        report["dataDir"] = version_dir
        return report

    # Load places
    state.initialized = True
    try:
        load_result = load_oglap(dl["data"])
    except Exception as err:
        load_result = {"ok": False, "count": 0, "message": f"Failed to load places database: {err}"}
    report["checks"].append({
        "id": "data.load",
        "status": "pass" if load_result["ok"] else "fail",
        "message": load_result["message"],
    })
    if not load_result["ok"]:
        report["ok"] = False
        report["error"] = load_result["message"]
        state.initialized = False
        state.reset_loaded_data(clear_places=True)
    report["dataLoaded"] = load_result
    report["dataDir"] = version_dir
    state.init_report = report
    return report


# ── Data loading ────────────────────────────────────────────────────

def load_oglap(data: Any) -> dict[str, Any]:
    """Load GeoJSON places into the in-memory engine.

    Validates that ``init_oglap`` was called first.
    """
    state.reset_loaded_data(clear_places=True)

    if not state.initialized:
        return {"ok": False, "count": 0, "message": "Cannot load data: initOglap must be called first with a valid profile and localities naming."}

    if not isinstance(data, list):
        return {"ok": False, "count": 0, "message": "Data must be an array of place objects."}

    if len(data) == 0:
        return {"ok": False, "count": 0, "message": "Data array is empty — no places to load."}

    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            return {"ok": False, "count": 0, "message": f"Data entry at index {i} is not a valid place object."}
        has_geometry = bool(entry.get("geojson"))
        has_address = entry.get("address") is not None
        has_place_id = entry.get("place_id") is not None
        if not has_place_id and not has_geometry and not has_address:
            return {"ok": False, "count": 0, "message": f"Data entry at index {i} does not appear to be an OGLAP place object (missing place_id, geojson, and address)."}

    state.places = data

    # Cache country border polygon (admin_level 2)
    state.country_border_geojson = None
    for p in data:
        et = p.get("extratags") or {}
        al = et.get("admin_level")
        if str(al) == "2":
            geo = p.get("geojson") or {}
            if geo.get("type") in ("Polygon", "MultiPolygon"):
                state.country_border_geojson = geo
                break

    try:
        # Build the R-tree spatial index eagerly. O(N) build, O(log N + K) queries.
        # For ~17K places this takes a few ms and saves a lot on every reverse_geocode.
        build_places_rtree()
    except Exception as err:
        state.reset_loaded_data(clear_places=True)
        return {
            "ok": False,
            "count": 0,
            "message": f"Failed to build spatial index: {err}",
        }

    with_geometry = sum(1 for p in data if p.get("geojson"))
    return {
        "ok": True,
        "count": len(data),
        "message": f"Loaded {len(data)} places ({with_geometry} with geometry).",
    }


def get_oglap_places() -> list[dict[str, Any]]:
    """Retrieve the currently loaded geography places."""
    return state.places


# ── LAP code parsing / validation ───────────────────────────────────

def _to_query_string(query: Any) -> str:
    return query.strip() if isinstance(query, str) else ""


def _is_valid_zone_code(code: str) -> bool:
    return bool(isinstance(code, str) and ZONE_CODE_RE.match(code))


def parse_lap_code(query: str) -> dict[str, Any] | None:
    """Parse a raw search query into structured LAP components."""
    q = _to_query_string(query)
    if not q or len(q) > 64:
        return None
    parts = [p.upper() for p in re.split(r"[\s\-]+", q) if p]
    cc = state.country_code

    if len(parts) == 4 and parts[0] == cc:
        admin2_iso = state.oglap_country_regions_reverse.get(parts[1])
        if admin2_iso and NATIONAL_MACROBLOCK_RE.match(parts[2]) and MICROSPOT_RE.match(parts[3]):
            return {"admin_level_2_Iso": admin2_iso, "admin_level_3_code": None, "macroblock": parts[2], "microspot": parts[3], "isNationalGrid": True}

    if len(parts) == 5 and parts[0] == cc:
        admin2_iso = state.oglap_country_regions_reverse.get(parts[1])
        if admin2_iso and _is_valid_zone_code(parts[2]) and LOCAL_MACROBLOCK_RE.match(parts[3]) and MICROSPOT_RE.match(parts[4]):
            return {"admin_level_2_Iso": admin2_iso, "admin_level_3_code": parts[2], "macroblock": parts[3], "microspot": parts[4], "isNationalGrid": False}

    if len(parts) == 3 and parts[0] != cc:
        admin2_iso = state.oglap_country_regions_reverse.get(parts[0])
        if admin2_iso and NATIONAL_MACROBLOCK_RE.match(parts[1]) and MICROSPOT_RE.match(parts[2]):
            return {"admin_level_2_Iso": admin2_iso, "admin_level_3_code": None, "macroblock": parts[1], "microspot": parts[2], "isNationalGrid": True}

    if len(parts) == 4 and parts[0] != cc:
        admin2_iso = state.oglap_country_regions_reverse.get(parts[0])
        if admin2_iso and _is_valid_zone_code(parts[1]) and LOCAL_MACROBLOCK_RE.match(parts[2]) and MICROSPOT_RE.match(parts[3]):
            return {"admin_level_2_Iso": admin2_iso, "admin_level_3_code": parts[1], "macroblock": parts[2], "microspot": parts[3], "isNationalGrid": False}

    if len(parts) == 3 and parts[0] == cc:
        admin2_iso = state.oglap_country_regions_reverse.get(parts[1])
        if admin2_iso and _is_valid_zone_code(parts[2]):
            return {"admin_level_2_Iso": admin2_iso, "admin_level_3_code": parts[2]}

    if len(parts) == 2 and len(parts[0]) <= 4 and len(parts[1]) <= MAX_ZONE_CODE_LENGTH:
        admin2_iso = state.oglap_country_regions_reverse.get(parts[0])
        if admin2_iso and _is_valid_zone_code(parts[1]):
            return {"admin_level_2_Iso": admin2_iso, "admin_level_3_code": parts[1]}

    if len(parts) == 1 and _is_valid_zone_code(parts[0]):
        token = parts[0]
        if token == cc or token in state.oglap_country_regions_reverse:
            return None
        return {"admin_level_3_code": token}

    return None


def validate_lap_code(query: str) -> str | None:
    """Validate a LAP or zone search input format.

    Accepts full LAP with or without country prefix (national or local), zone search.
    Returns ``None`` if perfectly valid, or a descriptive error string.
    """
    q = _to_query_string(query)
    if not q:
        return "Enter a LAP code or zone code to search."
    if len(q) > 64:
        return "Input too long. A valid LAP code is at most ~25 characters."

    parts = [p.upper() for p in re.split(r"[\s\-]+", q) if p]
    cc = state.country_code

    if len(parts) > 5:
        return "Invalid format: too many segments. Use e.g. GN-CKY-QKPC-B4A4-2798 (local) or GN-CKY-XXXYYY-2798 (national) or zone code QKAR."

    # 5 parts: CC-ADMIN2-ADMIN3-MACRO-MICRO (local with CC)
    if len(parts) == 5:
        if parts[0] != cc:
            return 'LAP code must start with country code "%s" when using 5-segment format.' % cc
        admin2 = state.oglap_country_regions_reverse.get(parts[1])
        if not admin2:
            return 'Unknown region code "%s". Use a valid ADMIN_LEVEL_2 code (e.g. CKY).' % parts[1]
        if not _is_valid_zone_code(parts[2]):
            return f"Zone (ADMIN_LEVEL_3) code must be 1-{MAX_ZONE_CODE_LENGTH} letters or digits."
        if len(parts[3]) != 4:
            return "Local macroblock must be 4 characters (e.g. B4A4)."
        if not LOCAL_MACROBLOCK_RE.match(parts[3]):
            return "Local macroblock format: letter-digit-letter-digit (e.g. B4A4)."
        if not MICROSPOT_RE.match(parts[4]):
            return "Microspot must be 4 digits (e.g. 2798)."
        return None

    # 4 parts: CC-ADMIN2-MACRO6-MICRO (national with CC) OR ADMIN2-ADMIN3-MACRO4-MICRO (local without CC)
    if len(parts) == 4:
        if parts[0] == cc:
            # National with CC: CC-ADMIN2-XXXYYY-MICRO
            admin2 = state.oglap_country_regions_reverse.get(parts[1])
            if not admin2:
                return 'Unknown region code "%s". Use a valid ADMIN_LEVEL_2 code (e.g. CKY).' % parts[1]
            if not NATIONAL_MACROBLOCK_RE.match(parts[2]):
                return "National macroblock must be 6 letters (e.g. ABCDEF)."
            if not MICROSPOT_RE.match(parts[3]):
                return "Microspot must be 4 digits (e.g. 2798)."
            return None
        # Local without CC: ADMIN2-ADMIN3-MACRO4-MICRO
        admin2 = state.oglap_country_regions_reverse.get(parts[0])
        if not admin2:
            return 'Unknown region code "%s". Use a valid ADMIN_LEVEL_2 code (e.g. CKY).' % parts[0]
        if not _is_valid_zone_code(parts[1]):
            return f"Zone (ADMIN_LEVEL_3) code must be 1-{MAX_ZONE_CODE_LENGTH} letters or digits."
        if len(parts[2]) != 4:
            return "Local macroblock must be 4 characters (e.g. B4A4)."
        if not LOCAL_MACROBLOCK_RE.match(parts[2]):
            return "Local macroblock format: letter-digit-letter-digit (e.g. B4A4)."
        if not MICROSPOT_RE.match(parts[3]):
            return "Microspot must be 4 digits (e.g. 2798)."
        return None

    # 3 parts: ADMIN2-MACRO6-MICRO (national without CC) OR CC-ADMIN2-ADMIN3 (zone search)
    if len(parts) == 3:
        if parts[0] == cc:
            # Zone search: CC-ADMIN2-ADMIN3
            admin2 = state.oglap_country_regions_reverse.get(parts[1])
            if not admin2:
                return 'Unknown region code "%s". Use a valid ADMIN_LEVEL_2 code (e.g. CKY).' % parts[1]
            if not _is_valid_zone_code(parts[2]):
                return f"Zone code must be 1-{MAX_ZONE_CODE_LENGTH} letters or digits."
            return None
        # National without CC: ADMIN2-XXXYYY-MICRO
        admin2 = state.oglap_country_regions_reverse.get(parts[0])
        if (
            admin2
            and NATIONAL_MACROBLOCK_RE.match(parts[1])
            and MICROSPOT_RE.match(parts[2])
        ):
            return None
        if admin2:
            return "Three-segment codes without a country prefix must be national LAPs: ADMIN2-XXXXXX-1234."
        return 'Unknown region code "%s". Use a valid ADMIN_LEVEL_2 code (e.g. CKY).' % parts[0]

    if len(parts) == 2:
        admin2 = state.oglap_country_regions_reverse.get(parts[0])
        if not admin2:
            return 'Unknown region code "%s". Use e.g. CKY QKAR.' % parts[0]
        if not _is_valid_zone_code(parts[1]):
            return f"Zone code must be 1-{MAX_ZONE_CODE_LENGTH} letters or digits."
        return None

    if len(parts) == 1:
        if not _is_valid_zone_code(parts[0]):
            return f"Zone code only must be 1-{MAX_ZONE_CODE_LENGTH} letters or digits (e.g. QKAR)."
        return None

    return "Invalid LAP or zone format. Use full LAP (GN-CKY-...), or zone code (e.g. QKAR)."


# ── Place lookup ────────────────────────────────────────────────────

def get_place_by_lap_code(query: str) -> dict[str, Any] | None:
    """Find the first place matching a LAP search query.

    Returns ``{place, parsed, originLat?, originLon?}`` or ``None``.
    """
    if not state.initialized:
        raise RuntimeError("OGLAP not initialized. Call init_oglap() with a valid profile and localities naming first.")

    parsed = parse_lap_code(query)
    if not parsed:
        return None

    if parsed.get("isNationalGrid") and parsed.get("admin_level_2_Iso"):
        return {"place": None, "parsed": parsed, "originLat": state.country_sw[0], "originLon": state.country_sw[1]}

    if not state.places:
        return None

    index = build_lap_search_index()
    place = None

    if parsed.get("admin_level_2_Iso") and parsed.get("admin_level_3_code"):
        key = f"{parsed['admin_level_2_Iso']}_{parsed['admin_level_3_code']}"
        place = index.get(key)
    elif parsed.get("admin_level_3_code"):
        suffix = f"_{parsed['admin_level_3_code']}"
        matches = sorted(k for k in index if k.endswith(suffix))
        if matches:
            place = index[matches[0]]

    if not place:
        return None
    return {"place": place, "parsed": parsed}


# ── Coordinate conversion ──────────────────────────────────────────

def lap_to_coordinates(lap_code: str) -> dict[str, float] | None:
    """Decode a LAP code string into ``{lat, lon}`` GPS coordinates.

    Accepts LAP codes with or without the country prefix::

        lap_to_coordinates("GN-FAR-HMDEUP-3241")   # national with CC
        lap_to_coordinates("FAR-HMDEUP-3241")       # national without CC
        lap_to_coordinates("GN-CON-QCL0-A2A3-5940") # local with CC
        lap_to_coordinates("CON-QCL0-A2A3-5940")    # local without CC

    Returns ``None`` if the code cannot be parsed or resolved.
    """
    if not state.initialized:
        raise RuntimeError("OGLAP not initialized. Call init_oglap() with a valid profile and localities naming first.")

    parsed = parse_lap_code(lap_code)
    if not parsed or not parsed.get("macroblock") or not parsed.get("microspot"):
        return None

    macro = decode_macroblock(parsed["macroblock"])
    micro = decode_microspot(parsed["microspot"])
    if not macro or not micro:
        return None

    if parsed.get("isNationalGrid"):
        origin_lat = state.country_sw[0]
        origin_lon = state.country_sw[1]
    else:
        # Local grid: resolve zone origin from the place's bbox
        from ._geo import get_cached_bbox

        match = get_place_by_lap_code(lap_code)
        if not match or not match.get("place"):
            return None
        bbox = get_cached_bbox(match["place"])
        if not bbox:
            return None
        origin_lat = bbox[0]  # minLat
        origin_lon = bbox[2]  # minLon

    from ._constants import NATIONAL_CELL_SIZE_M, NATIONAL_MICRO_SCALE

    m_per_lat = meters_per_degree_lat(origin_lat)
    is_national = len(parsed["macroblock"]) == 6
    cell_size = NATIONAL_CELL_SIZE_M if is_national else 100
    micro_scale = NATIONAL_MICRO_SCALE if is_national else 1

    east_m = macro["blockEast"] * cell_size + micro["eastM"] * micro_scale
    north_m = macro["blockNorth"] * cell_size + micro["northM"] * micro_scale
    lat = origin_lat + north_m / m_per_lat
    lon = wrap_lon(origin_lon + east_m / meters_per_degree_lon(origin_lat))
    if not math.isfinite(lat) or not math.isfinite(lon) or lat < -90 or lat > 90:
        return None
    return {"lat": lat, "lon": lon}


def _is_lon_in_country_range(lon: float) -> bool:
    sw_lon = state.country_bounds["sw"][1]
    ne_lon = state.country_bounds["ne"][1]
    if state.country_crosses_antimeridian:
        return lon >= sw_lon or lon <= ne_lon
    return sw_lon <= lon <= ne_lon


def coordinates_to_lap(lat: float, lon: float) -> dict[str, Any] | None:
    """Convert WGS84 coordinates to a fully-qualified OGLAP code object.

    Returns ``None`` if the coordinates are outside the country boundaries.
    """
    if not state.initialized:
        raise RuntimeError("OGLAP not initialized. Call init_oglap() with a valid profile and localities naming first.")

    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    lat = float(lat)
    lon = float(lon)
    if not math.isfinite(lat) or not math.isfinite(lon):
        return None
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return None
    if state.country_crosses_antimeridian and lon == -180:
        lon = 180

    # Fast reject: outside bounding box
    sw = state.country_bounds["sw"]
    ne = state.country_bounds["ne"]
    if lat < sw[0] or lat > ne[0]:
        return None
    if not _is_lon_in_country_range(lon):
        return None

    # Precise reject: outside country border polygon
    if state.country_border_geojson and not point_in_geometry(lon, lat, state.country_border_geojson):
        return None

    rev = reverse_geocode(lon, lat)
    return build_oglap_result(lat, lon, rev)

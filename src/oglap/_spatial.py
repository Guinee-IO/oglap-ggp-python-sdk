"""
Spatial lookups — reverse geocoding, admin-level resolution,
collision-aware zone assignment, LAP search index, and OGLAP result builder.
"""

from __future__ import annotations

import math
from typing import Any

from ._geo import (
    centroid_from_place,
    close_rings,
    compute_area,
    get_cached_bbox,
    point_in_geometry,
)
from ._grid import compute_lap, meters_per_degree_lat, meters_per_degree_lon
from ._naming import (
    _parse_admin_level,
    get_place_zone_candidates,
    zone_code_from_name_and_type,
    get_type_prefix_for_zone,
    get_significant_tokens,
    name_key_from_tokens,
)
from ._state import state


# ── Place name extraction ───────────────────────────────────────────

def get_place_name(place: dict[str, Any] | None) -> str:
    """Extract the most meaningful name from a place object."""
    if not place:
        return "Unknown"
    et = place.get("extratags") or {}
    if et.get("name"):
        return et["name"]
    addr = place.get("address") or {}
    for key in ("neighbourhood", "suburb", "village", "city", "town", "county", "state"):
        if addr.get(key):
            return addr[key]
    return "Unknown"


# ── Admin level 2 resolution chain ─────────────────────────────────

def get_admin_level_2_iso_from_address(address: dict[str, Any]) -> str | None:
    """Get ADMIN_LEVEL_2 ISO from address (ISO3166-2-Lvl4)."""
    return address.get("ISO3166-2-Lvl4") or address.get("ISO3166-2-lvl4") or None


def get_admin_level_2_code(address: dict[str, Any]) -> str | None:
    """Get ADMIN_LEVEL_2 OGLAP code from address."""
    iso4 = get_admin_level_2_iso_from_address(address)
    return state.oglap_country_regions.get(iso4) if iso4 else None


def get_admin_level_2_from_region_containment(lon: float, lat: float) -> str | None:
    """Find region (admin_level 4) that contains the point; return its ISO."""
    for place in state.places:
        level = _parse_admin_level(place)
        if level != 4:
            continue
        iso = get_admin_level_2_iso_from_address(place.get("address") or {})
        if not iso:
            continue
        if point_in_geometry(lon, lat, place.get("geojson")):
            return iso
    return None


def get_admin_level_2_by_sampling(
    lon: float,
    lat: float,
    num_samples: int = 5,
    radius_m: float = 750,
) -> str | None:
    """Sample 3-7 points in radius; return majority ADMIN_LEVEL_2 ISO."""
    m_per_lat = meters_per_degree_lat()
    m_per_lon = meters_per_degree_lon(lat)
    counts: dict[str, int] = {}

    for i in range(num_samples):
        angle = (i / num_samples) * 2 * math.pi
        east_m = radius_m * math.cos(angle)
        north_m = radius_m * math.sin(angle)
        d_lat = north_m / m_per_lat
        d_lon = east_m / m_per_lon
        lat2 = lat + d_lat
        lon2 = lon + d_lon

        iso = get_admin_level_2_from_region_containment(lon2, lat2)
        if not iso:
            rev = reverse_geocode(lon2, lat2)
            if rev:
                iso = get_admin_level_2_iso_from_address(rev["place"].get("address") or {})
        if iso:
            counts[iso] = counts.get(iso, 0) + 1

    best: str | None = None
    best_count = 0
    for iso, c in counts.items():
        if c > best_count:
            best_count = c
            best = iso
    return best


def get_admin_level_2_with_fallback(
    lat: float,
    lon: float,
    place: dict[str, Any] | None,
    skip_sampling: bool = False,
) -> str:
    """ADMIN_LEVEL_2 OGLAP code with fallbacks: address -> region containment -> sampling -> None."""
    address = (place.get("address") or {}) if place else {}
    iso = get_admin_level_2_iso_from_address(address)
    if iso and iso in state.oglap_country_regions:
        return state.oglap_country_regions[iso]
    iso = get_admin_level_2_from_region_containment(lon, lat)
    if iso and iso in state.oglap_country_regions:
        return state.oglap_country_regions[iso]
    if not skip_sampling:
        iso = get_admin_level_2_by_sampling(lon, lat, 5, 750)
        if iso and iso in state.oglap_country_regions:
            return state.oglap_country_regions[iso]
    return None


def get_admin_level_2_iso_with_fallback(
    lat: float,
    lon: float,
    place: dict[str, Any] | None,
    skip_sampling: bool = False,
) -> str:
    """ADMIN_LEVEL_2 ISO with same fallbacks (for grouping / collision)."""
    address = (place.get("address") or {}) if place else {}
    iso = get_admin_level_2_iso_from_address(address)
    if iso:
        return iso
    iso = get_admin_level_2_from_region_containment(lon, lat)
    if iso:
        return iso
    if not skip_sampling:
        iso = get_admin_level_2_by_sampling(lon, lat, 5, 750)
        if iso:
            return iso
    return None


# ── Zone grid strategy ──────────────────────────────────────────────

def use_zone_grid_for_place(place: dict[str, Any] | None) -> bool:
    """True if place has admin_level >= 9 AND meaningful name tokens (use local zone grid)."""
    if not place:
        return False
    level = _parse_admin_level(place)
    if level < 9:
        return False
    # If place has a pre-assigned zone code in localities naming, use local grid
    pid = place.get("place_id")
    if pid is not None and (pid in state.oglap_zone_codes_by_id or str(pid) in state.oglap_zone_codes_by_id):
        return True
    # Check if place has meaningful name tokens for zone code generation
    address = place.get("address") or {}
    name = (
        address.get("quarter") or address.get("neighbourhood") or address.get("suburb")
        or address.get("village") or address.get("hamlet") or address.get("town")
        or address.get("city")
        or (place.get("display_name", "").split(",")[0].strip() if place.get("display_name") else "")
    )
    significant = get_significant_tokens(name)
    return len(significant) > 0


# ── Effective admin-level-2 ISO for a place ─────────────────────────

def effective_admin_level_2_iso_for_place(
    place: dict[str, Any],
    skip_sampling: bool = False,
) -> str:
    cen = centroid_from_place(place)
    if cen:
        return get_admin_level_2_iso_with_fallback(cen[0], cen[1], place, skip_sampling)
    return get_admin_level_2_iso_from_address(place.get("address") or {}) or None


# ── Collision-aware zone assignments ────────────────────────────────

def build_admin_level_2_zone_assignments(admin_level_2_iso: str) -> dict[Any, str]:
    """Deterministic zone-code assignment per ADMIN_LEVEL_2 (collision avoidance)."""
    iso_key = admin_level_2_iso or ""
    in_admin = [
        p for p in state.places
        if effective_admin_level_2_iso_for_place(p, skip_sampling=True) == iso_key
    ]
    sorted_places = sorted(in_admin, key=lambda p: p.get("place_id", 0) or 0)

    used: set[str] = set()
    digit_count_by_base: dict[str, int] = {}
    assignment: dict[Any, str] = {}

    for place in sorted_places:
        candidates = get_place_zone_candidates(place)
        base_code = candidates["baseCode"]
        fallback_code = candidates["fallbackCode"]
        prefix3 = base_code[:3]
        final_code: str | None = None

        if base_code not in used:
            final_code = base_code
        elif fallback_code and fallback_code not in used:
            final_code = fallback_code
        else:
            nxt = digit_count_by_base.get(prefix3, 0)
            digit = min(9, nxt)
            digit_count_by_base[prefix3] = nxt + 1
            final_code = prefix3 + str(digit)

        used.add(final_code)
        assignment[place.get("place_id")] = final_code

    return assignment


def get_admin_level_3_code_with_collision(place: dict[str, Any] | None) -> str | None:
    """ADMIN_LEVEL_3 zone code respecting manual overrides then collision resolution."""
    if not place:
        return None
    pid = place.get("place_id")
    # Use explicit zone code from localities naming data if present
    if pid is not None and pid in state.oglap_zone_codes_by_id:
        return state.oglap_zone_codes_by_id[pid]
    admin_level_2_iso = effective_admin_level_2_iso_for_place(place)
    assignments = build_admin_level_2_zone_assignments(admin_level_2_iso)
    return assignments.get(pid) or get_place_zone_candidates(place)["baseCode"]


def get_admin_level_3_code(
    address: dict[str, Any],
    place_type: str,
    display_name: str,
    admin_level: int | None,
) -> str:
    """ADMIN_LEVEL_3 zone code from address/type/name (no collision context)."""
    name = (
        address.get("quarter")
        or address.get("neighbourhood")
        or address.get("suburb")
        or address.get("village")
        or address.get("hamlet")
        or address.get("town")
        or address.get("city")
        or (display_name.split(",")[0].strip() if display_name else "")
    )
    prefix = get_type_prefix_for_zone(place_type, admin_level)
    return zone_code_from_name_and_type(name, prefix, address)


# ── Reverse geocode ─────────────────────────────────────────────────

def reverse_geocode(lon: float, lat: float) -> dict[str, Any] | None:
    """Find smallest containing feature for ``(lon, lat)``, bubble up address hierarchy."""
    containing: list[dict[str, Any]] = []

    for place in state.places:
        geo = place.get("geojson")
        if not geo:
            continue
        geo_type = geo.get("type")
        if geo_type in ("Point", "MultiPoint"):
            continue
        if not point_in_geometry(lon, lat, geo):
            continue

        closed = close_rings(geo)
        if place.get("_computed_area") is None:
            try:
                place["_computed_area"] = compute_area(closed)
            except Exception:
                continue
        containing.append({"place": place, "area": place["_computed_area"]})

    if not containing:
        return None

    containing.sort(key=lambda x: x["area"])

    # Best (smallest) feature
    best = containing[0]["place"]
    if not best.get("address"):
        best["address"] = {}

    # Bubble up missing hierarchical addressing properties
    for i in range(1, len(containing)):
        parent = containing[i]["place"]
        parent_addr = parent.get("address") or {}
        parent_level = _parse_admin_level(parent)
        parent_name = get_place_name(parent)

        if not best["address"].get("country") and parent_addr.get("country"):
            best["address"]["country"] = parent_addr["country"]

        # Admin Level 4 -> State/Region
        if not best["address"].get("state"):
            if parent_addr.get("state"):
                best["address"]["state"] = parent_addr["state"]
            elif parent_level == 4:
                best["address"]["state"] = parent_name

        # Admin Level 6 -> County/Prefecture
        if not best["address"].get("county"):
            if parent_addr.get("county"):
                best["address"]["county"] = parent_addr["county"]
            elif parent_level == 6:
                best["address"]["county"] = parent_name

        # Admin Level 8 -> City/Town/Sub-prefecture
        if not best["address"].get("city") and not best["address"].get("town") and not best["address"].get("village"):
            if parent_addr.get("city"):
                best["address"]["city"] = parent_addr["city"]
            elif parent_addr.get("town"):
                best["address"]["town"] = parent_addr["town"]
            elif parent_level == 8:
                best["address"]["city"] = parent_name

    # Fallback country
    if not best["address"].get("country"):
        best["address"]["country"] = (state.country_profile.get("meta") or {}).get("country_name", "Guinée")

    bbox = get_cached_bbox(best)
    origin_lat = bbox[0] if bbox else state.country_sw[0]
    origin_lon = bbox[2] if bbox else state.country_sw[1]
    return {
        "place": best,
        "originLat": origin_lat,
        "originLon": origin_lon,
        "bbox": bbox,
    }


# ── OGLAP result builder ───────────────────────────────────────────

def build_oglap_result(
    lat: float,
    lon: float,
    rev: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build full OGLAP address and LAP code from reverse result."""
    use_zone = rev and rev.get("place") and use_zone_grid_for_place(rev["place"])
    use_national = not use_zone

    if use_zone:
        origin_lat = rev["originLat"]
        origin_lon = rev["originLon"]
        admin_level_2 = get_admin_level_2_with_fallback(lat, lon, rev["place"])
        if not admin_level_2:
            return None
        admin_level_3 = get_admin_level_3_code_with_collision(rev["place"])
        address = rev["place"].get("address") or {}
        display_name = get_place_name(rev["place"])
        pcode_raw = (rev["place"].get("extratags") or {}).get("unocha:pcode")
        pcode = (
            [s.strip() for s in pcode_raw.split(";") if s.strip()]
            if isinstance(pcode_raw, str) and pcode_raw.strip()
            else []
        )
    else:
        origin_lat = state.country_sw[0]
        origin_lon = state.country_sw[1]
        admin_level_2 = get_admin_level_2_with_fallback(lat, lon, rev["place"] if rev else None)
        if not admin_level_2:
            return None
        admin_level_3 = None
        address = (rev["place"].get("address") or {}) if rev and rev.get("place") else {}
        display_name = get_place_name(rev.get("place") if rev else None)
        pcode = []

    lap = compute_lap(lat, lon, origin_lat, origin_lon, admin_level_2, admin_level_3, use_national)

    if use_national:
        address_parts = [
            f"{lap['macroblock']}-{lap['microspot']}",
            address.get("county") or address.get("state") or address.get("city") or address.get("town") or address.get("village"),
            address.get("country"),
        ]
    else:
        first = (
            f"{lap['macroblock']}-{lap['microspot']} {display_name}"
            if display_name != "Unknown"
            else f"{lap['macroblock']}-{lap['microspot']}"
        )
        address_parts = [
            first,
            address.get("county") or address.get("state") or address.get("city") or address.get("town") or address.get("village"),
            address.get("country"),
        ]

    # Remove None/empty and deduplicate preserving order
    seen: set[str] = set()
    unique_parts: list[str] = []
    for part in address_parts:
        if part and part not in seen:
            seen.add(part)
            unique_parts.append(part)
    human_address = ", ".join(unique_parts)

    return {
        "lapCode": lap["lapCode"],
        "country": lap["country"],
        "admin_level_2": lap["admin_level_2"],
        "admin_level_3": lap["admin_level_3"],
        "macroblock": lap["macroblock"],
        "microspot": lap["microspot"],
        "isNationalGrid": lap["isNationalGrid"],
        "displayName": display_name,
        "address": address,
        "humanAddress": human_address,
        "originLat": origin_lat,
        "originLon": origin_lon,
        "pcode": pcode,
    }


# ── LAP search index ───────────────────────────────────────────────

def build_lap_search_index() -> dict[str, dict[str, Any]]:
    """Build search index: key ``"{admin2_iso}_{zone_code}"`` -> first matching place."""
    if state.lap_search_index is not None:
        return state.lap_search_index

    state.lap_search_index = {}
    iso_to_assignment: dict[str, dict[Any, str]] = {}

    for place in state.places:
        iso = effective_admin_level_2_iso_for_place(place, skip_sampling=True)

        pid = place.get("place_id")
        code: str | None = state.oglap_zone_codes_by_id.get(pid) if pid is not None else None

        if not code:
            if iso not in iso_to_assignment:
                iso_to_assignment[iso] = build_admin_level_2_zone_assignments(iso)
            code = iso_to_assignment[iso].get(pid)

        if not code:
            continue
        key = f"{iso}_{code}"
        if key not in state.lap_search_index:
            state.lap_search_index[key] = place

    return state.lap_search_index

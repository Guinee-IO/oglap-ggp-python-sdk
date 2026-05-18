"""
Spatial lookups — reverse geocoding, admin-level resolution,
collision-aware zone assignment, LAP search index, and OGLAP result builder.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import box
from shapely.strtree import STRtree

from ._geo import (
    centroid_from_place,
    compute_area,
    get_cached_bbox,
    point_in_geometry,
)
from ._constants import COLLISION_SUFFIX_ALPHABET, MAX_ZONE_CODE_LENGTH
from ._grid import compute_lap, is_point_within_local_grid, meters_per_degree_lat, meters_per_degree_lon
from ._naming import (
    _parse_admin_level,
    get_place_zone_candidates,
    zone_code_from_name_and_type,
    get_type_prefix_for_zone,
    get_significant_tokens,
    name_key_from_tokens,
)
from ._state import state


# ── R-tree spatial index over place polygon bboxes ─────────────────

def build_places_rtree() -> None:
    """Build a static R-tree (shapely STRtree) over polygon bboxes.

    Antimeridian-crossing bboxes (``minLon > maxLon``) are split into two
    entries that both reference the same place — both halves can match a
    click. Mirrors the JS ``_buildPlacesRTree`` (Flatbush) implementation.
    Idempotent: safe to call multiple times; cleared by ``reset_loaded_data``.
    """
    state.places_rtree = None
    state.places_rtree_idx = None
    if not state.places:
        return

    geoms: list[Any] = []
    idx: list[int] = []
    for i, place in enumerate(state.places):
        geo = place.get("geojson") or {}
        if geo.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        bbox = get_cached_bbox(place)
        if not bbox:
            continue
        min_lat, max_lat, min_lon, max_lon = bbox
        if min_lon <= max_lon:
            geoms.append(box(min_lon, min_lat, max_lon, max_lat))
            idx.append(i)
        else:
            # Antimeridian-crossing bbox: split into [minLon, 180] and [-180, maxLon].
            geoms.append(box(min_lon, min_lat, 180.0, max_lat))
            idx.append(i)
            geoms.append(box(-180.0, min_lat, max_lon, max_lat))
            idx.append(i)

    if not geoms:
        return
    state.places_rtree = STRtree(geoms)
    state.places_rtree_idx = idx


def _bbox_contains(bbox: list[float], lat: float, lon: float) -> bool:
    """True iff a bbox ``[minLat, maxLat, minLon, maxLon]`` contains ``(lat, lon)``.

    Handles antimeridian-wrapped bboxes (``minLon > maxLon``).
    """
    if lat < bbox[0] or lat > bbox[1]:
        return False
    min_lon, max_lon = bbox[2], bbox[3]
    if min_lon <= max_lon:
        return min_lon <= lon <= max_lon
    return lon >= min_lon or lon <= max_lon


def candidate_place_indices(lon: float, lat: float) -> list[int]:
    """Return indices of places whose bbox contains ``(lon, lat)``.

    Uses the R-tree when built; falls back to a linear bbox scan otherwise
    (e.g. before ``load_oglap`` was called). Duplicates may appear when a
    place's bbox was split for antimeridian — callers must deduplicate.
    """
    if state.places_rtree is not None and state.places_rtree_idx is not None:
        try:
            hits = state.places_rtree.query(box(lon, lat, lon, lat))
        except Exception:
            hits = []
        idx_arr = state.places_rtree_idx
        out: list[int] = []
        for h in hits:
            # Shapely >=2 returns integer indices; <2 returns geometry objects.
            if hasattr(h, "geom_type"):
                # Geometry object — find its position via identity in stored geometries.
                for k, g in enumerate(state.places_rtree.geometries):
                    if g is h:
                        out.append(idx_arr[k])
                        break
            else:
                out.append(idx_arr[int(h)])
        return out

    # Fallback: linear bbox scan over all places.
    out: list[int] = []
    for i, place in enumerate(state.places):
        geo = place.get("geojson") or {}
        if geo.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        bbox = get_cached_bbox(place)
        if bbox and _bbox_contains(bbox, lat, lon):
            out.append(i)
    return out


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


def _place_id_sort_key(place: dict[str, Any]) -> tuple[int, float | str]:
    pid = place.get("place_id", "")
    try:
        num = float(pid)
        if math.isfinite(num):
            return (0, num)
    except (TypeError, ValueError):
        pass
    return (1, str(pid))


def _get_explicit_zone_code_for_place(place: dict[str, Any] | None) -> str | None:
    if not place:
        return None
    pid = place.get("place_id")
    if pid is None:
        return None
    if pid in state.oglap_zone_codes_by_id:
        return state.oglap_zone_codes_by_id[pid]
    return state.oglap_zone_codes_by_id.get(str(pid))


def _base36(n: int) -> str:
    if n == 0:
        return "0"
    alphabet = COLLISION_SUFFIX_ALPHABET
    out = ""
    while n > 0:
        n, rem = divmod(n, 36)
        out = alphabet[rem] + out
    return out


def _next_collision_code(prefix: str, used: set[str], counters: dict[str, int]) -> str:
    nxt = counters.get(prefix, 0)
    max_suffix_len = max(1, MAX_ZONE_CODE_LENGTH - len(prefix))
    hard_limit = 36 ** max_suffix_len
    while True:
        if nxt >= hard_limit:
            raise RuntimeError(
                f'OGLAP collision overflow: exhausted {hard_limit} suffixes for zone prefix "{prefix}".'
            )
        suffix = COLLISION_SUFFIX_ALPHABET[nxt] if nxt < len(COLLISION_SUFFIX_ALPHABET) else _base36(nxt)
        nxt += 1
        candidate = prefix + suffix
        if len(candidate) > MAX_ZONE_CODE_LENGTH:
            raise RuntimeError(f'OGLAP collision candidate "{candidate}" exceeds MAX_ZONE_CODE_LENGTH ({MAX_ZONE_CODE_LENGTH}).')
        if candidate not in used:
            counters[prefix] = nxt
            return candidate


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
    if state.admin_level_4_places_cache is None:
        state.admin_level_4_places_cache = {}
        for place in state.places:
            if _parse_admin_level(place) != 4:
                continue
            iso = get_admin_level_2_iso_from_address(place.get("address") or {})
            if iso and place.get("geojson"):
                state.admin_level_4_places_cache[id(place)] = iso

    # Walk R-tree candidates only — admin_level 4 polygons that may contain the point.
    candidates = candidate_place_indices(lon, lat)
    seen: set[int] = set()
    for i in candidates:
        if i in seen:
            continue
        seen.add(i)
        place = state.places[i]
        iso = state.admin_level_4_places_cache.get(id(place))
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
    m_per_lat = meters_per_degree_lat(lat)
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
    if _get_explicit_zone_code_for_place(place):
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
) -> str | None:
    pid = place.get("place_id")
    cacheable = pid is not None and skip_sampling
    if cacheable and pid in state.place_effective_iso_cache:
        return state.place_effective_iso_cache[pid]
    cen = centroid_from_place(place)
    if cen:
        iso = get_admin_level_2_iso_with_fallback(cen[0], cen[1], place, skip_sampling)
    else:
        iso = get_admin_level_2_iso_from_address(place.get("address") or {}) or None
    if cacheable:
        state.place_effective_iso_cache[pid] = iso
    return iso


# ── Collision-aware zone assignments ────────────────────────────────

def build_admin_level_2_zone_assignments(admin_level_2_iso: str) -> dict[Any, str]:
    """Deterministic zone-code assignment per ADMIN_LEVEL_2 (collision avoidance)."""
    iso_key = admin_level_2_iso or ""
    if iso_key in state.admin_level_2_assignment_cache:
        return state.admin_level_2_assignment_cache[iso_key]
    in_admin = [
        p for p in state.places
        if effective_admin_level_2_iso_for_place(p, skip_sampling=True) == iso_key
    ]
    sorted_places = sorted(in_admin, key=_place_id_sort_key)

    used: set[str] = set()
    suffix_count_by_base: dict[str, int] = {}
    assignment: dict[Any, str] = {}

    for code in state.oglap_explicit_zone_codes_by_region.get(iso_key, set()):
        used.add(code)

    for place in sorted_places:
        explicit_code = _get_explicit_zone_code_for_place(place)
        if not explicit_code:
            continue
        used.add(explicit_code)
        assignment[place.get("place_id")] = explicit_code

    for place in sorted_places:
        if place.get("place_id") in assignment:
            continue
        candidates = get_place_zone_candidates(place)
        base_code = candidates["baseCode"]
        fallback_code = candidates["fallbackCode"]
        prefix3 = base_code[:3]
        final_code: str | None = None

        if base_code not in used:
            final_code = base_code
        elif fallback_code and fallback_code != base_code and fallback_code not in used:
            final_code = fallback_code
        else:
            final_code = _next_collision_code(prefix3, used, suffix_count_by_base)

        used.add(final_code)
        assignment[place.get("place_id")] = final_code

    state.admin_level_2_assignment_cache[iso_key] = assignment
    return assignment


def get_admin_level_3_code_with_collision(place: dict[str, Any] | None) -> str | None:
    """ADMIN_LEVEL_3 zone code respecting manual overrides then collision resolution."""
    if not place:
        return None
    pid = place.get("place_id")
    # Use explicit zone code from localities naming data if present
    explicit_code = _get_explicit_zone_code_for_place(place)
    if explicit_code:
        return explicit_code
    admin_level_2_iso = effective_admin_level_2_iso_for_place(place, skip_sampling=True)
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

    # Candidate set from R-tree; deduplicate (antimeridian-split bboxes can produce duplicates).
    candidate_idx = candidate_place_indices(lon, lat)
    seen_idx: set[int] = set()
    for i in candidate_idx:
        if i in seen_idx:
            continue
        seen_idx.add(i)
        place = state.places[i]
        geo = place.get("geojson")
        if not geo:
            continue
        geo_type = geo.get("type")
        if geo_type not in ("Polygon", "MultiPolygon"):
            continue
        if not point_in_geometry(lon, lat, geo):
            continue

        area_key = id(place)
        cached_area = state.place_area_cache.get(area_key)
        if cached_area and cached_area[0] is place:
            computed_area = cached_area[1]
        else:
            try:
                computed_area = compute_area(geo)
                state.place_area_cache[area_key] = (place, computed_area)
            except Exception:
                continue
        containing.append({"place": place, "area": computed_area})

    if not containing:
        return None

    containing.sort(key=lambda x: (x["area"], _place_id_sort_key(x["place"])))

    # Best (smallest) feature
    best = containing[0]["place"]
    enriched = dict(best.get("address") or {})

    # Bubble up missing hierarchical addressing properties
    for i in range(1, len(containing)):
        parent = containing[i]["place"]
        parent_addr = parent.get("address") or {}
        parent_level = _parse_admin_level(parent)
        parent_name = get_place_name(parent)

        if not enriched.get("country") and parent_addr.get("country"):
            enriched["country"] = parent_addr["country"]

        # Admin Level 4 -> State/Region
        if not enriched.get("state"):
            if parent_addr.get("state"):
                enriched["state"] = parent_addr["state"]
            elif parent_level == 4:
                enriched["state"] = parent_name

        # Admin Level 6 -> County/Prefecture
        if not enriched.get("county"):
            if parent_addr.get("county"):
                enriched["county"] = parent_addr["county"]
            elif parent_level == 6:
                enriched["county"] = parent_name

        # Admin Level 8 -> City/Town/Sub-prefecture
        if not enriched.get("city") and not enriched.get("town") and not enriched.get("village"):
            if parent_addr.get("city"):
                enriched["city"] = parent_addr["city"]
            elif parent_addr.get("town"):
                enriched["town"] = parent_addr["town"]
            elif parent_level == 8:
                enriched["city"] = parent_name

    # Fallback country
    if not enriched.get("country"):
        enriched["country"] = (state.country_profile.get("meta") or {}).get("country_name", "Guinée")

    bbox = get_cached_bbox(best)
    origin_lat = bbox[0] if bbox else state.country_sw[0]
    origin_lon = bbox[2] if bbox else state.country_sw[1]
    return {
        "place": best,
        "enrichedAddress": enriched,
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
    prefers_zone = bool(rev and rev.get("place") and use_zone_grid_for_place(rev["place"]))
    zone_origin_lat = rev.get("originLat") if rev else None
    zone_origin_lon = rev.get("originLon") if rev else None
    use_zone = bool(
        prefers_zone
        and isinstance(zone_origin_lat, (int, float))
        and isinstance(zone_origin_lon, (int, float))
        and math.isfinite(zone_origin_lat)
        and math.isfinite(zone_origin_lon)
        and is_point_within_local_grid(lat, lon, zone_origin_lat, zone_origin_lon)
    )
    use_national = not use_zone

    if use_zone:
        origin_lat = rev["originLat"]
        origin_lon = rev["originLon"]
        place_iso = effective_admin_level_2_iso_for_place(rev["place"], skip_sampling=True)
        admin_level_2 = state.oglap_country_regions.get(place_iso) if place_iso else None
        if not admin_level_2:
            admin_level_2 = get_admin_level_2_with_fallback(lat, lon, rev["place"])
        if not admin_level_2:
            return None
        admin_level_3 = get_admin_level_3_code_with_collision(rev["place"])
        address = rev.get("enrichedAddress") or rev["place"].get("address") or {}
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
        address = rev.get("enrichedAddress") if rev else None
        if address is None:
            address = (rev["place"].get("address") or {}) if rev and rev.get("place") else {}
        display_name = get_place_name(rev.get("place") if rev else None)
        pcode = []

    lap = compute_lap(lat, lon, origin_lat, origin_lon, admin_level_2, admin_level_3, use_national)
    if not lap:
        return None

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
    sorted_places = sorted(state.places, key=_place_id_sort_key)

    for place in sorted_places:
        iso = effective_admin_level_2_iso_for_place(place, skip_sampling=True)
        code = _get_explicit_zone_code_for_place(place)
        if not iso or not code:
            continue
        key = f"{iso}_{code}"
        if key not in state.lap_search_index:
            state.lap_search_index[key] = place

    for place in sorted_places:
        if _get_explicit_zone_code_for_place(place):
            continue
        iso = effective_admin_level_2_iso_for_place(place, skip_sampling=True)

        pid = place.get("place_id")
        if iso not in iso_to_assignment:
            iso_to_assignment[iso] = build_admin_level_2_zone_assignments(iso)
        code = iso_to_assignment[iso].get(pid)

        if not code:
            continue
        key = f"{iso}_{code}"
        if key not in state.lap_search_index:
            state.lap_search_index[key] = place

    return state.lap_search_index

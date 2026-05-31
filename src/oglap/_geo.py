"""
Geometry helpers — bounding boxes, centroids, point-in-polygon, area.

Uses Shapely for spatial predicates.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Point, shape

from ._grid import wrap_lon
from ._state import state


# ── Bounding box ────────────────────────────────────────────────────

def bbox_from_geometry(geometry: dict[str, Any] | None) -> list[float] | None:
    """Compute ``[minLat, maxLat, minLon, maxLon]`` from a GeoJSON geometry dict."""
    if not geometry or not geometry.get("coordinates"):
        return None

    coords = geometry["coordinates"]
    geo_type = geometry.get("type")

    min_lat = math.inf
    max_lat = -math.inf
    raw_min = math.inf
    raw_max = -math.inf
    lons: list[float] = []

    def add(lon: float, lat: float) -> None:
        nonlocal min_lat, max_lat, raw_min, raw_max
        if not math.isfinite(lon) or not math.isfinite(lat):
            return
        if lat < min_lat:
            min_lat = lat
        if lat > max_lat:
            max_lat = lat
        wrapped = wrap_lon(lon)
        if wrapped < raw_min:
            raw_min = wrapped
        if wrapped > raw_max:
            raw_max = wrapped
        lons.append(wrapped)

    def add_coord(p: Any) -> None:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return
        try:
            add(float(p[0]), float(p[1]))
        except (TypeError, ValueError):
            return

    if geo_type == "Point":
        add_coord(coords)
    elif geo_type == "Polygon" and isinstance(coords, (list, tuple)):
        for ring in coords:
            if not isinstance(ring, (list, tuple)):
                continue
            for p in ring:
                add_coord(p)
    elif geo_type == "MultiPolygon" and isinstance(coords, (list, tuple)):
        for poly in coords:
            if not isinstance(poly, (list, tuple)):
                continue
            for ring in poly:
                if not isinstance(ring, (list, tuple)):
                    continue
                for p in ring:
                    add_coord(p)

    if min_lat == math.inf:
        return None

    raw_span = raw_max - raw_min
    unique_lons = sorted(set(lons))
    if len(unique_lons) > 1:
        max_gap = -1.0
        max_gap_idx = 0
        for i, lon in enumerate(unique_lons):
            nxt = (i + 1) % len(unique_lons)
            gap = (unique_lons[0] + 360) - lon if nxt == 0 else unique_lons[nxt] - lon
            if gap > max_gap:
                max_gap = gap
                max_gap_idx = i
        compact_span = 360 - max_gap
        arc_start = unique_lons[(max_gap_idx + 1) % len(unique_lons)]
        arc_end = unique_lons[max_gap_idx]
        if compact_span < raw_span and compact_span <= 180:
            min_lon = arc_start
            max_lon = arc_end
        else:
            min_lon = raw_min
            max_lon = raw_max
    else:
        min_lon = raw_min
        max_lon = raw_max
    return [min_lat, max_lat, min_lon, max_lon]


def centroid_from_bbox(bbox: list[float] | None) -> list[float] | None:
    """Centroid ``[lat, lon]`` from a bbox ``[minLat, maxLat, minLon, maxLon]``."""
    if not bbox or len(bbox) < 4:
        return None
    lat = (bbox[0] + bbox[1]) / 2
    if bbox[2] <= bbox[3]:
        lon = (bbox[2] + bbox[3]) / 2
    else:
        lon = (bbox[2] + bbox[3] + 360) / 2
        if lon > 180:
            lon -= 360
    return [lat, lon]


# ── Cached bbox / centroid per place ────────────────────────────────

def get_cached_bbox(place: dict[str, Any]) -> list[float] | None:
    """Return bbox for a place without mutating the caller-provided dict."""
    if not place or not place.get("geojson"):
        return None
    key = id(place)
    cached = state.place_bbox_cache.get(key)
    if cached and cached[0] is place:
        return cached[1]
    bbox = bbox_from_geometry(place["geojson"])
    state.place_bbox_cache[key] = (place, bbox)
    return bbox


def centroid_from_place(place: dict[str, Any]) -> list[float] | None:
    """Return ``[lat, lon]`` centroid for a place (from its bbox)."""
    bbox = get_cached_bbox(place)
    return centroid_from_bbox(bbox) if bbox else None


# ── Ring closure (Shapely / Turf requirement) ───────────────────────

def _close_ring(ring: list[list[float]]) -> list[list[float]]:
    if not ring or len(ring) < 3:
        return ring
    first = ring[0]
    last = ring[-1]
    if first[0] != last[0] or first[1] != last[1]:
        return ring + [[first[0], first[1]]]
    return ring


def close_rings(geometry: dict[str, Any]) -> dict[str, Any]:
    """Ensure each polygon ring is closed (first coord == last coord)."""
    if not geometry or not geometry.get("coordinates"):
        return geometry
    geo_type = geometry.get("type")
    if geo_type == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [_close_ring(ring) for ring in geometry["coordinates"]],
        }
    if geo_type == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [_close_ring(ring) for ring in poly]
                for poly in geometry["coordinates"]
            ],
        }
    return geometry


# ── Cached closed-polygon shapely object ────────────────────────────

def _get_closed_shape(geometry: dict[str, Any] | None) -> Any:
    """Return a cached shapely geometry for a GeoJSON polygon/multipolygon.

    Mirrors the JS ``_getClosedPolyFromGeometry`` helper: ensures rings are
    closed and the shapely shape is built only once per geometry object.
    Cached on ``state.geometry_shape_cache`` keyed by ``id(geometry)`` so the
    caller's GeoJSON dict is never mutated.
    """
    if not geometry:
        return None
    geo_type = geometry.get("type")
    if geo_type not in ("Polygon", "MultiPolygon"):
        return None
    key = id(geometry)
    cached = state.geometry_shape_cache.get(key)
    if cached and cached[0] is geometry:
        return cached[1]
    try:
        closed = close_rings(geometry)
        poly = shape(closed)
    except Exception:
        poly = None
    state.geometry_shape_cache[key] = (geometry, poly)
    return poly


# ── Point-in-geometry ───────────────────────────────────────────────

def point_in_geometry(lon: float, lat: float, geometry: dict[str, Any] | None) -> bool:
    """Check if ``(lon, lat)`` falls inside a GeoJSON Polygon / MultiPolygon."""
    poly = _get_closed_shape(geometry)
    if poly is None:
        return False
    try:
        return poly.covers(Point(lon, lat))
    except Exception:
        return False


# ── Area (for sorting by smallest containing polygon) ───────────────

_WGS84_RADIUS = 6_378_137.0


def _ring_area(ring: Any) -> float:
    """Spherical ring area matching Turf/Dart ordering semantics."""
    if not isinstance(ring, (list, tuple)) or len(ring) < 3:
        return 0.0
    total = 0.0
    try:
        for i, p1 in enumerate(ring):
            p2 = ring[(i + 1) % len(ring)]
            lon1, lat1 = float(p1[0]), float(p1[1])
            lon2, lat2 = float(p2[0]), float(p2[1])
            total += math.radians(lon2 - lon1) * (
                2.0 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))
            )
    except (IndexError, TypeError, ValueError):
        return 0.0
    return abs(total * _WGS84_RADIUS * _WGS84_RADIUS / 2.0)


def _polygon_area(coords: Any) -> float:
    if not isinstance(coords, (list, tuple)) or not coords:
        return 0.0
    return _ring_area(coords[0]) - sum(_ring_area(ring) for ring in coords[1:])


def compute_area(geometry: dict[str, Any]) -> float:
    """Spherical GeoJSON area used to choose the smallest containing polygon.

    Node uses Turf area and Dart uses the equivalent spherical formula. Matching
    that model here prevents Python from choosing a different zone origin when
    overlapping polygons have a different planar-versus-spherical ordering.
    """
    if not isinstance(geometry, dict):
        return 0.0
    coords = geometry.get("coordinates")
    if geometry.get("type") == "Polygon":
        return _polygon_area(coords)
    if geometry.get("type") == "MultiPolygon" and isinstance(coords, (list, tuple)):
        return sum(_polygon_area(poly) for poly in coords)
    return 0.0

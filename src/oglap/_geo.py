"""
Geometry helpers — bounding boxes, centroids, point-in-polygon, area.

Uses Shapely for spatial predicates.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Point, shape


# ── Bounding box ────────────────────────────────────────────────────

def bbox_from_geometry(geometry: dict[str, Any] | None) -> list[float] | None:
    """Compute ``[minLat, maxLat, minLon, maxLon]`` from a GeoJSON geometry dict."""
    if not geometry or not geometry.get("coordinates"):
        return None

    coords = geometry["coordinates"]
    geo_type = geometry.get("type")

    min_lat = math.inf
    max_lat = -math.inf
    min_lon = math.inf
    max_lon = -math.inf

    def add(lon: float, lat: float) -> None:
        nonlocal min_lat, max_lat, min_lon, max_lon
        if lat < min_lat:
            min_lat = lat
        if lat > max_lat:
            max_lat = lat
        if lon < min_lon:
            min_lon = lon
        if lon > max_lon:
            max_lon = lon

    if geo_type == "Point":
        add(coords[0], coords[1])
    elif geo_type == "Polygon":
        for ring in coords:
            for p in ring:
                add(p[0], p[1])
    elif geo_type == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                for p in ring:
                    add(p[0], p[1])

    if min_lat == math.inf:
        return None
    return [min_lat, max_lat, min_lon, max_lon]


def centroid_from_bbox(bbox: list[float] | None) -> list[float] | None:
    """Centroid ``[lat, lon]`` from a bbox ``[minLat, maxLat, minLon, maxLon]``."""
    if not bbox or len(bbox) < 4:
        return None
    return [(bbox[0] + bbox[1]) / 2, (bbox[2] + bbox[3]) / 2]


# ── Cached bbox / centroid per place ────────────────────────────────

def get_cached_bbox(place: dict[str, Any]) -> list[float] | None:
    """Return bbox for a place, caching in ``place['_computed_bbox']``."""
    if not place or not place.get("geojson"):
        return None
    cached = place.get("_computed_bbox")
    if cached is not None:
        return cached
    bbox = bbox_from_geometry(place["geojson"])
    place["_computed_bbox"] = bbox
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


# ── Point-in-geometry ───────────────────────────────────────────────

def point_in_geometry(lon: float, lat: float, geometry: dict[str, Any] | None) -> bool:
    """Check if ``(lon, lat)`` falls inside a GeoJSON Polygon / MultiPolygon."""
    if not geometry:
        return False
    geo_type = geometry.get("type")
    if geo_type not in ("Polygon", "MultiPolygon"):
        return False
    closed = close_rings(geometry)
    try:
        poly = shape(closed)
        return poly.contains(Point(lon, lat))
    except Exception:
        return False


# ── Area (for sorting by smallest containing polygon) ───────────────

def compute_area(geometry: dict[str, Any]) -> float:
    """Planar area of a GeoJSON geometry (in square-degrees).

    This is only used for *relative* ordering (smallest containing polygon),
    so planar area in degree-space gives the same sort order as geodesic area.
    """
    closed = close_rings(geometry)
    try:
        return shape(closed).area
    except Exception:
        return 0.0

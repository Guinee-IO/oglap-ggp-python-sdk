"""
OGLAP Python SDK — Offline Grid Location Addressing Protocol.

Converts GPS coordinates into human-readable, deterministic alphanumeric
OGLAP codes for Guinea (GN) and vice versa.
"""

from __future__ import annotations

from .engine import (
    bbox_from_geometry,
    centroid_from_bbox,
    check_oglap,
    coordinates_to_lap,
    get_country_code,
    get_country_profile,
    get_country_sw,
    get_oglap_places,
    get_oglap_prefectures,
    get_package_version,
    get_place_by_lap_code,
    init_oglap,
    lap_to_coordinates,
    load_oglap,
    parse_lap_code,
    validate_lap_code,
)

__all__ = [
    "init_oglap",
    "load_oglap",
    "check_oglap",
    "get_package_version",
    "get_country_profile",
    "get_country_code",
    "get_country_sw",
    "get_oglap_prefectures",
    "get_oglap_places",
    "parse_lap_code",
    "validate_lap_code",
    "get_place_by_lap_code",
    "lap_to_coordinates",
    "coordinates_to_lap",
    "bbox_from_geometry",
    "centroid_from_bbox",
]

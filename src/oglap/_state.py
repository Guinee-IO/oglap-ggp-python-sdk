"""
OGLAP SDK mutable state — singleton that mirrors JS module-level ``let`` variables.
"""

from __future__ import annotations

from typing import Any


class _State:
    """Singleton holding all mutable engine state."""

    def __init__(self) -> None:
        self.reset()

    # ── Reset to pristine (pre-init) state ──────────────────────────
    def reset(self) -> None:
        # Initialization
        self.initialized: bool = False
        self.init_report: dict[str, Any] | None = None

        # Profile / country
        self.country_profile: dict[str, Any] = {}
        self.country_code: str = "GN"

        # Region / prefecture maps
        self.oglap_country_regions: dict[str, str] = {}
        self.oglap_country_regions_reverse: dict[str, str] = {}
        self.oglap_country_prefectures: dict[str, str] = {}

        # Zone codes by place_id
        self.oglap_zone_codes_by_id: dict[str | int, str] = {}
        self.oglap_explicit_zone_codes_by_region: dict[str, set[str]] = {}

        # Naming
        self.zone_type_prefix_default: str = "Z"
        self.zone_type_prefix: dict[str, str] = {}
        self.ggp_stopwords: set[str] = set()
        self.ggp_pad_char: str = "X"

        # Geography
        self.country_sw: list[float] = [0.0, 0.0]
        self.country_bounds: dict[str, list[float]] = {
            "sw": [7.19, -15.37],
            "ne": [12.68, -7.64],
        }
        self.country_border_geojson: dict[str, Any] | None = None
        self.meters_per_degree_lat: float = 111_320.0
        self.distance_mode: str = "flat"
        self.country_crosses_antimeridian: bool = False

        # Places data
        self.places: list[dict[str, Any]] = []
        self.lap_search_index: dict[str, dict[str, Any]] | None = None
        self.upper_admin_letter_cache: dict[Any, str] = {}
        self.admin_level_6_places_cache: list[dict[str, Any]] | None = None
        self.admin_level_4_places_cache: dict[int, str] | None = None
        self.admin_level_2_assignment_cache: dict[str, dict[Any, str]] = {}
        self.place_effective_iso_cache: dict[Any, str | None] = {}
        self.place_bbox_cache: dict[int, tuple[dict[str, Any], list[float] | None]] = {}
        self.place_area_cache: dict[int, tuple[dict[str, Any], float]] = {}
        # Cache for closed-polygon shapely objects (id(geometry) -> (geometry, shape))
        self.geometry_shape_cache: dict[int, tuple[dict[str, Any], Any]] = {}

        # Static R-tree over polygon bboxes for fast spatial candidate lookup.
        # places_rtree: shapely STRtree built from bbox boxes.
        # places_rtree_idx: parallel list mapping rtree node ordinal -> places index.
        self.places_rtree: Any = None
        self.places_rtree_idx: list[int] | None = None

    def reset_loaded_data(self, *, clear_places: bool = True) -> None:
        """Clear loaded places and derived spatial/addressing caches."""
        self.lap_search_index = None
        self.upper_admin_letter_cache.clear()
        self.admin_level_6_places_cache = None
        self.admin_level_4_places_cache = None
        self.admin_level_2_assignment_cache.clear()
        self.place_effective_iso_cache.clear()
        self.place_bbox_cache.clear()
        self.place_area_cache.clear()
        self.geometry_shape_cache.clear()
        self.places_rtree = None
        self.places_rtree_idx = None
        self.country_border_geojson = None
        if clear_places:
            self.places = []


# Module-level singleton
state = _State()

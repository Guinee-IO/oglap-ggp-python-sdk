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

        # Places data
        self.places: list[dict[str, Any]] = []
        self.lap_search_index: dict[str, dict[str, Any]] | None = None
        self.upper_admin_letter_cache: dict[Any, str] = {}
        self.admin_level_6_places_cache: list[dict[str, Any]] | None = None


# Module-level singleton
state = _State()

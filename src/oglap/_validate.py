"""
Init-time validation — validates profile + localities naming and applies engine state.
"""

from __future__ import annotations

import math
import re
from typing import Any

from ._constants import PACKAGE_VERSION
from ._semver import satisfies_caret
from ._state import state


def _as_dict(value: Any) -> dict[str, Any]:
    """Return a mapping-shaped config value without trusting decoded JSON."""
    return value if isinstance(value, dict) else {}


def _map_from_code_table(table: dict[str, Any] | None) -> dict[str, str]:
    """Create a flat ``{iso: oglap_code}`` map from a nested profile table."""
    if not table or not isinstance(table, dict):
        return {}
    result: dict[str, str] = {}
    for iso, entry in table.items():
        code = entry.get("oglap_code") if isinstance(entry, dict) else None
        if isinstance(code, str) and code.strip():
            result[iso] = code
    return result


def validate_and_apply(
    profile: Any,
    localities_naming: Any,
    prior_checks: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Validate profile + localities naming, apply engine state if valid.

    Returns ``{ok, countryCode, countryName, bounds, checks, error}``.
    """
    checks: list[dict[str, str]] = list(prior_checks) if prior_checks else []
    fatal = False

    def pass_(id_: str, msg: str) -> None:
        checks.append({"id": id_, "status": "pass", "message": msg})

    def warn(id_: str, msg: str) -> None:
        checks.append({"id": id_, "status": "warn", "message": msg})

    def fail(id_: str, msg: str) -> None:
        nonlocal fatal
        checks.append({"id": id_, "status": "fail", "message": msg})
        fatal = True

    # ── 1. Profile presence & schema ──────────────────────────────
    if not profile or not isinstance(profile, dict):
        fail("profile.present", "Country profile is missing or not a valid object.")
        return {"ok": False, "countryCode": None, "countryName": None, "bounds": None, "checks": checks, "error": "Country profile is missing."}
    pass_("profile.present", "Country profile loaded.")

    profile_schema = profile.get("schema_id")
    if profile_schema != "oglap.country_profile.v2":
        _got = profile_schema or "(none)"
        fail("profile.schema", 'Expected schema "oglap.country_profile.v2", got "%s".' % _got)
    else:
        pass_("profile.schema", f"Profile schema: {profile_schema}")

    # ── 2. Profile required fields ────────────────────────────────
    meta_raw = profile.get("meta")
    meta = _as_dict(meta_raw)
    if meta_raw is not None and not isinstance(meta_raw, dict):
        fail("profile.meta", "Profile meta must be a valid object.")
    if not meta.get("country_oglap_code") and not meta.get("iso_alpha_2"):
        fail("profile.meta.country_code", "Profile meta missing both country_oglap_code and iso_alpha_2.")
    else:
        _cc = meta.get("country_oglap_code") or meta.get("iso_alpha_2")
        pass_("profile.meta.country_code", "Country code: %s" % _cc)

    extent_raw = profile.get("country_extent")
    extent = _as_dict(extent_raw)
    if extent_raw is not None and not isinstance(extent_raw, dict):
        fail("profile.country_extent", "Profile country_extent must be a valid object.")
    if not extent.get("country_sw") or not extent.get("country_bounds"):
        fail("profile.country_extent", "Profile missing country_extent (country_sw or country_bounds).")
    else:
        pass_("profile.country_extent", "Country extent defined.")

    grid_settings_raw = profile.get("grid_settings")
    grid_settings = _as_dict(grid_settings_raw)
    if not grid_settings:
        fail("profile.grid_settings", "Profile missing grid_settings section.")
    else:
        pass_("profile.grid_settings", "Grid settings present.")

    zone_naming_raw = profile.get("zone_naming")
    zone_naming = _as_dict(zone_naming_raw)
    if zone_naming_raw is not None and not isinstance(zone_naming_raw, dict):
        fail("profile.zone_naming", "Profile zone_naming must be a valid object.")
    type_prefix_map = zone_naming.get("type_prefix_map")
    if not isinstance(type_prefix_map, dict) or not type_prefix_map:
        fail("profile.zone_naming", "Profile missing zone_naming.type_prefix_map.")
    else:
        _n = len(zone_naming["type_prefix_map"])
        pass_("profile.zone_naming", "Zone naming rules loaded (%d type prefixes)." % _n)

    # ── 3. Package version compatibility ──────────────────────────
    compat_raw = profile.get("compatibility")
    compat = _as_dict(compat_raw) if compat_raw is not None else None
    if compat_raw is not None and not isinstance(compat_raw, dict):
        fail("profile.compatibility", "Profile compatibility must be a valid object.")
    if not compat:
        warn("profile.compatibility", "Profile has no compatibility section \u2014 skipping version checks.")
    else:
        range_str = compat.get("oglap_package_range")
        if not range_str or not isinstance(range_str, str):
            warn("compat.package_range", "No oglap_package_range specified in profile \u2014 skipping package version check.")
        else:
            range_base = range_str.lstrip("^")
            if satisfies_caret(PACKAGE_VERSION, range_base):
                pass_("compat.package_range", 'Package v%s satisfies required range "%s".' % (PACKAGE_VERSION, range_str))
            else:
                fail("compat.package_range", 'Package v%s does NOT satisfy required range "%s". Update the OGLAP package or use a compatible profile.' % (PACKAGE_VERSION, range_str))

    # ── 4. Localities naming presence & schema ────────────────────
    if not localities_naming or not isinstance(localities_naming, dict):
        fail("localities.present", "Localities naming data is missing or not a valid object.")
        return {"ok": False, "countryCode": None, "countryName": None, "bounds": None, "checks": checks, "error": "Localities naming data is missing."}
    pass_("localities.present", "Localities naming data loaded.")

    loc_schema = localities_naming.get("schema_id")
    if loc_schema != "oglap.localities_naming.v1":
        _got_schema = loc_schema or "(none)"
        fail("localities.schema", 'Expected localities schema "oglap.localities_naming.v1", got "%s".' % _got_schema)
    else:
        pass_("localities.schema", f"Localities schema: {loc_schema}")

    def _localities_table(name: str) -> dict[str, Any]:
        raw = localities_naming.get(name)
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            fail(f"localities.{name}.schema", f"Localities {name} must be a valid object.")
            return {}
        return raw

    level_4_regions = _localities_table("level_4_regions")
    level_6_prefectures = _localities_table("level_6_prefectures")
    level_8_sous_prefectures = _localities_table("level_8_sous_prefectures")
    level_9_villages = _localities_table("level_9_villages")
    level_10_quartiers = _localities_table("level_10_quartiers")

    # ── 5. Country code alignment ─────────────────────────────────
    profile_country = meta.get("country_oglap_code") or meta.get("iso_alpha_2")
    loc_country = localities_naming.get("country")
    if profile_country and loc_country and profile_country != loc_country:
        fail("compat.country_match", 'Country mismatch: profile="%s", localities="%s".' % (profile_country, loc_country))
    elif profile_country and loc_country:
        pass_("compat.country_match", 'Country codes match: "%s".' % profile_country)

    # ── 6. Dataset version compatibility ──────────────────────────
    dataset_versions = (compat or {}).get("dataset_versions")
    loc_generated_at = localities_naming.get("generated_at")
    if not dataset_versions or not isinstance(dataset_versions, list) or len(dataset_versions) == 0:
        warn("compat.dataset_version", "Profile has no dataset_versions list \u2014 skipping dataset compatibility check.")
    elif not loc_generated_at:
        fail("compat.dataset_version", "Localities naming has no generated_at timestamp \u2014 cannot verify dataset compatibility.")
    elif loc_generated_at not in dataset_versions:
        _versions = ", ".join(str(v) for v in dataset_versions)
        fail("compat.dataset_version", 'Localities naming timestamp "%s" is not in profile\'s compatible dataset_versions [%s].' % (loc_generated_at, _versions))
    else:
        pass_("compat.dataset_version", 'Localities naming dataset version "%s" is compatible with profile.' % loc_generated_at)

    # ── 7. Localities naming source ───────────────────────────────
    loc_source = localities_naming.get("source")
    if not loc_source:
        warn("localities.source", "Localities naming has no source field \u2014 cannot verify which gn_full database was used.")
    else:
        pass_("localities.source", 'Localities naming was generated from source: "%s".' % loc_source)

    # ── 8. Structural check (admin levels) ────────────────────────
    has_l4 = bool(level_4_regions)
    has_l6 = bool(level_6_prefectures)
    has_zones = (
        bool(level_8_sous_prefectures)
        or bool(level_9_villages)
        or bool(level_10_quartiers)
    )
    if not has_l4:
        fail("localities.level_4", "Localities naming has no level_4_regions entries \u2014 regions cannot be resolved.")
    else:
        pass_("localities.level_4", "Level 4 regions: %d entries." % len(level_4_regions))
    if not has_l6:
        warn("localities.level_6", "Localities naming has no level_6_prefectures \u2014 prefecture resolution will use fallbacks.")
    else:
        pass_("localities.level_6", "Level 6 prefectures: %d entries." % len(level_6_prefectures))
    if not has_zones:
        warn("localities.zones", "Localities naming has no zone entries (levels 8/9/10) \u2014 local grid addressing will be unavailable.")
    else:
        count = (
            len(level_8_sous_prefectures)
            + len(level_9_villages)
            + len(level_10_quartiers)
        )
        pass_("localities.zones", f"Zone entries (levels 8/9/10): {count} total.")

    # Explicit localities naming zone codes are authoritative. They must be
    # unique within a declared parent region so local LAPs decode predictably.
    explicit_by_region: dict[str, list[dict[str, Any]]] = {}
    explicit_zone_count = 0
    missing_explicit_region = 0
    zone_code_re = re.compile(r"^[A-Z0-9]{1,8}$")
    for table in (
        level_8_sous_prefectures,
        level_9_villages,
        level_10_quartiers,
    ):
        for entry in table.values():
            if not isinstance(entry, dict):
                continue
            raw_code = entry.get("oglap_code")
            code = raw_code.strip().upper() if isinstance(raw_code, str) else ""
            if not code:
                continue
            explicit_zone_count += 1
            if not zone_code_re.match(code):
                fail("localities.zone_code.format", f'Invalid explicit zone code "{raw_code}" for place_id={entry.get("place_id", "(unknown)")}. Codes must be 1-8 uppercase letters/digits.')
                continue
            region_iso = entry.get("parent_region_iso")
            if not region_iso:
                missing_explicit_region += 1
                continue
            key = f"{region_iso}_{code}"
            explicit_by_region.setdefault(key, []).append(entry)

    explicit_collisions = [(key, entries) for key, entries in explicit_by_region.items() if len(entries) > 1]
    if explicit_collisions:
        key, entries = explicit_collisions[0]
        ids = ", ".join(str(e.get("place_id", "(unknown)")) for e in entries)
        fail("localities.zone_code.unique", f"Duplicate explicit zone code in parent region ({key}): place_ids {ids}. Explicit zone codes must be unique within an ADMIN_LEVEL_2 region.")
    elif explicit_zone_count > 0:
        pass_("localities.zone_code.unique", f"No duplicate explicit zone codes found within declared parent regions ({explicit_zone_count} entries scanned).")
    if missing_explicit_region > 0:
        warn("localities.zone_code.parent_region", f"{missing_explicit_region} explicit zone code entries have no parent_region_iso; uniqueness will be resolved from place geometry at load time.")

    def _valid_lat_lon_pair(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
            and math.isfinite(value[0])
            and math.isfinite(value[1])
            and -90 <= value[0] <= 90
            and -180 <= value[1] <= 180
        )

    csw = extent.get("country_sw")
    bounds_raw = extent.get("country_bounds")
    bounds = _as_dict(bounds_raw)
    if bounds_raw is not None and not isinstance(bounds_raw, dict):
        fail("profile.country_extent.country_bounds", "country_bounds must be a valid object.")
    bsw = bounds.get("sw")
    bne = bounds.get("ne")
    if not _valid_lat_lon_pair(csw):
        fail("profile.country_extent.country_sw", f"country_sw must be [lat, lon] with finite numbers in WGS84 range. Got: {csw!r}.")
    if not _valid_lat_lon_pair(bsw):
        fail("profile.country_extent.country_bounds.sw", f"country_bounds.sw must be [lat, lon]. Got: {bsw!r}.")
    if not _valid_lat_lon_pair(bne):
        fail("profile.country_extent.country_bounds.ne", f"country_bounds.ne must be [lat, lon]. Got: {bne!r}.")
    if _valid_lat_lon_pair(bsw) and _valid_lat_lon_pair(bne) and bne[0] < bsw[0]:
        fail("profile.country_extent.country_bounds", f"country_bounds.ne.lat ({bne[0]}) must be \u2265 country_bounds.sw.lat ({bsw[0]}). Lon may wrap (antimeridian), but lat must not.")

    requested_mode = grid_settings.get("distance_mode")
    if requested_mode is None:
        validated_distance_mode = "flat"
        pass_("grid_settings.distance_mode", 'distance_mode not specified \u2014 defaulting to "flat" (backward-compatible).')
    elif requested_mode in ("flat", "wgs84_ellipsoid"):
        validated_distance_mode = requested_mode
        pass_("grid_settings.distance_mode", f'Distance mode: "{requested_mode}".')
    else:
        validated_distance_mode = "flat"
        fail("grid_settings.distance_mode", f'Unknown distance_mode "{requested_mode}". Must be one of: "flat", "wgs84_ellipsoid". A typo here would silently shift every LAP code, so init refuses to start.')

    distance_conversion_raw = grid_settings.get("distance_conversion")
    distance_conversion = _as_dict(distance_conversion_raw)
    if distance_conversion_raw is not None and not isinstance(distance_conversion_raw, dict):
        fail("grid_settings.distance_conversion", "distance_conversion must be a valid object.")
    configured_meters_per_degree_lat = distance_conversion.get("meters_per_degree_lat")
    if configured_meters_per_degree_lat is None:
        validated_meters_per_degree_lat = 111_320.0
        pass_("grid_settings.distance_conversion.meters_per_degree_lat", "meters_per_degree_lat not specified — defaulting to 111320.")
    elif (
        isinstance(configured_meters_per_degree_lat, (int, float))
        and not isinstance(configured_meters_per_degree_lat, bool)
        and math.isfinite(configured_meters_per_degree_lat)
        and configured_meters_per_degree_lat > 0
    ):
        validated_meters_per_degree_lat = float(configured_meters_per_degree_lat)
        pass_("grid_settings.distance_conversion.meters_per_degree_lat", f"meters_per_degree_lat: {configured_meters_per_degree_lat}.")
    else:
        validated_meters_per_degree_lat = 111_320.0
        fail("grid_settings.distance_conversion.meters_per_degree_lat", "meters_per_degree_lat must be a finite positive number.")

    # ── If any fatal check, abort ─────────────────────────────────
    if fatal:
        return {
            "ok": False,
            "countryCode": profile_country,
            "countryName": meta.get("country_name"),
            "bounds": None,
            "checks": checks,
            "error": " ".join(c["message"] for c in checks if c["status"] == "fail"),
        }

    # ── All checks passed — apply state ───────────────────────────
    state.country_profile = profile
    state.country_code = profile_country or "GN"

    state.oglap_country_regions = _map_from_code_table(level_4_regions)

    state.oglap_country_regions_reverse = {
        v: k for k, v in state.oglap_country_regions.items()
    }

    state.oglap_country_prefectures = _map_from_code_table(level_6_prefectures)

    # Cache zone codes by ID (levels 8, 9, 10)
    state.oglap_zone_codes_by_id.clear()
    state.oglap_explicit_zone_codes_by_region.clear()
    zones_list = (
        list(level_8_sous_prefectures.values())
        + list(level_9_villages.values())
        + list(level_10_quartiers.values())
    )
    for z in zones_list:
        if not isinstance(z, dict):
            continue
        pid = z.get("place_id")
        code = z.get("oglap_code")
        if pid is not None and code:
            normalized_code = str(code).strip().upper()
            state.oglap_zone_codes_by_id[str(pid)] = normalized_code
            try:
                state.oglap_zone_codes_by_id[int(pid)] = normalized_code
            except (ValueError, TypeError):
                pass
            region_iso = z.get("parent_region_iso")
            if region_iso:
                state.oglap_explicit_zone_codes_by_region.setdefault(region_iso, set()).add(normalized_code)

    prefix_map = dict(zone_naming.get("type_prefix_map") or {})
    state.zone_type_prefix_default = prefix_map.pop("default", "Z")
    state.zone_type_prefix = prefix_map

    state.ggp_stopwords = set(
        str(s).upper() for s in (zone_naming.get("stopwords") or [])
    )
    state.ggp_pad_char = zone_naming.get("padding_char") or "X"

    state.country_sw = list(csw)
    state.country_bounds = {"sw": list(bsw), "ne": list(bne)}
    state.meters_per_degree_lat = validated_meters_per_degree_lat
    state.distance_mode = validated_distance_mode
    state.country_crosses_antimeridian = state.country_bounds["ne"][1] < state.country_bounds["sw"][1]

    bounds_arr = [state.country_bounds["sw"], state.country_bounds["ne"]]

    return {
        "ok": True,
        "countryCode": state.country_code,
        "countryName": meta.get("country_name", "Country"),
        "bounds": bounds_arr,
        "checks": checks,
        "error": None,
    }

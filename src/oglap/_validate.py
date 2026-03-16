"""
Init-time validation — validates profile + localities naming and applies engine state.
"""

from __future__ import annotations

from typing import Any

from ._constants import PACKAGE_VERSION
from ._semver import satisfies_caret
from ._state import state


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
    meta = profile.get("meta") or {}
    if not meta.get("country_oglap_code") and not meta.get("iso_alpha_2"):
        fail("profile.meta.country_code", "Profile meta missing both country_oglap_code and iso_alpha_2.")
    else:
        _cc = meta.get("country_oglap_code") or meta.get("iso_alpha_2")
        pass_("profile.meta.country_code", "Country code: %s" % _cc)

    extent = profile.get("country_extent") or {}
    if not extent.get("country_sw") or not extent.get("country_bounds"):
        fail("profile.country_extent", "Profile missing country_extent (country_sw or country_bounds).")
    else:
        pass_("profile.country_extent", "Country extent defined.")

    if not profile.get("grid_settings"):
        fail("profile.grid_settings", "Profile missing grid_settings section.")
    else:
        pass_("profile.grid_settings", "Grid settings present.")

    zone_naming = profile.get("zone_naming") or {}
    if not zone_naming.get("type_prefix_map"):
        fail("profile.zone_naming", "Profile missing zone_naming.type_prefix_map.")
    else:
        _n = len(zone_naming["type_prefix_map"])
        pass_("profile.zone_naming", "Zone naming rules loaded (%d type prefixes)." % _n)

    # ── 3. Package version compatibility ──────────────────────────
    compat = profile.get("compatibility")
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
    has_l4 = bool(localities_naming.get("level_4_regions") and len(localities_naming["level_4_regions"]) > 0)
    has_l6 = bool(localities_naming.get("level_6_prefectures") and len(localities_naming["level_6_prefectures"]) > 0)
    has_zones = (
        bool(localities_naming.get("level_8_sous_prefectures") and len(localities_naming["level_8_sous_prefectures"]) > 0)
        or bool(localities_naming.get("level_9_villages") and len(localities_naming["level_9_villages"]) > 0)
        or bool(localities_naming.get("level_10_quartiers") and len(localities_naming["level_10_quartiers"]) > 0)
    )
    if not has_l4:
        fail("localities.level_4", "Localities naming has no level_4_regions entries \u2014 regions cannot be resolved.")
    else:
        pass_("localities.level_4", "Level 4 regions: %d entries." % len(localities_naming["level_4_regions"]))
    if not has_l6:
        warn("localities.level_6", "Localities naming has no level_6_prefectures \u2014 prefecture resolution will use fallbacks.")
    else:
        pass_("localities.level_6", "Level 6 prefectures: %d entries." % len(localities_naming["level_6_prefectures"]))
    if not has_zones:
        warn("localities.zones", "Localities naming has no zone entries (levels 8/9/10) \u2014 local grid addressing will be unavailable.")
    else:
        count = (
            len(localities_naming.get("level_8_sous_prefectures") or {})
            + len(localities_naming.get("level_9_villages") or {})
            + len(localities_naming.get("level_10_quartiers") or {})
        )
        pass_("localities.zones", f"Zone entries (levels 8/9/10): {count} total.")

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

    state.oglap_country_regions = _map_from_code_table(localities_naming.get("level_4_regions"))

    state.oglap_country_regions_reverse = {
        v: k for k, v in state.oglap_country_regions.items()
    }

    state.oglap_country_prefectures = _map_from_code_table(localities_naming.get("level_6_prefectures"))

    # Cache zone codes by ID (levels 8, 9, 10)
    state.oglap_zone_codes_by_id.clear()
    zones_list = (
        list((localities_naming.get("level_8_sous_prefectures") or {}).values())
        + list((localities_naming.get("level_9_villages") or {}).values())
        + list((localities_naming.get("level_10_quartiers") or {}).values())
    )
    for z in zones_list:
        if not isinstance(z, dict):
            continue
        pid = z.get("place_id")
        code = z.get("oglap_code")
        if pid and code:
            state.oglap_zone_codes_by_id[str(pid)] = code
            try:
                state.oglap_zone_codes_by_id[int(pid)] = code
            except (ValueError, TypeError):
                pass

    prefix_map = dict(zone_naming.get("type_prefix_map") or {})
    state.zone_type_prefix_default = prefix_map.pop("default", "Z")
    state.zone_type_prefix = prefix_map

    state.ggp_stopwords = set(
        str(s).upper() for s in (zone_naming.get("stopwords") or [])
    )
    state.ggp_pad_char = zone_naming.get("padding_char") or "X"

    state.country_sw = extent.get("country_sw") or [7.19, -15.37]
    bounds = extent.get("country_bounds") or {}
    state.country_bounds = {
        "sw": bounds.get("sw") or [7.19, -15.37],
        "ne": bounds.get("ne") or [12.68, -7.64],
    }
    state.meters_per_degree_lat = (
        (profile.get("grid_settings") or {})
        .get("distance_conversion", {})
        .get("meters_per_degree_lat", 111_320)
    )

    bounds_arr = [state.country_bounds["sw"], state.country_bounds["ne"]]

    return {
        "ok": True,
        "countryCode": state.country_code,
        "countryName": meta.get("country_name", "Country"),
        "bounds": bounds_arr,
        "checks": checks,
        "error": None,
    }

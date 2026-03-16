"""
GGP name normalization, stopword removal, zone-code generation,
consonant abbreviation, and collision-avoidance helpers.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ._constants import CONSONANTS
from ._state import state


# ── Name normalization (GGP Section 6) ──────────────────────────────

_RE_HYPHEN_UNDER = re.compile(r"[-_]")
_RE_PUNCT = re.compile(r"['.,/()]")
_RE_MULTI_SPACE = re.compile(r"\s+")


def normalize_name_for_ggp(name: str) -> str:
    """Uppercase, remove accents, hyphens/underscores → space, strip punctuation."""
    if not name or not isinstance(name, str):
        return ""
    # NFD decomposition then remove combining marks
    nfd = unicodedata.normalize("NFD", name)
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    upper = stripped.upper()
    upper = _RE_HYPHEN_UNDER.sub(" ", upper)
    upper = _RE_PUNCT.sub("", upper)
    upper = _RE_MULTI_SPACE.sub(" ", upper)
    return upper.strip()


# ── Stopword removal (GGP Section 7) ───────────────────────────────

def remove_stopwords(tokens: list[str]) -> list[str]:
    """Filter out empty tokens and those in the GGP stopword set."""
    return [t for t in tokens if t and t not in state.ggp_stopwords]


# ── Consonant abbreviation ──────────────────────────────────────────

def consonant_abbrev2(significant_tokens: list[str]) -> str:
    """Two-letter consonant abbreviation from significant tokens.

    Chars 2-3 of zone code = first 2 consonants from the name.
    """
    s = "".join(significant_tokens).upper()
    cons: list[str] = []
    for c in s:
        if c in CONSONANTS:
            cons.append(c)
            if len(cons) >= 2:
                break
    if len(cons) >= 2:
        return cons[0] + cons[1]
    if len(cons) == 1:
        return cons[0] + state.ggp_pad_char
    return state.ggp_pad_char + state.ggp_pad_char


# ── Significant tokens ─────────────────────────────────────────────

def get_significant_tokens(name: str) -> list[str]:
    """Normalize + remove stopwords → list of significant tokens."""
    normalized = normalize_name_for_ggp(name)
    if not normalized:
        return []
    tokens = [t for t in normalized.split() if t]
    return remove_stopwords(tokens)


# ── Admin helpers ───────────────────────────────────────────────────

def get_admin_level_6_iso_from_address(address: dict[str, Any]) -> str | None:
    """Extract admin_level 6 ISO from address dict."""
    return address.get("ISO3166-2-Lvl6") or address.get("ISO3166-2-lvl6") or None


def normalized_first_letter(name: str) -> str | None:
    """First A-Z letter from the GGP-normalized name."""
    normalized = normalize_name_for_ggp(name or "")
    m = re.search(r"[A-Z]", normalized)
    return m.group(0) if m else None


def strip_prefecture_prefix(name: str) -> str:
    """Remove ``Préfecture de`` / ``Prefecture de`` prefix."""
    return re.sub(r"^(Pr[eé]fecture|Prefecture)\s+(de\s+)?", "", str(name or ""), flags=re.IGNORECASE).strip()


def _get_admin_level_6_name_from_containment(lon: float, lat: float) -> str | None:
    """Infer prefecture-level admin name by point containment (admin_level=6)."""
    from ._geo import point_in_geometry  # local import to break circular

    if not state.places:
        return None

    if state.admin_level_6_places_cache is None:
        state.admin_level_6_places_cache = [
            p for p in state.places
            if _parse_admin_level(p) == 6
        ]

    for place in state.admin_level_6_places_cache:
        if not place.get("geojson"):
            continue
        if not point_in_geometry(lon, lat, place["geojson"]):
            continue
        p_address = place.get("address") or {}
        iso6 = get_admin_level_6_iso_from_address(p_address)
        profile_name = (
            state.country_profile
            .get("admin_codes", {})
            .get("level_6_prefectures", {})
            .get(iso6, {})
            .get("name")
            if iso6 else None
        )
        if profile_name:
            return profile_name
        return strip_prefecture_prefix(
            p_address.get("county")
            or p_address.get("state")
            or (place.get("display_name", "").split(",")[0] if place.get("display_name") else "")
        )
    return None


def _parse_admin_level(place: dict[str, Any]) -> int:
    """Parse admin_level from extratags, return 0 if absent."""
    et = place.get("extratags") or {}
    al = et.get("admin_level")
    if al is None:
        return 0
    try:
        return int(al)
    except (ValueError, TypeError):
        return 0


def upper_admin_first_letter(address: dict[str, Any], place: dict[str, Any] | None = None) -> str:
    """First letter of the direct upper admin subdivision (prefecture/county or region).

    Used as 4th char of zone code.
    """
    from ._geo import centroid_from_place  # local import

    cache_key = place.get("place_id") if place else None
    if cache_key is not None and cache_key in state.upper_admin_letter_cache:
        return state.upper_admin_letter_cache[cache_key]

    county_name = strip_prefecture_prefix(address.get("county", ""))
    resolved = normalized_first_letter(county_name)
    if not resolved:
        resolved = normalized_first_letter(address.get("state", ""))

    if not resolved:
        iso6 = get_admin_level_6_iso_from_address(address)
        profile_pref_name = (
            state.country_profile
            .get("admin_codes", {})
            .get("level_6_prefectures", {})
            .get(iso6, {})
            .get("name")
            if iso6 else None
        )
        resolved = normalized_first_letter(strip_prefecture_prefix(profile_pref_name or ""))

    if not resolved and place:
        centroid = centroid_from_place(place)
        if centroid:
            lat, lon = centroid
            pref_by_containment = _get_admin_level_6_name_from_containment(lon, lat)
            resolved = normalized_first_letter(strip_prefecture_prefix(pref_by_containment or ""))
            if not resolved:
                # Import here to avoid circular dependency
                from ._spatial import get_admin_level_2_iso_with_fallback
                region_iso = get_admin_level_2_iso_with_fallback(lat, lon, place, skip_sampling=True)
                region_name = (
                    state.country_profile
                    .get("admin_codes", {})
                    .get("level_4_regions", {})
                    .get(region_iso, {})
                    .get("name")
                )
                resolved = normalized_first_letter(region_name)

    if not resolved:
        resolved = state.ggp_pad_char

    if cache_key is not None:
        state.upper_admin_letter_cache[cache_key] = resolved
    return resolved


# ── Zone key / code generation ──────────────────────────────────────

def name_key_from_tokens(
    significant_tokens: list[str],
    address: dict[str, Any],
    place: dict[str, Any] | None = None,
) -> str:
    """Zone key = 2 consonants + 1 upper-admin letter (3 chars)."""
    if not significant_tokens:
        return "XXX"
    two = consonant_abbrev2(significant_tokens)
    upper = upper_admin_first_letter(address, place) if address else state.ggp_pad_char
    return (two + upper)[:3]


def name_key_fallback_a(
    significant_tokens: list[str],
    address: dict[str, Any],
) -> str | None:
    """Fallback A: 2 consonants + first letter of state (if different)."""
    if not significant_tokens or not address or not address.get("state"):
        return None
    two = consonant_abbrev2(significant_tokens)
    state_first = (address["state"] or "")[:1].upper()
    if not re.match(r"[A-Z]", state_first):
        return None
    return (two + state_first)[:3]


def zone_code_from_name_and_type(
    name: str,
    type_prefix: str,
    address: dict[str, Any],
) -> str:
    """GGP zone code = [PREFIX] + [KEY3]."""
    prefix = type_prefix or "Z"
    significant = get_significant_tokens(name)
    if not significant:
        return prefix + "XXX"
    key = name_key_from_tokens(significant, address, None)
    return prefix + key


def get_type_prefix_for_zone(place_type: str, admin_level: int | None) -> str:
    """Resolve type prefix from OSM place type and admin_level (GGP Section 5)."""
    key = (place_type or "").lower()
    if admin_level == 8:
        return "S"  # Commune / Sous-préfecture
    if admin_level == 10:
        return "Q"  # Quartier boundary
    if key in state.zone_type_prefix:
        return state.zone_type_prefix[key]
    return state.zone_type_prefix_default


def get_place_zone_candidates(place: dict[str, Any]) -> dict[str, Any]:
    """Base code and optional fallback A code for collision resolution."""
    address = place.get("address") or {}
    name = (
        address.get("quarter")
        or address.get("neighbourhood")
        or address.get("suburb")
        or address.get("village")
        or address.get("hamlet")
        or address.get("town")
        or address.get("city")
        or (place.get("display_name", "").split(",")[0].strip() if place.get("display_name") else "")
    )
    place_type = place.get("type") or place.get("addresstype") or ""
    admin_level = _parse_admin_level(place) or None
    prefix = get_type_prefix_for_zone(place_type, admin_level)
    significant = get_significant_tokens(name)
    if not significant:
        return {"prefix": prefix, "baseCode": prefix + "XXX", "fallbackCode": None}
    base_key = name_key_from_tokens(significant, address, place)
    base_code = prefix + base_key
    fallback_key = name_key_fallback_a(significant, address)
    fallback_code = (prefix + fallback_key) if fallback_key else None
    return {"prefix": prefix, "baseCode": base_code, "fallbackCode": fallback_code}

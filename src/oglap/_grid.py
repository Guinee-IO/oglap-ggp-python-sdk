"""
Macroblock / microspot encode-decode and LAP computation.

Local grid:    4-char macroblock (LetterDigitLetterDigit), 100 m cells, 1 m micro.
National grid: 6-char macroblock (XXXYYY, A-Z per axis, 26**3 = 17 576 per axis),
               100 m cells, 1 m micro.
"""

from __future__ import annotations

import math
import re
from typing import Any

from ._constants import ALPHA3_MAX, NATIONAL_CELL_SIZE_M, NATIONAL_MICRO_SCALE
from ._constants import GRID_EPSILON_M, LOCAL_AXIS_BLOCKS, LOCAL_CELL_SIZE_M, LOCAL_GRID_SPAN_M
from ._state import state

# ── Precompiled regex ───────────────────────────────────────────────
_RE_ALPHA6 = re.compile(r"^[A-Z]{6}$")
_RE_LOCAL_MACRO = re.compile(r"^[A-J]\d[A-J]\d$")
_RE_MICRO = re.compile(r"^\d{4}$")


# ── Helpers ─────────────────────────────────────────────────────────

def _m_per_deg_lat_ellipsoid(lat_deg: float) -> float:
    phi = lat_deg * math.pi / 180.0
    return 111132.954 - 559.822 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)


def _m_per_deg_lon_ellipsoid(lat_deg: float) -> float:
    phi = lat_deg * math.pi / 180.0
    return 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi) + 0.118 * math.cos(5 * phi)


def meters_per_degree_lat(lat_deg: float = 0.0) -> float:
    if state.distance_mode == "wgs84_ellipsoid":
        return _m_per_deg_lat_ellipsoid(lat_deg)
    return state.meters_per_degree_lat


def meters_per_degree_lon(lat_deg: float) -> float:
    if state.distance_mode == "wgs84_ellipsoid":
        return _m_per_deg_lon_ellipsoid(lat_deg)
    lat_rad = lat_deg * math.pi / 180.0
    return state.meters_per_degree_lat * math.cos(lat_rad)


def normalize_lon_for_grid(lon: float, origin_lon: float) -> float:
    if not state.country_crosses_antimeridian:
        return lon
    return lon + 360 if lon < origin_lon else lon


def is_offset_within_local_grid(east_m: float, north_m: float) -> bool:
    return (
        east_m >= -GRID_EPSILON_M
        and north_m >= -GRID_EPSILON_M
        and east_m < LOCAL_GRID_SPAN_M
        and north_m < LOCAL_GRID_SPAN_M
    )


def is_point_within_local_grid(lat: float, lon: float, origin_lat: float, origin_lon: float) -> bool:
    effective_lon = normalize_lon_for_grid(lon, origin_lon)
    east_m = (effective_lon - origin_lon) * meters_per_degree_lon(origin_lat)
    north_m = (lat - origin_lat) * meters_per_degree_lat(origin_lat)
    return is_offset_within_local_grid(east_m + GRID_EPSILON_M, north_m + GRID_EPSILON_M)


# ── Alpha-3 encoding (national grid) ───────────────────────────────

def encode_alpha3(n: int) -> str:
    """Encode integer 0..17 575 as 3 A-Z letters (AAA..ZZZ)."""
    try:
        safe = math.floor(float(n))
    except (TypeError, ValueError):
        safe = 0
    val = max(0, min(safe, ALPHA3_MAX - 1))
    c2 = val % 26
    c1 = (val // 26) % 26
    c0 = val // 676
    return chr(65 + c0) + chr(65 + c1) + chr(65 + c2)


def decode_alpha3(s: str) -> int:
    """Decode 3 A-Z letters to integer; returns -1 if invalid."""
    if not s or len(s) != 3:
        return -1
    u = s.upper()
    n = 0
    for ch in u:
        c = ord(ch) - 65
        if c < 0 or c > 25:
            return -1
        n = n * 26 + c
    return n


# ── Local macroblock helpers ────────────────────────────────────────

def macro_letter(n: int) -> str:
    """Letter encoding: 0->A, 1->B, ..., 9->J."""
    return chr(65 + min(9, max(0, int(n))))


def encode_local_macroblock(east_blocks: int, north_blocks: int) -> str:
    """Encode local macroblock: ``C2E6`` style (LetterDigitLetterDigit)."""
    e = max(0, min(LOCAL_AXIS_BLOCKS - 1, int(math.floor(east_blocks))))
    n = max(0, min(LOCAL_AXIS_BLOCKS - 1, int(math.floor(north_blocks))))
    e_tens = e // 10
    e_units = e % 10
    n_tens = n // 10
    n_units = n % 10
    return macro_letter(e_tens) + str(e_units) + macro_letter(n_tens) + str(n_units)


def encode_national_macroblock(east_km: int, north_km: int) -> str:
    """Encode national macroblock: ``XXXYYY`` (6 A-Z letters)."""
    return encode_alpha3(east_km) + encode_alpha3(north_km)


def encode_microspot(east_m: float, north_m: float) -> str:
    """Encode microspot: 0-99 east, 0-99 north -> 4 digits (e.g. ``5020``)."""
    e_raw = round(east_m) if isinstance(east_m, (int, float)) and math.isfinite(east_m) else 0
    n_raw = round(north_m) if isinstance(north_m, (int, float)) and math.isfinite(north_m) else 0
    e = min(99, max(0, e_raw))
    n = min(99, max(0, n_raw))
    return f"{e:02d}{n:02d}"


def decode_macro_letter(c: str) -> int:
    """Decode local macroblock letter (A=0 ... J=9)."""
    if not c or len(c) != 1:
        return 0
    u = c.upper()
    if u < "A" or u > "J":
        return 0
    return ord(u) - 65


# ── Decode macroblock ───────────────────────────────────────────────

def decode_macroblock(s: str) -> dict[str, int] | None:
    """Decode a macroblock string.

    * 6-char all A-Z → national: ``{blockEast, blockNorth}``
    * 4-char LetterDigitLetterDigit → local: ``{blockEast, blockNorth}``
    """
    if not s or len(s) < 4:
        return None
    u = s.upper()
    if len(u) == 6 and _RE_ALPHA6.match(u):
        east_km = decode_alpha3(u[:3])
        north_km = decode_alpha3(u[3:])
        if east_km < 0 or north_km < 0:
            return None
        return {"blockEast": east_km, "blockNorth": north_km}
    if len(u) == 4 and _RE_LOCAL_MACRO.match(u):
        block_east = decode_macro_letter(u[0]) * 10 + int(u[1])
        block_north = decode_macro_letter(u[2]) * 10 + int(u[3])
        return {"blockEast": block_east, "blockNorth": block_north}
    return None


def decode_microspot(s: str) -> dict[str, int] | None:
    """Decode microspot ``"5020"`` → ``{eastM, northM}``."""
    if not s or len(s) != 4:
        return None
    if not _RE_MICRO.match(s):
        return None
    east_m = int(s[:2])
    north_m = int(s[2:])
    return {"eastM": east_m, "northM": north_m}


# ── LAP computation ────────────────────────────────────────────────

def compute_lap(
    lat: float,
    lon: float,
    origin_lat: float,
    origin_lon: float,
    admin_level_2_code: str | None,
    admin_level_3_code: str | None,
    use_national: bool = False,
) -> dict[str, Any] | None:
    """Compute LAP code segments (local or national grid)."""
    m_per_lat = meters_per_degree_lat(origin_lat)
    m_per_lon = meters_per_degree_lon(origin_lat)
    effective_lon = normalize_lon_for_grid(lon, origin_lon)
    north_m = (lat - origin_lat) * m_per_lat
    east_m = (effective_lon - origin_lon) * m_per_lon

    # Float64 precision compensation
    north_m_eps = north_m + GRID_EPSILON_M
    east_m_eps = east_m + GRID_EPSILON_M

    admin2 = admin_level_2_code

    if use_national:
        block_east_n = max(0, int(math.floor(east_m_eps / NATIONAL_CELL_SIZE_M)))
        block_north_n = max(0, int(math.floor(north_m_eps / NATIONAL_CELL_SIZE_M)))
        if block_east_n >= ALPHA3_MAX or block_north_n >= ALPHA3_MAX:
            return None
        in_cell_east = int(math.floor((east_m_eps - block_east_n * NATIONAL_CELL_SIZE_M) / NATIONAL_MICRO_SCALE))
        in_cell_north = int(math.floor((north_m_eps - block_north_n * NATIONAL_CELL_SIZE_M) / NATIONAL_MICRO_SCALE))
        macroblock = encode_national_macroblock(block_east_n, block_north_n)
        microspot = encode_microspot(in_cell_east, in_cell_north)
        return {
            "country": state.country_code,
            "admin_level_2": admin2,
            "admin_level_3": None,
            "macroblock": macroblock,
            "microspot": microspot,
            "isNationalGrid": True,
            "lapCode": f"{state.country_code}-{admin2}-{macroblock}-{microspot}",
        }

    if not is_offset_within_local_grid(east_m_eps, north_m_eps):
        raise ValueError(
            "Local grid offset is outside the 10 km x 10 km addressable range."
        )

    block_east = int(math.floor(east_m_eps / LOCAL_CELL_SIZE_M))
    block_north = int(math.floor(north_m_eps / LOCAL_CELL_SIZE_M))
    in_block_east = east_m_eps - block_east * LOCAL_CELL_SIZE_M
    in_block_north = north_m_eps - block_north * LOCAL_CELL_SIZE_M
    macroblock = encode_local_macroblock(block_east, block_north)
    microspot = encode_microspot(in_block_east, in_block_north)

    a3 = admin_level_3_code or None
    return {
        "country": state.country_code,
        "admin_level_2": admin2,
        "admin_level_3": a3,
        "macroblock": macroblock,
        "microspot": microspot,
        "isNationalGrid": False,
        "lapCode": f"{state.country_code}-{admin2}-{a3}-{macroblock}-{microspot}",
    }

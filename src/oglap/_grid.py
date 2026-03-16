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
from ._state import state

# ── Epsilon for float64 precision at grid boundaries ────────────────
EPSILON = 1e-4

# ── Precompiled regex ───────────────────────────────────────────────
_RE_ALPHA6 = re.compile(r"^[A-Z]{6}$")
_RE_LOCAL_MACRO = re.compile(r"^[A-J]\d[A-J]\d$")


# ── Helpers ─────────────────────────────────────────────────────────

def meters_per_degree_lat() -> float:
    return state.meters_per_degree_lat


def meters_per_degree_lon(lat_deg: float) -> float:
    lat_rad = lat_deg * math.pi / 180.0
    return state.meters_per_degree_lat * math.cos(lat_rad)


# ── Alpha-3 encoding (national grid) ───────────────────────────────

def encode_alpha3(n: int) -> str:
    """Encode integer 0..17 575 as 3 A-Z letters (AAA..ZZZ)."""
    val = max(0, min(int(n), ALPHA3_MAX - 1))
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
    e_tens = int(east_blocks) // 10
    e_units = int(east_blocks) % 10
    n_tens = int(north_blocks) // 10
    n_units = int(north_blocks) % 10
    return macro_letter(e_tens) + str(e_units) + macro_letter(n_tens) + str(n_units)


def encode_national_macroblock(east_km: int, north_km: int) -> str:
    """Encode national macroblock: ``XXXYYY`` (6 A-Z letters)."""
    return encode_alpha3(east_km) + encode_alpha3(north_km)


def encode_microspot(east_m: float, north_m: float) -> str:
    """Encode microspot: 0-99 east, 0-99 north -> 4 digits (e.g. ``5020``)."""
    e = min(99, max(0, round(east_m)))
    n = min(99, max(0, round(north_m)))
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
    if len(u) >= 4 and _RE_LOCAL_MACRO.match(u[:4]):
        block_east = decode_macro_letter(u[0]) * 10 + int(u[1])
        block_north = decode_macro_letter(u[2]) * 10 + int(u[3])
        return {"blockEast": block_east, "blockNorth": block_north}
    return None


def decode_microspot(s: str) -> dict[str, int] | None:
    """Decode microspot ``"5020"`` → ``{eastM, northM}``."""
    if not s or len(s) != 4:
        return None
    try:
        east_m = int(s[:2])
        north_m = int(s[2:])
    except ValueError:
        return None
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
) -> dict[str, Any]:
    """Compute LAP code segments (local or national grid)."""
    m_per_lat = meters_per_degree_lat()
    m_per_lon = meters_per_degree_lon(origin_lat)
    north_m = (lat - origin_lat) * m_per_lat
    east_m = (lon - origin_lon) * m_per_lon

    # Float64 precision compensation
    north_m_eps = north_m + EPSILON
    east_m_eps = east_m + EPSILON

    admin2 = admin_level_2_code

    if use_national:
        block_east_n = max(0, int(math.floor(east_m_eps / NATIONAL_CELL_SIZE_M)))
        block_north_n = max(0, int(math.floor(north_m_eps / NATIONAL_CELL_SIZE_M)))
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

    block_east = int(math.floor(east_m_eps / 100))
    block_north = int(math.floor(north_m_eps / 100))
    in_block_east = east_m_eps - block_east * 100
    in_block_north = north_m_eps - block_north * 100
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

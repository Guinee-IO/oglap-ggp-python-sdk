"""
OGLAP SDK constants — grid parameters, S3 URLs, encoding tables.
"""

from __future__ import annotations

# --- Package identity ---
PACKAGE_VERSION = "0.1.0"

# --- Remote data ---
OGLAP_S3_BASE = "https://s3.guinee.io/oglap/ggp"

OGLAP_REMOTE_FILES = [
    {"key": "profile", "name": "gn_oglap_country_profile.json", "label": "Country profile", "timeout_ms": 30_000},
    {"key": "localities", "name": "gn_localities_naming.json", "label": "Localities naming", "timeout_ms": 60_000},
    {"key": "data", "name": "gn_full.json", "label": "Places database", "timeout_ms": 300_000},
]

# --- Slow-network detection ---
SLOW_BPS = 50 * 1024  # 50 KB/s
SLOW_WINDOW_MS = 5000

# --- Local data storage ---
OGLAP_DATA_DIR_DEFAULT = "oglap-data"

# --- Grid parameters ---
ALPHA3_MAX = 26 ** 3  # 17 576
NATIONAL_CELL_SIZE_M = 100
NATIONAL_MICRO_SCALE = 1

# --- Naming ---
CONSONANTS = frozenset("BCDFGHJKLMNPQRSTVWXZ")

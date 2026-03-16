"""
Semver parsing and caret-range checking.
"""

from __future__ import annotations

import re

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_semver(s: str) -> tuple[int, int, int] | None:
    """Parse ``"MAJOR.MINOR.PATCH"`` into a 3-tuple, or *None* if invalid."""
    if not isinstance(s, str):
        return None
    m = _SEMVER_RE.match(s.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def satisfies_caret(version: str, range_str: str) -> bool:
    """Check if *version* satisfies the caret range ``^range_str``.

    ``^MAJOR.MINOR.PATCH`` means ``>=MAJOR.MINOR.PATCH`` and
    ``<(MAJOR+1).0.0`` when MAJOR > 0, or ``<0.(MINOR+1).0`` when MAJOR == 0.
    """
    v = parse_semver(version)
    r = parse_semver(range_str)
    if v is None or r is None:
        return False

    # version must be >= range
    for i in range(3):
        if v[i] > r[i]:
            break
        if v[i] < r[i]:
            return False

    # version must be < next breaking change
    if r[0] > 0:
        return v[0] == r[0]
    if r[1] > 0:
        return v[0] == 0 and v[1] == r[1]
    return v[0] == 0 and v[1] == 0 and v[2] == r[2]

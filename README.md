# oglap (Python SDK)

> Python SDK for the **OGLAP** protocol — Offline Grid Location Addressing for the Guinea Grid Profile (GGP).

🇫🇷 **Version française** → [README.fr.md](README.fr.md)

Convert GPS coordinates into compact, deterministic, human-readable address codes (e.g. `GN-CON-QYTC-B0B1-2282`) and back — fully offline, with no external API. Designed for regions where formal postal addressing is sparse or unreliable.

[![PyPI version](https://img.shields.io/pypi/v/oglap.svg)](https://pypi.org/project/oglap/)
[![Python versions](https://img.shields.io/pypi/pyversions/oglap.svg)](https://pypi.org/project/oglap/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Table of contents

- [Why OGLAP?](#why-oglap)
- [The LAP code format](#the-lap-code-format)
- [Installation](#installation)
- [Initialization (required)](#initialization-required)
- [Core API](#core-api)
  - [`coordinates_to_lap` — encode GPS → LAP](#coordinates_to_lap--encode-gps--lap)
  - [`lap_to_coordinates` — decode LAP → GPS](#lap_to_coordinates--decode-lap--gps)
  - [`parse_lap_code` — break a code into components](#parse_lap_code--break-a-code-into-components)
  - [`validate_lap_code` — validate a code](#validate_lap_code--validate-a-code)
  - [`get_place_by_lap_code` — look up the underlying place](#get_place_by_lap_code--look-up-the-underlying-place)
  - [`bbox_from_geometry` & `centroid_from_bbox`](#bbox_from_geometry--centroid_from_bbox)
  - [State & metadata helpers](#state--metadata-helpers)
- [Data files & caching](#data-files--caching)
- [End-to-end example](#end-to-end-example)
- [Using inside a web framework](#using-inside-a-web-framework)
- [Performance notes](#performance-notes)
- [Testing](#testing)
- [Versioning & compatibility](#versioning--compatibility)
- [License](#license)

---

## Why OGLAP?

In many parts of the world, conventional street addresses don't exist or aren't reliable enough to route deliveries, dispatch emergency services, or share a location with a friend. OGLAP solves this by carving the country into a deterministic grid and giving every ~1 m × 1 m cell a short, copy-pasteable code.

- **Offline-first** — works without network once reference data is cached.
- **Deterministic** — same coordinates always produce the same code; same code always decodes back to the same point.
- **Hierarchical** — the prefix reveals the country / region / zone, so the code is meaningful even when truncated.
- **Human-readable** — uppercase A–Z and digits only, no ambiguous characters.

---

## The LAP code format

A LAP code encodes a location at four hierarchical levels. Two grid strategies coexist:

### Local grid (5 segments — used inside named administrative zones)

```
GN  - CON  - QYTC - B0B1 - 2282
│      │      │      │      └─ Microspot   — 4 digits, ~1 m offset inside the macroblock
│      │      │      └─────── Macroblock   — 4 chars [A–J][0–9][A–J][0–9], ~100 m cell inside the zone
│      │      └────────────── Zone         — 4 chars, immediate admin level ≥8 (e.g. QYTC for Yattaya-Fossedè)
│      └───────────────────── Region       — 3 chars, immediate admin level 4 or 6 (e.g. CON for Conakry)
└──────────────────────────── Country      — ISO alpha-2 (e.g. GN for Guinea)
```

### National grid (4 segments — fallback for rural areas without admin level ≥8 coverage)

```
GN  - NZE  - AABCDE - 4250
│      │      │        └─ Microspot   — 4 digits, ~1 m offset
│      │      └────────── Macroblock   — 6 letters, country-wide kilometric grid
│      └──────────────── Region       — 3 chars (e.g. NZE for Nzérékoré)
└─────────────────────── Country      — ISO alpha-2
```

The SDK transparently picks the right grid based on whether the input coordinate falls inside a named admin level ≥8 polygon.

---

## Installation

```bash
pip install oglap
```

Requires **Python ≥ 3.9** and depends on [`shapely`](https://shapely.readthedocs.io/) (geometry ops) and [`httpx`](https://www.python-httpx.org/) (async download).

Install in a fresh virtualenv:

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install oglap
```

---

## Initialization (required)

You must call `init_oglap()` **once** at application startup before any encoding/decoding function. On first run it downloads three JSON files from the OGLAP CDN (`https://s3.guinee.io/oglap/ggp/latest/`) and caches them under `oglap-data/<version>/`. Subsequent runs load from the cache instantly.

```python
import asyncio
from oglap import init_oglap

async def main():
    def on_progress(*, label, status, percent, step, totalSteps, **_):
        # status ∈ 'downloading' | 'cached' | 'slow' | 'validating' | 'done' | 'error'
        if status == "downloading":
            print(f"\r↓ [{step}/{totalSteps}] {label}: {percent}%", end="")
        elif status == "cached":
            print(f"⚡ [{step}/{totalSteps}] {label}: loaded from cache")
        elif status == "done":
            print(f"✓ [{step}/{totalSteps}] {label}: ready")
        elif status == "error":
            print(f"✗ [{step}/{totalSteps}] {label}: error")

    report = await init_oglap({
        "version": "latest",          # 'latest' (default) or a pinned dataset version
        "data_dir": "oglap-data",     # local cache directory (default: 'oglap-data')
        "force_download": False,      # re-download even if cache is present
        "on_progress": on_progress,
    })

    if not report["ok"]:
        raise RuntimeError(f"OGLAP init failed: {report['error']}")

asyncio.run(main())
```

### Init report shape

| Key            | Type           | Description                                                        |
| -------------- | -------------- | ------------------------------------------------------------------ |
| `ok`           | `bool`         | `True` if initialization succeeded                                 |
| `countryCode`  | `str \| None`  | Active country code, e.g. `"GN"`                                   |
| `countryName`  | `str \| None`  | Display name, e.g. `"Guinea"`                                      |
| `bounds`       | `list \| None` | `[[swLat, swLon], [neLat, neLon]]`                                 |
| `checks`       | `list[dict]`   | Per-step validation results — each `{id, status, message}`         |
| `error`        | `str \| None`  | First fatal error message if not ok                                |
| `dataDir`      | `str`          | Resolved local cache directory                                     |
| `dataLoaded`   | `dict`         | `{ok, count, message}` — places loaded into the in-memory engine   |

### Direct mode (bring your own data)

If you already have the JSON files in memory (e.g. loaded yourself or bundled with your app), skip the download:

```python
import json, asyncio
from oglap import init_oglap, load_oglap

async def main():
    profile    = json.load(open("my-profile.json"))
    localities = json.load(open("my-localities.json"))
    places     = json.load(open("my-places.json"))

    report = await init_oglap(profile, localities)
    if not report["ok"]:
        raise RuntimeError(report["error"])

    load_oglap(places)   # load the places database into the engine

asyncio.run(main())
```

---

## Core API

All functions below are **synchronous** (no network, pure in-memory computation) except `init_oglap`. Import them from the top-level `oglap` package:

```python
from oglap import (
    init_oglap,
    load_oglap,
    check_oglap,
    coordinates_to_lap,
    lap_to_coordinates,
    parse_lap_code,
    validate_lap_code,
    get_place_by_lap_code,
    bbox_from_geometry,
    centroid_from_bbox,
    get_package_version,
    get_country_code,
    get_country_sw,
    get_country_profile,
    get_oglap_prefectures,
    get_oglap_places,
)
```

### `coordinates_to_lap` — encode GPS → LAP

```python
from oglap import coordinates_to_lap

result = coordinates_to_lap(9.5370, -13.6773)  # lat, lon

print(result["lapCode"])         # 'GN-CON-QYTC-B0B1-2282'
print(result["humanAddress"])    # 'B0B1-2282, Yattaya Fossedè, Conakry, Guinea'
print(result["isNationalGrid"])  # False
```

Returns `None` if the coordinates fall outside the country (verified via 3-layer check: bounding box → country polygon → admin polygon).

**Result keys:**

| Key              | Type           | Description                                                          |
| ---------------- | -------------- | -------------------------------------------------------------------- |
| `lapCode`        | `str`          | Full code, e.g. `"GN-CON-QYTC-B0B1-2282"`                            |
| `country`        | `str`          | Country code, e.g. `"GN"`                                            |
| `admin_level_2`  | `str`          | Region code, e.g. `"CON"`                                            |
| `admin_level_3`  | `str \| None`  | Zone code (None when national-grid)                                  |
| `macroblock`     | `str`          | Macroblock segment                                                   |
| `microspot`      | `str`          | Microspot segment                                                    |
| `isNationalGrid` | `bool`         | `True` if national-grid (rural) was used                             |
| `displayName`    | `str`          | Reverse-geocoded display name                                        |
| `humanAddress`   | `str`          | Comma-joined human-readable address                                  |
| `address`        | `dict`         | Structured address components                                        |
| `originLat`      | `float`        | Latitude origin of the macroblock bounding box                       |
| `originLon`      | `float`        | Longitude origin of the macroblock bounding box                      |
| `pcode`          | `list[str]`    | UNOCHA P-codes for the matched admin units (when available)          |

### `lap_to_coordinates` — decode LAP → GPS

```python
from oglap import lap_to_coordinates

coords = lap_to_coordinates("GN-CON-QYTC-B0B1-2282")
# {"lat": 9.5370, "lon": -13.6773}

# The country prefix is optional:
lap_to_coordinates("CON-QYTC-B0B1-2282")  # same result
```

Returns `None` if the code is structurally invalid or references an unknown region/zone.

### `parse_lap_code` — break a code into components

```python
from oglap import parse_lap_code

parsed = parse_lap_code("GN-CON-QYTC-B0B1-2282")
# {
#     "admin_level_2_Iso":  "GN-C",   # ISO key of the region (CON resolves to its OSM-style key)
#     "admin_level_3_code": "QYTC",   # zone short code
#     "macroblock":         "B0B1",
#     "microspot":          "2282",
#     "isNationalGrid":     False,
# }

# Partial codes also parse:
parse_lap_code("GN-CON-QYTC")  # region + zone only — returns {"admin_level_2_Iso", "admin_level_3_code"}
parse_lap_code("QYTC")         # zone only          — returns {"admin_level_3_code"}
```

> **Note:** the country code (`GN`) is *not* a field on the parsed dict — it's implicit and available via `get_country_code()`. The region segment (e.g. `CON`) is exposed as `admin_level_2_Iso` (the OSM-style ISO key, e.g. `GN-C`), not as the 3-letter LAP short code. Use `get_oglap_prefectures()` to map between the two if you need the short code.

### `validate_lap_code` — validate a code

```python
from oglap import validate_lap_code

validate_lap_code("GN-CON-QYTC-B0B1-2282")  # → None  (valid)
validate_lap_code("GN-XXX-INVALID")         # → 'Unknown region code "XXX"'
```

Returns `None` for valid codes, or an English error message string for invalid ones.

### `get_place_by_lap_code` — look up the underlying place

```python
from oglap import get_place_by_lap_code

resolved = get_place_by_lap_code("GN-CON-QYTC-B0B1-2282")
# {
#     "place": {"place_id": ..., "address": {...}, "geojson": {...}, "display_name": ...},
#     "parsed": {"admin_level_2_Iso": ..., "admin_level_3_code": ..., ...},
#     # "originLat", "originLon" are present only when isNationalGrid is True
# }

addr = resolved["place"]["address"]
name = addr.get("village") or addr.get("town") or addr.get("city") or resolved["place"]["display_name"]
```

For national-grid codes, `place` is `None` (they do not bind to a named place) and the response carries `originLat`/`originLon` set to the country's south-west origin point — usable as a coarse fallback location.

### `bbox_from_geometry` & `centroid_from_bbox`

Geometry helpers for working with GeoJSON shapes the SDK loads internally.

```python
from oglap import bbox_from_geometry, centroid_from_bbox

geometry = {
    "type": "Polygon",
    "coordinates": [[[-13.70, 9.50], [-13.65, 9.50], [-13.65, 9.55], [-13.70, 9.55], [-13.70, 9.50]]],
}

bbox = bbox_from_geometry(geometry)   # [minLat, maxLat, minLon, maxLon]
center = centroid_from_bbox(bbox)     # [lat, lon]
```

### State & metadata helpers

```python
from oglap import (
    check_oglap,
    get_package_version,
    get_country_code,
    get_country_sw,
    get_country_profile,
    get_oglap_prefectures,
    get_oglap_places,
)

check_oglap()              # → init report (same shape init_oglap returned)
get_package_version()      # → '0.1.2'
get_country_code()         # → 'GN'
get_country_sw()           # → [7.19, -15.37]
get_country_profile()      # → the loaded country profile dict
get_oglap_prefectures()    # → {'GN.CON': 'CON', 'GN.NZE': 'NZE', ...}
get_oglap_places()         # → list[dict]  (the loaded places — large, use sparingly)
```

---

## Data files & caching

The SDK loads three reference files from `https://s3.guinee.io/oglap/ggp/<version>/`:

| File                                | Size   | Description                                                            |
| ----------------------------------- | ------ | ---------------------------------------------------------------------- |
| `gn_oglap_country_profile.json`     | ~3 KB  | Grid parameters, admin codes, naming rules, compatibility range        |
| `gn_localities_naming.json`         | ~300 KB | Naming table for regions / prefectures / zones                        |
| `gn_full.json`                      | ~37 MB | Places database with GeoJSON polygons                                  |

By default they are cached to `./oglap-data/latest/`. The cache directory is **gitignored** in this repo (and the SDK's `.gitignore` template) and should be gitignored in yours too — these files are reproducibly downloaded by `init_oglap()`.

To force a re-download (e.g. after a dataset update is published):

```python
await init_oglap({"force_download": True})
```

---

## End-to-end example

```python
import asyncio
from oglap import (
    init_oglap,
    coordinates_to_lap,
    lap_to_coordinates,
    validate_lap_code,
    get_place_by_lap_code,
)


class LocationService:
    """Thin wrapper exposing only what an app typically needs."""

    _ready: bool = False

    @classmethod
    async def init(cls) -> None:
        if cls._ready:
            return

        def progress(*, label, status, percent, step, totalSteps, **_):
            if status == "downloading":
                print(f"\r↓ [{step}/{totalSteps}] {label}: {percent}%", end="")
            elif status == "cached":
                print(f"⚡ [{step}/{totalSteps}] {label}: cached")
            elif status == "done":
                print(f"✓ [{step}/{totalSteps}] {label}: ready")

        report = await init_oglap({"on_progress": progress})
        if not report["ok"]:
            raise RuntimeError(f"OGLAP init failed: {report['error']}")
        cls._ready = True

    @staticmethod
    def encode(lat: float, lon: float) -> str | None:
        result = coordinates_to_lap(lat, lon)
        return result["lapCode"] if result else None

    @staticmethod
    def decode(code: str) -> dict | None:
        return lap_to_coordinates(code)  # None if invalid

    @staticmethod
    def validate(code: str) -> str | None:
        return validate_lap_code(code)   # None = valid; error string otherwise

    @staticmethod
    def resolve(code: str) -> dict | None:
        r = get_place_by_lap_code(code)
        if not r or not r.get("place"):
            return None
        a = r["place"].get("address", {})
        return {
            "name":       a.get("village") or a.get("town") or a.get("city") or r["place"].get("display_name"),
            "admin_code": r["parsed"]["admin_level_3_code"],
            "originLat":  r["originLat"],
            "originLon":  r["originLon"],
        }


async def main():
    await LocationService.init()

    code = LocationService.encode(9.660147, -13.588009)
    print(code)                              # 'GN-CON-QYTC-B0B1-2282'
    print(LocationService.decode(code))      # {'lat': ~9.660, 'lon': ~-13.588}
    print(LocationService.validate(code))    # None  (valid)
    print(LocationService.resolve(code))     # {'name': 'Yattaya Fossedè', ...}


asyncio.run(main())
```

---

## Using inside a web framework

### FastAPI

`init_oglap()` is async — call it from FastAPI's lifespan handler so it runs once at startup and the engine is warm for every request:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from oglap import init_oglap, coordinates_to_lap, lap_to_coordinates

@asynccontextmanager
async def lifespan(app: FastAPI):
    report = await init_oglap()
    if not report["ok"]:
        raise RuntimeError(f"OGLAP init failed: {report['error']}")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/encode")
def encode(lat: float, lon: float):
    result = coordinates_to_lap(lat, lon)
    if not result:
        raise HTTPException(404, "Coordinates outside country boundaries")
    return result

@app.get("/decode/{code}")
def decode(code: str):
    coords = lap_to_coordinates(code)
    if not coords:
        raise HTTPException(400, "Invalid LAP code")
    return coords
```

### Django (sync views)

Run `init_oglap()` once at process start (e.g. from an `AppConfig.ready()` hook with `asyncio.run`, or a management command). The encode/decode helpers themselves are synchronous, so they slot directly into a regular view.

---

## Performance notes

- **Spatial index** — `coordinates_to_lap` uses a Shapely STRtree built once at `load_oglap()` time. Reverse-geocoding a single coordinate is O(log N) candidate lookup + a small polygon-in-polygon check.
- **Bounded validation** — all regex scans run against bounded, sanitized strings — no ReDoS exposure on malformed user input.
- **3-layer rejection** — coordinates outside the country are short-circuited by bbox check, then country polygon, then admin polygon. Out-of-country calls cost ~µs.
- **Single-process state** — the engine holds the loaded dataset in a module-level state. Reuse the process across requests; don't reload data per-request.

---

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

The test suite is ~80 tests covering encoding, decoding, parsing, validation, and round-trip determinism across the local and national grids.

---

## Versioning & compatibility

The SDK declares a compatibility range with the country-profile dataset via a semver caret. The currently published `gn_oglap_country_profile.json` requires the SDK to satisfy `^0.1.0` — so this package follows the 0.1.x line. Major bumps in the dataset schema will be accompanied by a major bump here.

You can inspect the loaded compatibility range at runtime:

```python
from oglap import get_country_profile
print(get_country_profile()["compatibility"])
# {'oglap_package_range': '^0.1.0', 'dataset_versions': ['2026-02-21T14:13:02.414Z']}
```

If `init_oglap()` fails with a compatibility error, either downgrade the SDK or update your cached dataset (`force_download=True`).

---

## License

MIT — see [LICENSE](LICENSE).

Issues and contributions: <https://github.com/Guinee-IO/oglap-ggp-python-sdk/issues>

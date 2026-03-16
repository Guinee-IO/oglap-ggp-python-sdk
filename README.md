# OGLAP Python SDK

**Offline Grid Location Addressing Protocol** — Python SDK for the Guinea Grid Profile (GGP).

Converts GPS coordinates into human-readable, deterministic alphanumeric OGLAP codes
(e.g., `GN-CKY-QKPC-B4A4-2798`) and vice versa. Works entirely offline once reference
data is cached locally.

## Installation

```bash
pip install oglap
```

## Quick Start

```python
import asyncio
from oglap import init_oglap, coordinates_to_lap, lap_to_coordinates, parse_lap_code

async def main():
    # Initialize (downloads data on first run, caches locally)
    report = await init_oglap()
    print(f"Loaded: {report['countryName']} ({report['countryCode']})")

    # Encode GPS → LAP code
    result = coordinates_to_lap(9.5370, -13.6785)
    print(f"LAP: {result['lapCode']}")
    print(f"Address: {result['humanAddress']}")

    # Decode LAP → GPS
    parsed = parse_lap_code(result['lapCode'])
    coords = lap_to_coordinates(
        result['originLat'], result['originLon'],
        parsed['macroblock'], parsed['microspot']
    )
    print(f"Decoded: {coords['lat']:.6f}, {coords['lon']:.6f}")

asyncio.run(main())
```

## Features

- **Dual grid strategy**: Local grid (5-segment, 1m precision) for urban zones, national grid (4-segment) fallback for rural areas
- **Offline-first**: Downloads reference data once, caches to `oglap-data/` folder
- **Country boundary verification**: 3-layer check (bounding box, country polygon, reverse geocode)
- **Deterministic**: Same coordinates always produce the same OGLAP code
- **Type-annotated**: Full type hints for IDE support

## API Reference

| Function | Description |
|----------|-------------|
| `init_oglap()` | Initialize engine (async, downloads/caches data) |
| `coordinates_to_lap(lat, lon)` | GPS → OGLAP code |
| `lap_to_coordinates(origin_lat, origin_lon, macroblock, microspot)` | OGLAP → GPS |
| `parse_lap_code(query)` | Parse LAP code string into components |
| `validate_lap_code(query)` | Validate LAP code format |
| `get_place_by_lap_code(query)` | Look up place from LAP code |
| `load_oglap(data)` | Load places data into engine |
| `check_oglap()` | Check engine initialization status |
| `get_package_version()` | Get SDK version |
| `get_country_code()` | Get active country code |
| `get_country_sw()` | Get country SW origin point |
| `get_country_profile()` | Get country profile config |
| `get_oglap_prefectures()` | Get prefecture code map |
| `get_oglap_places()` | Get loaded places array |
| `bbox_from_geometry(geometry)` | Compute bounding box from GeoJSON |
| `centroid_from_bbox(bbox)` | Compute centroid from bounding box |

## License

MIT

"""
Full OGLAP engine test — mirrors the JavaScript test.js (68+ tests).

Sections:
  1. Pre-init state
  2. Init (download mode)
  3. State getters
  4. coordinatesToLap — local grid (5 cities)
  4b. coordinatesToLap — national grid (4 rural areas)
  4c. coordinatesToLap — out-of-bounds rejection (7 foreign locations)
  5. parseLapCode
  6. validateLapCode
  7. lapToCoordinates — decode LAP → GPS
  8. getPlaceByLapCode
  9. bboxFromGeometry & centroidFromBbox
  10. Round-trip consistency
"""

from __future__ import annotations

import math

import pytest

from oglap import (
    bbox_from_geometry,
    centroid_from_bbox,
    check_oglap,
    coordinates_to_lap,
    get_country_code,
    get_country_profile,
    get_country_sw,
    get_oglap_places,
    get_oglap_prefectures,
    get_package_version,
    get_place_by_lap_code,
    init_oglap,
    lap_to_coordinates,
    load_oglap,
    parse_lap_code,
    validate_lap_code,
)


# ════════════════════════════════════════════════════════════════════
#  1. PRE-INIT STATE
# ════════════════════════════════════════════════════════════════════

class TestPreInitState:
    def test_package_version(self):
        v = get_package_version()
        assert isinstance(v, str) and len(v) > 0

    def test_check_oglap_before_init(self):
        # Before any init, check_oglap should report not ok
        # (Note: if session fixture already ran, this won't apply.
        #  We test the function returns a dict with expected keys.)
        result = check_oglap()
        assert isinstance(result, dict)
        assert "ok" in result


# ════════════════════════════════════════════════════════════════════
#  2. INIT (download mode)
# ════════════════════════════════════════════════════════════════════

class TestInit:
    @pytest.mark.asyncio
    async def test_init_download_mode(self, oglap_report):
        report = oglap_report
        assert report["ok"] is True
        assert report["countryCode"] is not None
        assert report["bounds"] is not None
        assert report.get("dataDir") is not None
        assert report.get("dataLoaded") is not None
        assert report["dataLoaded"]["ok"] is True


# ════════════════════════════════════════════════════════════════════
#  3. STATE GETTERS
# ════════════════════════════════════════════════════════════════════

class TestStateGetters:
    def test_check_oglap_after_init(self, oglap_report):
        result = check_oglap()
        assert result["ok"] is True
        assert result["countryCode"] is not None

    def test_get_country_code(self, oglap_report):
        assert isinstance(get_country_code(), str)
        assert len(get_country_code()) == 2

    def test_get_country_sw(self, oglap_report):
        sw = get_country_sw()
        assert isinstance(sw, list)
        assert len(sw) == 2

    def test_get_country_profile(self, oglap_report):
        profile = get_country_profile()
        assert isinstance(profile, dict)
        assert "schema_id" in profile

    def test_get_oglap_prefectures(self, oglap_report):
        prefs = get_oglap_prefectures()
        assert isinstance(prefs, dict)
        assert len(prefs) > 0

    def test_get_oglap_places(self, oglap_report):
        places = get_oglap_places()
        assert isinstance(places, list)
        assert len(places) > 0


# ════════════════════════════════════════════════════════════════════
#  4. coordinatesToLap — GPS → LAP (local grid)
# ════════════════════════════════════════════════════════════════════

LOCAL_TEST_COORDS = [
    {"name": "Conakry center", "lat": 9.5370, "lon": -13.6785},
    {"name": "Nzérékoré", "lat": 7.7562, "lon": -8.8179},
    {"name": "Kankan", "lat": 10.3854, "lon": -9.3057},
    {"name": "Labé", "lat": 11.3183, "lon": -12.2860},
    {"name": "Kindia", "lat": 10.0565, "lon": -12.8665},
]

NATIONAL_TEST_COORDS = [
    {"name": "Rural Siguiri (Kankan)", "lat": 11.70, "lon": -9.30},
    {"name": "Rural Macenta (Nzérékoré)", "lat": 8.40, "lon": -9.40},
    {"name": "Rural Boké (Boké)", "lat": 11.20, "lon": -14.20},
    {"name": "Rural Faranah (Faranah)", "lat": 10.10, "lon": -10.80},
]

OUT_OF_BOUNDS_COORDS = [
    {"name": "Dakar, Senegal", "lat": 14.6928, "lon": -17.4467},
    {"name": "Atlantic Ocean", "lat": 9.00, "lon": -18.00},
    {"name": "Bamako, Mali", "lat": 12.6392, "lon": -8.0029},
    {"name": "Freetown, Sierra Leone", "lat": 8.4657, "lon": -13.2317},
    {"name": "Bissau, Guinea-Bissau", "lat": 11.8617, "lon": -15.5977},
    {"name": "Monrovia, Liberia", "lat": 6.3156, "lon": -10.8074},
    {"name": "Kédougou, Senegal (near GN border)", "lat": 12.5605, "lon": -12.1747},
]


class TestCoordinatesToLapLocal:
    @pytest.mark.parametrize("coord", LOCAL_TEST_COORDS, ids=[c["name"] for c in LOCAL_TEST_COORDS])
    def test_local_grid(self, oglap_report, coord):
        result = coordinates_to_lap(coord["lat"], coord["lon"])
        assert result is not None, f"{coord['name']} returned None"
        assert result["lapCode"], f"{coord['name']} has no lapCode"
        assert result["humanAddress"], f"{coord['name']} has no humanAddress"


class TestCoordinatesToLapNational:
    @pytest.mark.parametrize("coord", NATIONAL_TEST_COORDS, ids=[c["name"] for c in NATIONAL_TEST_COORDS])
    def test_national_grid(self, oglap_report, coord):
        result = coordinates_to_lap(coord["lat"], coord["lon"])
        assert result is not None, f"{coord['name']} returned None"
        assert result["lapCode"], f"{coord['name']} has no lapCode"

    def test_at_least_one_national(self, oglap_report):
        national_count = 0
        for coord in NATIONAL_TEST_COORDS:
            result = coordinates_to_lap(coord["lat"], coord["lon"])
            if result and result.get("isNationalGrid"):
                national_count += 1
        assert national_count > 0, "None of the test coordinates triggered national grid fallback"


class TestCoordinatesToLapOutOfBounds:
    @pytest.mark.parametrize("coord", OUT_OF_BOUNDS_COORDS, ids=[c["name"] for c in OUT_OF_BOUNDS_COORDS])
    def test_out_of_bounds_rejected(self, oglap_report, coord):
        result = coordinates_to_lap(coord["lat"], coord["lon"])
        assert result is None, f"{coord['name']} should be None but got {result.get('lapCode') if result else 'N/A'}"


# ════════════════════════════════════════════════════════════════════
#  Helpers to collect all generated LAP codes for later sections
# ════════════════════════════════════════════════════════════════════

def _generate_all_laps():
    """Generate LAP codes for local + national coords (run after init)."""
    results = []
    for coord in LOCAL_TEST_COORDS + NATIONAL_TEST_COORDS:
        r = coordinates_to_lap(coord["lat"], coord["lon"])
        if r:
            results.append({
                "name": coord["name"],
                "lat": coord["lat"],
                "lon": coord["lon"],
                "lap": r["lapCode"],
                "result": r,
            })
    return results


# ════════════════════════════════════════════════════════════════════
#  5. parseLapCode
# ════════════════════════════════════════════════════════════════════

class TestParseLapCode:
    def test_parse_generated_codes(self, oglap_report):
        laps = _generate_all_laps()
        assert len(laps) > 0
        for entry in laps:
            parsed = parse_lap_code(entry["lap"])
            assert parsed is not None, f'parse "{entry["lap"]}" returned None'


# ════════════════════════════════════════════════════════════════════
#  6. validateLapCode
# ════════════════════════════════════════════════════════════════════

class TestValidateLapCode:
    def test_valid_codes(self, oglap_report):
        laps = _generate_all_laps()
        for entry in laps:
            result = validate_lap_code(entry["lap"])
            assert result is None, f'validate "{entry["lap"]}" returned error: {result}'

    def test_invalid_code(self, oglap_report):
        result = validate_lap_code("QQ-ZZZ-GARBAGE")
        assert result is not None, "validate invalid should return error string, got None"


# ════════════════════════════════════════════════════════════════════
#  7. lapToCoordinates — decode LAP → GPS
# ════════════════════════════════════════════════════════════════════

class TestLapToCoordinates:
    def test_decode_all(self, oglap_report):
        """Decode all generated LAP codes back to lat/lon — just pass the LAP code string."""
        laps = _generate_all_laps()
        for entry in laps:
            parsed = parse_lap_code(entry["lap"])
            assert parsed is not None
            grid = "national" if parsed.get("isNationalGrid") else "local"
            coords = lap_to_coordinates(entry["lap"])
            assert coords is not None, f'decode "{entry["lap"]}" [{grid}] returned None'
            dist = math.sqrt((coords["lat"] - entry["lat"]) ** 2 + (coords["lon"] - entry["lon"]) ** 2)
            dist_m = dist * 111320
            # Should be within ~200m (grid quantization)
            assert dist_m < 500, f'decode "{entry["lap"]}" [{grid}] distance {dist_m:.1f}m is too large'

    def test_decode_without_country_prefix(self, oglap_report):
        """Decode a LAP code with the country prefix stripped (e.g. 'CKY-QKPC-B4A4-2798')."""
        laps = _generate_all_laps()
        cc = get_country_code()
        sample_lap = laps[0]["lap"] if laps else None
        assert sample_lap is not None, "No LAP codes generated"
        if sample_lap.startswith(cc + "-"):
            without_cc = sample_lap[len(cc) + 1:]
            coords = lap_to_coordinates(without_cc)
            assert coords is not None, f'decode without CC "{without_cc}" returned None'


# ════════════════════════════════════════════════════════════════════
#  8. getPlaceByLapCode
# ════════════════════════════════════════════════════════════════════

class TestGetPlaceByLapCode:
    def test_lookup_all(self, oglap_report):
        laps = _generate_all_laps()
        for entry in laps:
            match = get_place_by_lap_code(entry["lap"])
            # match can be None for some national grid codes, but should not throw
            # For local codes we expect a place, for national we accept parsed result
            assert match is None or isinstance(match, dict)


# ════════════════════════════════════════════════════════════════════
#  9. bboxFromGeometry & centroidFromBbox
# ════════════════════════════════════════════════════════════════════

class TestBboxAndCentroid:
    def test_bbox_and_centroid(self, oglap_report):
        places = get_oglap_places()
        sample = None
        for p in places:
            geo = p.get("geojson") or {}
            if geo.get("type") in ("Polygon", "MultiPolygon"):
                sample = p
                break
        assert sample is not None, "No polygon geometry found in places"

        bbox = bbox_from_geometry(sample["geojson"])
        assert bbox is not None
        assert len(bbox) == 4

        centroid = centroid_from_bbox(bbox)
        assert centroid is not None
        assert len(centroid) == 2


# ════════════════════════════════════════════════════════════════════
#  10. Round-trip: encode → decode → re-encode
# ════════════════════════════════════════════════════════════════════

class TestRoundTrip:
    def test_round_trip_consistency(self, oglap_report):
        """encode → decode → re-encode should produce the same LAP code."""
        laps = _generate_all_laps()
        for entry in laps:
            parsed = parse_lap_code(entry["lap"])
            assert parsed is not None
            grid = "national" if parsed.get("isNationalGrid") else "local"
            decoded = lap_to_coordinates(entry["lap"])
            assert decoded is not None, f'round-trip decode "{entry["lap"]}" [{grid}] returned None'
            re_result = coordinates_to_lap(decoded["lat"], decoded["lon"])
            assert re_result is not None, f'round-trip re-encode "{entry["lap"]}" returned None'
            re_encoded = re_result["lapCode"]
            assert re_encoded == entry["lap"], (
                '%s [%s]: encode->decode->encode mismatch: '
                '%s -> (%s,%s) -> %s' % (entry["name"], grid, entry["lap"], decoded["lat"], decoded["lon"], re_encoded)
            )

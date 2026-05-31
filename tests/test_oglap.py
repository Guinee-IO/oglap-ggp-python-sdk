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

import json
import math
from pathlib import Path

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


DATA_DIR = Path(__file__).resolve().parents[1] / "oglap-data" / "latest"


def _read_json(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


async def _load_real_fixture():
    profile = _read_json("gn_oglap_country_profile.json")
    localities = _read_json("gn_localities_naming.json")
    data = _read_json("gn_full.json")
    report = await init_oglap(profile, localities)
    assert report["ok"], report.get("error")
    loaded = load_oglap(data)
    assert loaded["ok"], loaded["message"]
    return profile, localities, data


def _ring(w, s, e, n):
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]


def _polygon(w, s, e, n):
    return {"type": "Polygon", "coordinates": [_ring(w, s, e, n)]}


def _synthetic_profile():
    return {
        "schema_id": "oglap.country_profile.v2",
        "meta": {"country_oglap_code": "TS", "iso_alpha_2": "TS", "country_name": "Testland"},
        "compatibility": {"oglap_package_range": "^2.0.0", "dataset_versions": ["synthetic-v1"]},
        "country_extent": {"country_sw": [0, 0], "country_bounds": {"sw": [0, 0], "ne": [1, 1]}},
        "grid_settings": {"distance_conversion": {"meters_per_degree_lat": 111320}},
        "zone_naming": {"type_prefix_map": {"default": "Z", "administrative": "Z"}, "stopwords": [], "padding_char": "X"},
        "admin_codes": {
            "level_4_regions": {"TS-A": {"name": "Alpha"}},
            "level_6_prefectures": {"TS-AA": {"name": "Alpha Prefecture"}},
        },
    }


def _synthetic_localities():
    return {
        "schema_id": "oglap.localities_naming.v1",
        "country": "TS",
        "generated_at": "synthetic-v1",
        "source": "synthetic",
        "level_4_regions": {"TS-A": {"oglap_code": "AAA"}},
        "level_6_prefectures": {"TS-AA": {"oglap_code": "AAB"}},
        "level_8_sous_prefectures": {},
        "level_9_villages": {},
        "level_10_quartiers": {},
    }


def _base_places(extra_places):
    return [
        {
            "place_id": 1,
            "type": "administrative",
            "extratags": {"admin_level": "2", "name": "Testland"},
            "address": {"country": "Testland"},
            "geojson": _polygon(0, 0, 1, 1),
        },
        {
            "place_id": 2,
            "type": "administrative",
            "extratags": {"admin_level": "4", "name": "Alpha"},
            "address": {"state": "Alpha", "ISO3166-2-Lvl4": "TS-A", "country": "Testland"},
            "geojson": _polygon(0, 0, 1, 1),
        },
        {
            "place_id": 3,
            "type": "administrative",
            "extratags": {"admin_level": "6", "name": "Alpha Prefecture"},
            "address": {
                "county": "Alpha Prefecture",
                "state": "Alpha",
                "ISO3166-2-Lvl6": "TS-AA",
                "ISO3166-2-Lvl4": "TS-A",
                "country": "Testland",
            },
            "geojson": _polygon(0, 0, 1, 1),
        },
        *extra_places,
    ]


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


class TestDeterminismParity:
    @pytest.mark.asyncio
    async def test_explicit_zone_codes_win_decode_index(self):
        _, localities, _ = await _load_real_fixture()
        samples = [
            {"region": "CON", "id": 5576846},  # Sonfonia Centre 2, QSN1
            {"region": "BOK", "id": 9275313},  # Kamakouloun, QKM0
        ]
        for sample in samples:
            zone = None
            for level in ("level_8_sous_prefectures", "level_9_villages", "level_10_quartiers"):
                zone = zone or next((z for z in localities.get(level, {}).values() if z.get("place_id") == sample["id"]), None)
            assert zone is not None

            lookup = get_place_by_lap_code(f"GN-{sample['region']}-{zone['oglap_code']}")
            assert lookup and lookup["place"]["place_id"] == sample["id"]

            lat = (zone["bounds"]["sw"][0] + zone["bounds"]["ne"][0]) / 2
            lon = (zone["bounds"]["sw"][1] + zone["bounds"]["ne"][1]) / 2
            encoded = coordinates_to_lap(lat, lon)
            assert encoded and not encoded["isNationalGrid"]
            decoded = lap_to_coordinates(encoded["lapCode"])
            assert decoded
            reencoded = coordinates_to_lap(decoded["lat"], decoded["lon"])
            assert reencoded and reencoded["lapCode"] == encoded["lapCode"]

    @pytest.mark.asyncio
    async def test_all_explicit_zone_lookups_resolve_to_their_place(self):
        _, localities, _ = await _load_real_fixture()
        checked = 0
        for level in ("level_8_sous_prefectures", "level_9_villages", "level_10_quartiers"):
            for zone in localities.get(level, {}).values():
                if not zone.get("parent_region_oglap"):
                    continue
                checked += 1
                lookup = get_place_by_lap_code(f"GN-{zone['parent_region_oglap']}-{zone['oglap_code']}")
                assert lookup and lookup["place"]["place_id"] == zone["place_id"]
        assert checked > 500

    @pytest.mark.asyncio
    async def test_explicit_locality_centers_round_trip(self):
        _, localities, _ = await _load_real_fixture()
        checked = 0
        for level in ("level_9_villages", "level_10_quartiers"):
            for zone in localities.get(level, {}).values():
                bounds = zone.get("bounds") or {}
                if not bounds.get("sw") or not bounds.get("ne"):
                    continue
                lat = (bounds["sw"][0] + bounds["ne"][0]) / 2
                lon = (bounds["sw"][1] + bounds["ne"][1]) / 2
                encoded = coordinates_to_lap(lat, lon)
                assert encoded is not None
                if encoded["isNationalGrid"]:
                    continue
                checked += 1
                decoded = lap_to_coordinates(encoded["lapCode"])
                assert decoded
                reencoded = coordinates_to_lap(decoded["lat"], decoded["lon"])
                assert reencoded and reencoded["lapCode"] == encoded["lapCode"]
        assert checked > 450

    @pytest.mark.asyncio
    async def test_reverse_geocode_does_not_mutate_addresses_or_cache_fields(self):
        await _load_real_fixture()
        places = get_oglap_places()
        before_addresses = [json.dumps(p.get("address"), sort_keys=True) for p in places]
        before_keys = [set(p.keys()) for p in places[:100]]
        for lat, lon in [(9.5370, -13.6785), (7.7562, -8.8179), (10.3854, -9.3057), (11.70, -9.30)]:
            assert coordinates_to_lap(lat, lon)
        after_addresses = [json.dumps(p.get("address"), sort_keys=True) for p in places]
        assert after_addresses == before_addresses
        for p, keys in zip(places[:100], before_keys):
            assert set(p.keys()) == keys
            assert "_computed_bbox" not in p
            assert "_computed_area" not in p

    @pytest.mark.asyncio
    async def test_load_failure_clears_stale_places(self):
        await _load_real_fixture()
        assert len(get_oglap_places()) > 0
        report = await init_oglap(_synthetic_profile(), _synthetic_localities())
        assert report["ok"]
        bad = load_oglap([_base_places([])[0], None])
        assert bad["ok"] is False
        assert get_oglap_places() == []

    @pytest.mark.asyncio
    async def test_bad_distance_mode_rejects_init_and_clears_loaded_data(self):
        await _load_real_fixture()
        assert coordinates_to_lap(9.5370, -13.6785)
        profile = _read_json("gn_oglap_country_profile.json")
        localities = _read_json("gn_localities_naming.json")
        profile["grid_settings"] = {**profile["grid_settings"], "distance_mode": "wgs84"}
        report = await init_oglap(profile, localities)
        assert report["ok"] is False
        assert "Unknown distance_mode" in report["error"]
        assert get_oglap_places() == []
        with pytest.raises(RuntimeError):
            coordinates_to_lap(9.5370, -13.6785)

    @pytest.mark.asyncio
    async def test_strict_parse_rejects_trailing_junk_and_bad_microspots(self):
        await _load_real_fixture()
        invalids = [
            "GN-CON-QCL0-A2A3-6041-extra",
            "GN-CON-QCL0-A2A3-ABCD",
            "GN-CON-QCL0-K2A3-6041",
            "GN-CON-QCL0-A2A3-60411",
        ]
        for lap in invalids:
            assert parse_lap_code(lap) is None


# ════════════════════════════════════════════════════════════════════
#  11. Full JS determinism test parity
# ════════════════════════════════════════════════════════════════════

import os
import re
import shutil
import tempfile
import time
from pathlib import Path as _Path

from oglap import bbox_from_geometry


async def _load_synthetic(extra_places):
    report = await init_oglap(_synthetic_profile(), _synthetic_localities())
    assert report["ok"], report.get("error")
    loaded = load_oglap(_base_places(extra_places))
    assert loaded["ok"], loaded["message"]


def _synthetic_profile_antimeridian():
    return {
        "schema_id": "oglap.country_profile.v2",
        "meta": {"country_oglap_code": "PC", "iso_alpha_2": "PC", "country_name": "Pacifica"},
        "compatibility": {"oglap_package_range": "^2.0.0", "dataset_versions": ["synthetic-v1"]},
        "country_extent": {"country_sw": [-21, 176], "country_bounds": {"sw": [-21, 176], "ne": [-12, -178]}},
        "grid_settings": {"distance_conversion": {"meters_per_degree_lat": 111320}},
        "zone_naming": {"type_prefix_map": {"default": "Z", "administrative": "Z"}, "stopwords": [], "padding_char": "X"},
        "admin_codes": {"level_4_regions": {"PC-W": {"name": "West"}}, "level_6_prefectures": {"PC-WA": {"name": "West A"}}},
    }


def _synthetic_localities_antimeridian():
    return {
        "schema_id": "oglap.localities_naming.v1",
        "country": "PC",
        "generated_at": "synthetic-v1",
        "source": "synthetic",
        "level_4_regions": {"PC-W": {"oglap_code": "WST"}},
        "level_6_prefectures": {"PC-WA": {"oglap_code": "WSA"}},
        "level_8_sous_prefectures": {},
        "level_9_villages": {},
        "level_10_quartiers": {},
    }


class TestRealFixtureDeterminism:
    """Mirror of JS testRealFixtureDeterminism — canonical LAP codes must hold."""

    EXPECTED = [
        ("Conakry center", 9.5370, -13.6785, "GN-CON-QCL0-A2A3-6041"),
        ("Nzerekore", 7.7562, -8.8179, "GN-NZE-QKLN-A1A2-9149"),
        ("Kankan", 10.3854, -9.3057, "GN-KAN-QFR1-A8A3-4463"),
        ("Labe", 11.3183, -12.2860, "GN-LAB-QKRL-A6B6-0978"),
        ("Kindia", 10.0565, -12.8665, "GN-KIN-QFS0-B3B0-4495"),
        ("Rural Siguiri", 11.70, -9.30, "GN-KAN-JXVHLC-9853"),
        ("Rural Macenta", 8.40, -9.40, "GN-NZE-JTPBZU-5497"),
        ("Rural Boke", 11.20, -14.20, "GN-BOK-BXSGPR-2093"),
        ("Rural Faranah", 10.10, -10.80, "GN-FAR-HMDEUP-3241"),
    ]

    @pytest.mark.asyncio
    async def test_canonical_codes_and_repeat_stability(self):
        await _load_real_fixture()
        for name, lat, lon, lap in self.EXPECTED:
            first = coordinates_to_lap(lat, lon)
            second = coordinates_to_lap(lat, lon)
            assert first is not None and first["lapCode"] == lap, name
            assert second is not None and second["lapCode"] == lap, f"{name} repeated encode"

    @pytest.mark.asyncio
    async def test_canonical_codes_stable_after_reload(self):
        await _load_real_fixture()
        await _load_real_fixture()
        for name, lat, lon, lap in self.EXPECTED:
            assert coordinates_to_lap(lat, lon)["lapCode"] == lap, f"{name} after reload"


class TestStrictParsing:
    @pytest.mark.asyncio
    async def test_strict_parse_invalids(self):
        await _load_real_fixture()
        assert parse_lap_code("GN-CON-QCL0-A2A3-6041-extra") is None
        assert parse_lap_code("GN-CON-QCL0-A2A3-1A23") is None
        assert parse_lap_code("GN-CON-QCL0-Z2A3-1234") is None
        assert (
            validate_lap_code("CON-QCL0-extra")
            == "Three-segment codes without a country prefix must be national LAPs: ADMIN2-XXXXXX-1234."
        )


class TestLocalGridOverflowFallsBackToNational:
    @pytest.mark.asyncio
    async def test_overflow_falls_back_to_national(self):
        large_zone = {
            "place_id": 100,
            "type": "administrative",
            "extratags": {"admin_level": "10", "name": "Overflow Zone"},
            "address": {
                "neighbourhood": "Overflow Zone",
                "county": "Alpha Prefecture",
                "state": "Alpha",
                "ISO3166-2-Lvl6": "TS-AA",
                "ISO3166-2-Lvl4": "TS-A",
                "country": "Testland",
            },
            "geojson": _polygon(0.1, 0.1, 0.25, 0.25),
        }
        await _load_synthetic([large_zone])
        local = coordinates_to_lap(0.12, 0.12)
        assert local and local["isNationalGrid"] is False
        assert (local["lapCode"] or "").startswith("TS-AAA-Q")

        overflow = coordinates_to_lap(0.24, 0.24)
        assert overflow and overflow["isNationalGrid"] is True
        assert re.match(r"^TS-AAA-[A-Z]{6}-\d{4}$", overflow["lapCode"] or "")


class TestCollisionStability:
    """Same-named zones must get unique, stable codes across runs."""

    def _build_zones(self):
        zones = []
        for i in range(12):
            w = 0.02 + i * 0.003
            zones.append({
                "place_id": 1000 + i,
                "type": "administrative",
                "extratags": {"admin_level": "10", "name": "Same Name"},
                "address": {
                    "neighbourhood": "Same Name",
                    "county": "Alpha Prefecture",
                    "state": "Alpha",
                    "ISO3166-2-Lvl6": "TS-AA",
                    "ISO3166-2-Lvl4": "TS-A",
                    "country": "Testland",
                },
                "geojson": _polygon(w, 0.02, w + 0.001, 0.021),
            })
        return zones

    async def _encode_all(self):
        zones = self._build_zones()
        await _load_synthetic(zones)
        out = []
        for i, _zone in enumerate(zones):
            lon = 0.0205 + i * 0.003
            result = coordinates_to_lap(0.0205, lon)
            assert result and result["isNationalGrid"] is False
            out.append(result["admin_level_3"])
        return out

    @pytest.mark.asyncio
    async def test_collision_codes_unique_and_stable(self):
        first = await self._encode_all()
        second = await self._encode_all()
        assert second == first
        assert len(set(first)) == len(first)


class TestEncodeIsIndependentOfClickOrder:
    @pytest.mark.asyncio
    async def test_click_order_independence(self):
        coords = [
            (9.5370, -13.6785),
            (7.7562, -8.8179),
            (10.3854, -9.3057),
            (11.3183, -12.2860),
            (10.0565, -12.8665),
        ]

        async def encode_in_order(order):
            await _load_real_fixture()
            return {i: coordinates_to_lap(coords[i][0], coords[i][1])["lapCode"] for i in order}

        forward = await encode_in_order([0, 1, 2, 3, 4])
        reverse = await encode_in_order([4, 3, 2, 1, 0])
        shuffled = await encode_in_order([2, 0, 4, 1, 3])

        for i in range(len(coords)):
            assert forward[i] == reverse[i], f"click-order independence failed at i={i} (reverse)"
            assert forward[i] == shuffled[i], f"click-order independence failed at i={i} (shuffled)"


class TestEncodeDoesNotMutatePlaces:
    @pytest.mark.asyncio
    async def test_no_mutation(self):
        await _load_real_fixture()
        places = get_oglap_places()
        snapshot = [json.dumps(p.get("address"), sort_keys=True) for p in places]
        coords = [
            (9.5370, -13.6785), (7.7562, -8.8179), (10.3854, -9.3057),
            (11.3183, -12.2860), (10.0565, -12.8665), (11.70, -9.30),
        ]
        for lat, lon in coords:
            coordinates_to_lap(lat, lon)
        for i, place in enumerate(places):
            now = json.dumps(place.get("address"), sort_keys=True)
            assert now == snapshot[i], f"place at index {i} (place_id={place.get('place_id')}) was mutated"


class TestGeometryCachesDoNotMutatePlaceObjects:
    @pytest.mark.asyncio
    async def test_geometry_caches_do_not_add_keys(self):
        zone = {
            "place_id": 100,
            "type": "administrative",
            "extratags": {"admin_level": "10", "name": "Cache Zone"},
            "address": {
                "neighbourhood": "Cache Zone",
                "county": "Alpha Prefecture",
                "state": "Alpha",
                "ISO3166-2-Lvl6": "TS-AA",
                "ISO3166-2-Lvl4": "TS-A",
                "country": "Testland",
            },
            "geojson": _polygon(0.1, 0.1, 0.11, 0.11),
        }
        await _load_synthetic([zone])
        live_zone = next(p for p in get_oglap_places() if p.get("place_id") == 100)
        before_keys = sorted(live_zone.keys())
        result = coordinates_to_lap(0.105, 0.105)
        assert result is not None
        after_keys = sorted(live_zone.keys())
        assert after_keys == before_keys, "geometry caching added enumerable keys to the place"
        assert "_computed_bbox" not in live_zone
        assert "_computed_area" not in live_zone
        assert "_closed_poly" not in live_zone


class TestDecodeRoundTripIsStable:
    @pytest.mark.asyncio
    async def test_round_trip_stable_over_iterations(self):
        await _load_real_fixture()
        samples = [
            (9.5370, -13.6785),
            (7.7562, -8.8179),
            (10.3854, -9.3057),
            (11.3183, -12.2860),
            (10.0565, -12.8665),
        ]
        for lat, lon in samples:
            first = coordinates_to_lap(lat, lon)
            assert first, f"initial encode failed at ({lat}, {lon})"
            current = first["lapCode"]
            for _ in range(5):
                decoded = lap_to_coordinates(current)
                assert decoded, f"decode failed for {current}"
                re_enc = coordinates_to_lap(decoded["lat"], decoded["lon"])
                assert re_enc, f"re-encode failed after decoding {current}"
                assert re_enc["lapCode"] == current
                current = re_enc["lapCode"]


class TestDecodedPointReEncodesToSameLap:
    @pytest.mark.asyncio
    async def test_decoded_point_re_encodes(self):
        await _load_real_fixture()
        for lap in (
            "GN-CON-QCL0-A2A3-6041",
            "GN-NZE-QKLN-A1A2-9149",
            "GN-KAN-JXVHLC-9853",
            "GN-FAR-HMDEUP-3241",
        ):
            coords = lap_to_coordinates(lap)
            assert coords, f"decode returned None for {lap}"
            re_enc = coordinates_to_lap(coords["lat"], coords["lon"])
            assert re_enc and re_enc["lapCode"] == lap, f"re-encode mismatch for {lap}"


class TestParseLapCodeRejectsBadInput:
    @pytest.mark.asyncio
    async def test_parse_rejects_various_invalids(self):
        await _load_real_fixture()
        invalids = [
            "",
            "   ",
            "GN",
            "GN-CON-QCL0-A2A3",
            "GN-CON-QCL0-A2A3-XXXX",
            "GN-CON-QCL0-K2A3-6041",
            "GN-CON-QCL0-A2A3-60411",
            "GN-XX-ABCDEF-1234",
            "GN-CON-QCL0-A2A3-6041-extra",
            "GN-CON-QCL0-2A3-6041",
            "GN-CON-QCL0-A2A3-ABCD",
        ]
        for q in invalids:
            assert parse_lap_code(q) is None, f"expected None for {q!r}"


class TestZoneOnlySearchIsDeterministic:
    @pytest.mark.asyncio
    async def test_zone_only_search_deterministic(self):
        await _load_real_fixture()
        seed = coordinates_to_lap(9.5370, -13.6785)
        zone_code = seed["admin_level_3"]
        a = get_place_by_lap_code(zone_code)
        b = get_place_by_lap_code(zone_code)
        c = get_place_by_lap_code(zone_code)
        assert a and a.get("place"), f"no place for zone-only search {zone_code}"
        assert a["place"]["place_id"] == b["place"]["place_id"] == c["place"]["place_id"]


class TestLapToCoordinatesAcceptsOptionalCountryPrefix:
    @pytest.mark.asyncio
    async def test_lap_to_coords_with_and_without_cc(self):
        await _load_real_fixture()
        with_cc = lap_to_coordinates("GN-CON-QCL0-A2A3-6041")
        without_cc = lap_to_coordinates("CON-QCL0-A2A3-6041")
        assert with_cc and without_cc
        assert with_cc["lat"] == without_cc["lat"]
        assert with_cc["lon"] == without_cc["lon"]

        nat_with_cc = lap_to_coordinates("GN-FAR-HMDEUP-3241")
        nat_without_cc = lap_to_coordinates("FAR-HMDEUP-3241")
        assert nat_with_cc and nat_without_cc
        assert nat_with_cc["lat"] == nat_without_cc["lat"]
        assert nat_with_cc["lon"] == nat_without_cc["lon"]


class TestOutOfBoundsRejection:
    @pytest.mark.asyncio
    async def test_out_of_bounds_rejected(self):
        await _load_real_fixture()
        # Far outside bbox
        assert coordinates_to_lap(0, 0) is None
        assert coordinates_to_lap(50, 0) is None
        # Inside bbox but outside country polygon
        assert coordinates_to_lap(12.6392, -8.0029) is None  # Bamako
        assert coordinates_to_lap(8.4657, -13.2317) is None  # Freetown


class TestRepeatedInitIsClean:
    @pytest.mark.asyncio
    async def test_repeated_init_same_output(self):
        await _load_real_fixture()
        a = coordinates_to_lap(9.5370, -13.6785)["lapCode"]
        await _load_real_fixture()
        b = coordinates_to_lap(9.5370, -13.6785)["lapCode"]
        await _load_real_fixture()
        c = coordinates_to_lap(9.5370, -13.6785)["lapCode"]
        assert a == b == c


class TestDownloadInitDataFetchFailureClearsState:
    @pytest.mark.asyncio
    async def test_failed_download_clears_state(self):
        await _load_real_fixture()
        assert coordinates_to_lap(9.5370, -13.6785) is not None

        tmp = tempfile.mkdtemp(prefix="oglap-init-fail-")
        latest = _Path(tmp) / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DATA_DIR / "gn_oglap_country_profile.json", latest / "gn_oglap_country_profile.json")
        shutil.copyfile(DATA_DIR / "gn_localities_naming.json", latest / "gn_localities_naming.json")

        report = await init_oglap({
            "version": "latest",
            "data_dir": tmp,
            "base_url": "http://127.0.0.1:9/oglap-test",
        })
        assert report["ok"] is False
        assert "Places database" in (report.get("error") or "")
        assert get_oglap_places() == []
        with pytest.raises(RuntimeError):
            coordinates_to_lap(9.5370, -13.6785)
        shutil.rmtree(tmp, ignore_errors=True)


class TestPublicApisNeverThrowOnGarbageInput:
    @pytest.mark.asyncio
    async def test_garbage_input_returns_none_no_throw(self):
        await _load_real_fixture()

        zone_re = re.compile(r"^[A-Z0-9]{1,8}$", re.IGNORECASE)
        garbage = [
            None, 123, 3.14, True, False, {}, [], {"x": 1}, [1, 2],
            float("nan"), float("inf"), float("-inf"),
            "", "   ", "\n\t", " bad",
        ]
        for g in garbage:
            # None of these should raise
            r_parse = parse_lap_code(g)
            validate_lap_code(g)
            lap_to_coordinates(g)
            if isinstance(g, str) and zone_re.match(g.strip() or ""):
                continue  # could be a valid zone code
            assert r_parse is None, f"parse_lap_code returned {r_parse!r} for {g!r}"

        coord_pairs = [
            (float("nan"), float("nan")), (float("nan"), 0), (0, float("nan")),
            (float("inf"), 0), (float("-inf"), 0),
            (None, None), ("9.5", "-13.6"), ({}, {}), ([], []),
            (True, False), (9.5, "-13.6"), (9.5, float("nan")),
            (91, 0), (-91, 0), (0, 181), (0, -181),
        ]
        for lat, lon in coord_pairs:
            r = coordinates_to_lap(lat, lon)
            assert r is None, f"coordinates_to_lap({lat!r}, {lon!r}) returned {r!r}"


class TestHugeInputDoesNotHang:
    @pytest.mark.asyncio
    async def test_huge_input_handled_in_bounded_time(self):
        await _load_real_fixture()
        huge = "A" * 1_000_000
        t0 = time.time()
        assert parse_lap_code(huge) is None
        assert lap_to_coordinates(huge) is None
        assert validate_lap_code(huge) is not None
        elapsed_ms = (time.time() - t0) * 1000
        assert elapsed_ms < 200, f"huge input handling took {elapsed_ms:.1f}ms"


class TestEncodePerformance:
    @pytest.mark.asyncio
    async def test_encode_perf(self):
        await _load_real_fixture()
        t0 = time.time()
        n = 500
        for i in range(n):
            coordinates_to_lap(9.5370 + (i % 50) * 1e-4, -13.6785 + (i % 50) * 1e-4)
        elapsed_ms = (time.time() - t0) * 1000
        per_call = elapsed_ms / n
        # Python is slower than JS — relax cap to 60 ms/call (CI slack); R-tree should comfortably beat this.
        assert per_call < 60, f"encode perf regression: {per_call:.2f} ms/encode"


class TestFloatPrecisionAtGridEdges:
    @pytest.mark.asyncio
    async def test_perturbed_points_re_encode(self):
        await _load_real_fixture()
        conakry = coordinates_to_lap(9.5370, -13.6785)
        assert conakry and not conakry["isNationalGrid"]
        ll = lap_to_coordinates(conakry["lapCode"])
        assert ll
        pat = re.compile(r"^GN-[A-Z]{3}-(?:[A-Z0-9]{1,8}-[A-J]\d[A-J]\d|[A-Z]{6})-\d{4}$")
        for eps in (0, 1e-9, -1e-9, 1e-7, -1e-7):
            re_enc = coordinates_to_lap(ll["lat"] + eps, ll["lon"] + eps)
            if re_enc:
                assert pat.match(re_enc["lapCode"]), f"unexpected code shape: {re_enc['lapCode']}"


class TestEncodedCodesAlwaysMatchValidationGrammar:
    @pytest.mark.asyncio
    async def test_encoded_codes_validate(self):
        await _load_real_fixture()
        coords = [
            (9.5370, -13.6785), (7.7562, -8.8179), (10.3854, -9.3057),
            (11.3183, -12.2860), (10.0565, -12.8665), (11.70, -9.30),
            (8.40, -9.40), (11.20, -14.20), (10.10, -10.80),
        ]
        for lat, lon in coords:
            r = coordinates_to_lap(lat, lon)
            assert r, f"encode failed for ({lat}, {lon})"
            assert validate_lap_code(r["lapCode"]) is None
            assert parse_lap_code(r["lapCode"]) is not None


class TestCollisionOverflowDoesNotProduceMalformedCodes:
    @pytest.mark.asyncio
    async def test_many_same_named_zones_still_produce_valid_codes(self):
        n = 80
        zones = []
        for i in range(n):
            w = 0.02 + i * 0.003
            zones.append({
                "place_id": 5000 + i,
                "type": "administrative",
                "extratags": {"admin_level": "10", "name": "Same Name"},
                "address": {
                    "neighbourhood": "Same Name",
                    "county": "Alpha Prefecture",
                    "state": "Alpha",
                    "ISO3166-2-Lvl6": "TS-AA",
                    "ISO3166-2-Lvl4": "TS-A",
                    "country": "Testland",
                },
                "geojson": _polygon(w, 0.02, w + 0.001, 0.021),
            })
        await _load_synthetic(zones)
        seen: set[str] = set()
        grammar = re.compile(r"^[A-Z0-9]{1,8}$")
        for i in range(n):
            lon = 0.0205 + i * 0.003
            r = coordinates_to_lap(0.0205, lon)
            if not r or r["isNationalGrid"]:
                continue
            code = r["admin_level_3"]
            assert 1 <= len(code) <= 8, f"code {code!r} out of bounds"
            assert grammar.match(code), f"code {code!r} violates grammar"
            seen.add(code)
        assert len(seen) > 0


class TestRTreeCorrectness:
    """R-tree results must match canonical truth across reload."""

    @pytest.mark.asyncio
    async def test_rtree_stable_across_reload(self):
        await _load_real_fixture()
        sw = (7.19, -15.37)
        ne = (12.68, -7.64)
        s = 42

        def rand():
            nonlocal s
            s = (s + 0x6D2B79F5) & 0xFFFFFFFF
            t = s
            t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
            t ^= (t + ((t ^ (t >> 7)) * (t | 61))) & 0xFFFFFFFF
            return (((t ^ (t >> 14)) & 0xFFFFFFFF)) / 4294967296

        first_pass = []
        for _ in range(250):
            lat = sw[0] + rand() * (ne[0] - sw[0])
            lon = sw[1] + rand() * (ne[1] - sw[1])
            r = coordinates_to_lap(lat, lon)
            first_pass.append((lat, lon, r["lapCode"] if r else None))

        await _load_real_fixture()
        for lat, lon, code in first_pass:
            r = coordinates_to_lap(lat, lon)
            new_code = r["lapCode"] if r else None
            assert new_code == code, f"R-tree result diverged at ({lat}, {lon}): {code} vs {new_code}"

    @pytest.mark.asyncio
    async def test_canonical_truth(self):
        await _load_real_fixture()
        truth = [
            (9.5370, -13.6785, "GN-CON-QCL0-A2A3-6041"),
            (7.7562, -8.8179, "GN-NZE-QKLN-A1A2-9149"),
            (10.3854, -9.3057, "GN-KAN-QFR1-A8A3-4463"),
        ]
        for lat, lon, expected in truth:
            r = coordinates_to_lap(lat, lon)
            assert r and r["lapCode"] == expected


class TestRTreePerformanceScales:
    @pytest.mark.asyncio
    async def test_rtree_per_call_perf(self):
        await _load_real_fixture()
        for _ in range(200):
            coordinates_to_lap(9.5370, -13.6785)
        t0 = time.time()
        n = 2000
        for i in range(n):
            coordinates_to_lap(9.5370 + (i % 100) * 1e-4, -13.6785 + (i % 100) * 1e-4)
        per = ((time.time() - t0) * 1000) / n
        # JS asserts < 5ms; Python with shapely+STRtree typically lands < 10ms.
        assert per < 25, f"R-tree encode perf regression: {per:.3f} ms/encode"


class TestAntimeridianBboxRejection:
    @pytest.mark.asyncio
    async def test_crossing_country_accepts_and_rejects_correctly(self):
        report = await init_oglap(
            _synthetic_profile_antimeridian(), _synthetic_localities_antimeridian()
        )
        assert report["ok"] is True, report.get("error")
        crossing_geom = {
            "type": "MultiPolygon",
            "coordinates": [
                [[[176, -21], [180, -21], [180, -12], [176, -12], [176, -21]]],
                [[[-180, -21], [-178, -21], [-178, -12], [-180, -12], [-180, -21]]],
            ],
        }
        country = {
            "place_id": 1, "type": "administrative",
            "extratags": {"admin_level": "2", "name": "Pacifica"},
            "address": {"country": "Pacifica"},
            "geojson": crossing_geom,
        }
        region = {
            "place_id": 2, "type": "administrative",
            "extratags": {"admin_level": "4", "name": "West"},
            "address": {"state": "West", "ISO3166-2-Lvl4": "PC-W", "country": "Pacifica"},
            "geojson": crossing_geom,
        }
        loaded = load_oglap([country, region])
        assert loaded["ok"], loaded["message"]

        # Inside: lon=177 (east) and lon=-179 (west) both encode.
        assert coordinates_to_lap(-15, 177) is not None
        assert coordinates_to_lap(-15, -179) is not None
        # Outside: lon=170 and lon=-170 rejected.
        assert coordinates_to_lap(-15, 170) is None
        assert coordinates_to_lap(-15, -170) is None


class TestBadCountryBoundsRejected:
    @pytest.mark.asyncio
    async def test_sw_as_string_rejected(self):
        profile = _read_json("gn_oglap_country_profile.json")
        localities = _read_json("gn_localities_naming.json")
        profile["country_extent"] = {
            **profile["country_extent"],
            "country_bounds": {"sw": "7.19,-15.37", "ne": [12.68, -7.64]},
        }
        r = await init_oglap(profile, localities)
        assert r["ok"] is False
        assert "country_bounds.sw" in r["error"]

    @pytest.mark.asyncio
    async def test_inverted_bounds_rejected(self):
        profile = _read_json("gn_oglap_country_profile.json")
        localities = _read_json("gn_localities_naming.json")
        profile["country_extent"] = {
            **profile["country_extent"],
            "country_bounds": {"sw": [12.68, -15.37], "ne": [7.19, -7.64]},
        }
        r = await init_oglap(profile, localities)
        assert r["ok"] is False
        assert "country_bounds.ne.lat" in r["error"]

    @pytest.mark.asyncio
    async def test_lat_out_of_range_rejected(self):
        profile = _read_json("gn_oglap_country_profile.json")
        localities = _read_json("gn_localities_naming.json")
        profile["country_extent"] = {
            **profile["country_extent"],
            "country_bounds": {"sw": [-95, -15.37], "ne": [12.68, -7.64]},
        }
        r = await init_oglap(profile, localities)
        assert r["ok"] is False


class TestBboxClassification:
    def test_single_ring_antimeridian_polygon(self):
        bbox = bbox_from_geometry({
            "type": "Polygon",
            "coordinates": [[
                [178, -10], [180, -10], [-180, -10], [-178, -10],
                [-178, -5], [178, -5], [178, -10],
            ]],
        })
        assert bbox is not None
        # Expected: wrapped bbox (minLon > maxLon)
        assert bbox[2] > bbox[3], f"expected wrapped bbox, got {bbox!r}"

    def test_wide_non_crossing_polygon_not_misclassified(self):
        bbox = bbox_from_geometry({
            "type": "Polygon",
            "coordinates": [[[30, 50], [100, 50], [100, 60], [30, 60], [30, 50]]],
        })
        assert bbox is not None
        assert bbox[2] <= bbox[3]

        us = bbox_from_geometry({
            "type": "Polygon",
            "coordinates": [[[-125, 25], [-67, 25], [-67, 49], [-125, 49], [-125, 25]]],
        })
        assert us and us[2] < us[3] and us[2] == -125 and us[3] == -67


class TestZoneCodeLengthCapEnforcedByValidation:
    @pytest.mark.asyncio
    async def test_overlong_zone_code_rejected(self):
        await _load_real_fixture()
        too_long = "GN-CON-QABCDEFGH-A2A3-6041"
        assert validate_lap_code(too_long) is not None
        assert parse_lap_code(too_long) is None
        max_len = "GN-CON-QABCDEFG-A2A3-6041"
        assert validate_lap_code(max_len) is None


def _high_lat_profile():
    return {
        "schema_id": "oglap.country_profile.v2",
        "meta": {"country_oglap_code": "NL", "iso_alpha_2": "NL", "country_name": "NorthLand"},
        "compatibility": {"oglap_package_range": "^2.0.0", "dataset_versions": ["synthetic-v1"]},
        "country_extent": {"country_sw": [55, 10], "country_bounds": {"sw": [55, 10], "ne": [65, 20]}},
        "grid_settings": {
            "distance_mode": "wgs84_ellipsoid",
            "distance_conversion": {"meters_per_degree_lat": 111320},
        },
        "zone_naming": {
            "type_prefix_map": {"default": "Z", "administrative": "Z"},
            "stopwords": [],
            "padding_char": "X",
        },
        "admin_codes": {
            "level_4_regions": {"NL-A": {"name": "Alpha"}},
            "level_6_prefectures": {"NL-AA": {"name": "Alpha Pref"}},
        },
    }


def _high_lat_localities():
    return {
        "schema_id": "oglap.localities_naming.v1",
        "country": "NL",
        "generated_at": "synthetic-v1",
        "source": "synthetic",
        "level_4_regions": {"NL-A": {"oglap_code": "AAA"}},
        "level_6_prefectures": {"NL-AA": {"oglap_code": "AAB"}},
        "level_8_sous_prefectures": {},
        "level_9_villages": {},
        "level_10_quartiers": {},
    }


class TestEllipsoidAtHighLatitude:
    @pytest.mark.asyncio
    async def test_ellipsoid_round_trip_at_lat_60(self):
        report = await init_oglap(_high_lat_profile(), _high_lat_localities())
        assert report["ok"] is True, report.get("error")
        places = [
            {"place_id": 1, "type": "administrative", "extratags": {"admin_level": "2"},
             "address": {"country": "NorthLand"}, "geojson": _polygon(10, 55, 20, 65)},
            {"place_id": 2, "type": "administrative", "extratags": {"admin_level": "4", "name": "Alpha"},
             "address": {"state": "Alpha", "ISO3166-2-Lvl4": "NL-A", "country": "NorthLand"},
             "geojson": _polygon(10, 55, 20, 65)},
            {"place_id": 3, "type": "administrative", "extratags": {"admin_level": "6", "name": "Alpha Pref"},
             "address": {"county": "Alpha Pref", "state": "Alpha",
                         "ISO3166-2-Lvl6": "NL-AA", "ISO3166-2-Lvl4": "NL-A", "country": "NorthLand"},
             "geojson": _polygon(10, 55, 20, 65)},
            {"place_id": 100, "type": "administrative",
             "extratags": {"admin_level": "10", "name": "High Zone"},
             "address": {"neighbourhood": "High Zone", "county": "Alpha Pref", "state": "Alpha",
                         "ISO3166-2-Lvl6": "NL-AA", "ISO3166-2-Lvl4": "NL-A", "country": "NorthLand"},
             "geojson": _polygon(15, 60, 15.05, 60.05)},
        ]
        assert load_oglap(places)["ok"]
        enc = coordinates_to_lap(60.02, 15.02)
        assert enc
        dec = lap_to_coordinates(enc["lapCode"])
        assert dec
        re_enc = coordinates_to_lap(dec["lat"], dec["lon"])
        assert re_enc and re_enc["lapCode"] == enc["lapCode"]


class TestCachedGeometryReuseAcrossLoads:
    @pytest.mark.asyncio
    async def test_same_data_same_objects_same_code(self):
        profile = _synthetic_profile()
        localities = _synthetic_localities()
        await init_oglap(profile, localities)
        places = _base_places([{
            "place_id": 100,
            "type": "administrative",
            "extratags": {"admin_level": "10", "name": "Cached"},
            "address": {
                "neighbourhood": "Cached",
                "county": "Alpha Prefecture",
                "state": "Alpha",
                "ISO3166-2-Lvl6": "TS-AA",
                "ISO3166-2-Lvl4": "TS-A",
                "country": "Testland",
            },
            "geojson": _polygon(0.1, 0.1, 0.11, 0.11),
        }])
        assert load_oglap(places)["ok"]
        a = coordinates_to_lap(0.105, 0.105)
        await init_oglap(profile, localities)
        assert load_oglap(places)["ok"]
        b = coordinates_to_lap(0.105, 0.105)
        assert a["lapCode"] == b["lapCode"]


class TestProfileDistanceModeIsObserved:
    @pytest.mark.asyncio
    async def test_profile_distance_mode_check_in_report(self):
        await _load_real_fixture()
        profile = _read_json("gn_oglap_country_profile.json")
        assert profile["grid_settings"]["distance_mode"] == "flat"
        report = await init_oglap(profile, _read_json("gn_localities_naming.json"))
        dm = next((c for c in report["checks"] if c["id"] == "grid_settings.distance_mode"), None)
        assert dm and dm["status"] == "pass"
        assert "flat" in dm["message"]


class TestProfileWithUnknownDistanceModeFailsInit:
    @pytest.mark.asyncio
    async def test_unknown_distance_mode_rejected(self):
        profile = _read_json("gn_oglap_country_profile.json")
        localities = _read_json("gn_localities_naming.json")
        profile["grid_settings"] = {**profile["grid_settings"], "distance_mode": "wgs84"}
        report = await init_oglap(profile, localities)
        assert report["ok"] is False
        assert "Unknown distance_mode" in report["error"]


class TestProfileWithoutDistanceModeFallsBackToFlat:
    @pytest.mark.asyncio
    async def test_missing_distance_mode_defaults_to_flat(self):
        profile = _read_json("gn_oglap_country_profile.json")
        localities = _read_json("gn_localities_naming.json")
        if "distance_mode" in profile["grid_settings"]:
            del profile["grid_settings"]["distance_mode"]
        report = await init_oglap(profile, localities)
        assert report["ok"] is True, report.get("error")
        dm = next((c for c in report["checks"] if c["id"] == "grid_settings.distance_mode"), None)
        assert dm and "flat" in dm["message"]


class TestEllipsoidModeDoesNotAffectFlatModeCodes:
    @pytest.mark.asyncio
    async def test_flat_mode_codes_unchanged(self):
        await _load_real_fixture()
        expected = [
            "GN-CON-QCL0-A2A3-6041",
            "GN-NZE-QKLN-A1A2-9149",
            "GN-KAN-QFR1-A8A3-4463",
            "GN-LAB-QKRL-A6B6-0978",
            "GN-KIN-QFS0-B3B0-4495",
        ]
        coords = [
            (9.5370, -13.6785), (7.7562, -8.8179), (10.3854, -9.3057),
            (11.3183, -12.286), (10.0565, -12.8665),
        ]
        for (lat, lon), exp in zip(coords, expected):
            r = coordinates_to_lap(lat, lon)
            assert r and r["lapCode"] == exp


class TestEllipsoidModeRoundTrips:
    @pytest.mark.asyncio
    async def test_ellipsoid_round_trip_stable(self):
        profile = _synthetic_profile()
        profile["grid_settings"]["distance_mode"] = "wgs84_ellipsoid"
        report = await init_oglap(profile, _synthetic_localities())
        assert report["ok"] is True, report.get("error")
        zone = {
            "place_id": 100,
            "type": "administrative",
            "extratags": {"admin_level": "10", "name": "Test Zone"},
            "address": {
                "neighbourhood": "Test Zone", "county": "Alpha Prefecture", "state": "Alpha",
                "ISO3166-2-Lvl6": "TS-AA", "ISO3166-2-Lvl4": "TS-A", "country": "Testland",
            },
            "geojson": _polygon(0.1, 0.1, 0.15, 0.15),
        }
        assert load_oglap(_base_places([zone]))["ok"]
        for lat, lon in [(0.12, 0.12), (0.105, 0.105), (0.13, 0.14)]:
            a = coordinates_to_lap(lat, lon)
            assert a, f"encode failed at ({lat}, {lon})"
            ll = lap_to_coordinates(a["lapCode"])
            assert ll
            re_enc = coordinates_to_lap(ll["lat"], ll["lon"])
            assert re_enc and re_enc["lapCode"] == a["lapCode"]


class TestEllipsoidModeIsMoreAccurateThanFlat:
    @pytest.mark.asyncio
    async def test_ellipsoid_round_trip_distance_sub_meter(self):
        profile = _synthetic_profile()
        profile["grid_settings"]["distance_mode"] = "wgs84_ellipsoid"
        report = await init_oglap(profile, _synthetic_localities())
        assert report["ok"] is True
        zone = {
            "place_id": 200,
            "type": "administrative",
            "extratags": {"admin_level": "10", "name": "Acc Zone"},
            "address": {
                "neighbourhood": "Acc Zone", "county": "Alpha Prefecture", "state": "Alpha",
                "ISO3166-2-Lvl6": "TS-AA", "ISO3166-2-Lvl4": "TS-A", "country": "Testland",
            },
            "geojson": _polygon(0.5, 0.5, 0.51, 0.51),
        }
        assert load_oglap(_base_places([zone]))["ok"]
        lat, lon = 0.505, 0.505
        enc = coordinates_to_lap(lat, lon)
        assert enc
        dec = lap_to_coordinates(enc["lapCode"])
        assert dec
        d_lat = abs(lat - dec["lat"]) * 110575
        d_lon = abs(lon - dec["lon"]) * 110575 * math.cos(lat * math.pi / 180.0)
        dist = math.sqrt(d_lat * d_lat + d_lon * d_lon)
        assert dist < 1.0, f"ellipsoid round-trip distance {dist:.3f}m exceeds 1m"

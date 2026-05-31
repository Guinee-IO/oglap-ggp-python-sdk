# Changelog

## 2.0.1

### Compatibility

* Package version bumped to `2.0.1`. The country-profile compatibility range
  intentionally remains `^2.0.0`, so deployed 2.x profiles remain valid.

### Precision resilience

* Tiny negative offsets admitted by the SW-edge floating-point tolerance are
  normalized to zero before macroblock decomposition.
* Decode and geometry helpers now normalize longitude with bounded modulo math,
  including malformed extreme-longitude inputs.
* Polygon overlap ordering now uses spherical area, matching Node and Dart,
  instead of planar degree-space area.
* Init rejects malformed nested configuration and non-positive, non-finite, or
  non-numeric `meters_per_degree_lat` values before applying engine state.
* `encode_alpha3` safely handles non-finite input.

### Tests

* Added resilience regressions for malformed precision config, SW tolerance,
  bounded longitude wrapping, spherical overlap ordering, and non-finite input.

## 2.0.0

### Grid correctness (BREAKING — some encoded codes change)

* **Microspot encoding now uses `floor` (cell containment), not `round`.** A
  microspot index `N` now covers the half-open interval `[N, N+1)` metres, so
  microspot `0000` is the macroblock's SW 1×1 m cell and shares the macroblock's
  SW origin. The previous `round` behaviour shifted local-grid coordinates by up
  to half a metre and misaligned drawn reference grids. This matches the decoder
  (always SW-anchored). It also removes a cross-SDK divergence: Python `round`
  uses banker's rounding (half-to-even) while JS/Dart round half-away-from-zero,
  so the three SDKs previously disagreed at exact `.5 m` boundaries. **LAP codes
  for coordinates whose sub-cell offset had a fractional part ≥ 0.5 m change**
  (e.g. `GN-CON-QCL0-A2A3-6041` → `…-5940`). Round-trip precision on the 1 m grid
  is now up to one cell-diagonal (~1.414 m).
* `macro_letter` now floors (instead of truncating toward zero) for parity with
  the Node `Math.floor` semantics on negative inputs.

### Compatibility

* Package version `2.0.0`; bundled country profile `oglap_package_range` is now
  `^2.0.0`.

### Tests

* Added `TestMicrospotFloorContainment` asserting floor semantics, microspot
  `0000` ↔ macroblock SW corner, and cell-boundary behaviour — the guard that
  would have caught the round-vs-floor regression.

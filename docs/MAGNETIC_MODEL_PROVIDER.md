# Magnetic Model Provider Contract

## Purpose

Define the first adapter boundary for turning observing location/time into
magnetic correction data. The first real provider should target WMM2025, using
GeographicLib `MagneticField` or NOAA/NCEI reference code in a later spike.

## Request

`MagneticModelRequest` fields:

- `latitude_deg`
- `longitude_deg`
- `elevation_m`
- `timestamp_utc`
- `elevation_reference`, default `WGS84_ELLIPSOID`

The request must not include private labels such as home address, observing
site name, or raw device identifiers. Coordinates are enough.

## Result

`MagneticModelResult` fields:

- `model_name`
- `model_version`
- `valid_from`
- `valid_until`
- `source`
- `declination_deg`
- `inclination_deg`
- `field_vector_nt`
- `annual_change`
- `uncertainty`

Declination is east-positive. The alignment model uses:

```text
true_azimuth = magnetic_azimuth + declination
```

## WMM2025 Fixture Contract

The fixture contract for WMM2025-like results requires:

- Model identity starts with `WMM2025`.
- Validity includes the 2025-2030 epoch and expires no later than
  `2029-12-31` for this project.
- Declination and inclination are finite degrees.
- Field vector includes north/east/down components in nanotesla.
- Annual change includes at least declination change when available.
- Uncertainty includes declination uncertainty.

The current fixtures are synthetic and privacy-safe. They are not authoritative
NOAA/NCEI test values and must not be used to validate numerical WMM
correctness.

## Provider Rules

- Providers must be offline by default.
- Providers must report source/version/validity metadata with each result.
- Providers must reject or clearly warn outside the model validity window.
- Providers must avoid logging raw coordinates by default.
- Network calculators are reference tools only, not runtime dependencies.

## GeographicLib Spike

`GeographicLibMagneticFieldProvider` wraps the external `MagneticField`
executable. It calls:

```text
MagneticField -n wmm2025 -r -p 8
```

The request is sent on standard input as:

```text
YYYY-MM-DD latitude longitude height_m
```

The adapter parses GeographicLib's documented two-line output: the first line
contains declination, inclination, horizontal field, north/east/down components,
and total field; the second line contains annual rates of change.

This adapter is optional. If `MagneticField` or its WMM2025 model data is not
installed, the provider fails clearly instead of falling back to a network
service.

## GeographicLib Integration Test

The real `MagneticField` integration test is opt-in. Default test runs skip it
so unit tests remain offline, fast, and independent of local package state.

Run it only on a machine where GeographicLib's `MagneticField` executable and
WMM2025 magnetic model data are installed:

```bash
ASTRO_TRUE_NORTH_RUN_GEOGRAPHICLIB_TESTS=1 scripts/check.sh
```

Optional environment variables:

- `ASTRO_TRUE_NORTH_MAGNETICFIELD_EXECUTABLE`: path or command name for the
  real `MagneticField` executable.
- `ASTRO_TRUE_NORTH_GEOGRAPHICLIB_MAGNETIC_MODEL_DIR`: model data directory to
  pass to `MagneticField -d`.

The test uses fixed synthetic coordinates at latitude `0.0`, longitude `0.0`,
elevation `0.0`, and date `2025-01-01`. It validates adapter execution,
WMM2025 metadata, output parsing, and finite field values without using private
observing coordinates.

Install the external dependency through the operating-system package or the
official GeographicLib installation path that provides `MagneticField`, then
install or point at the WMM2025 magnetic model data before enabling the test.

## Epoch Update Check

`check_model_epoch` classifies model validity as:

- `current`: more than the warning window remains before expiry.
- `update_due`: the model is still valid, but expiry is within the warning
  window.
- `expired`: the checked date is after `valid_until`.

The default warning window is 365 days. For WMM2025, that means the project
should start warning on 2029-01-01 and must not silently use the model after
2029-12-31.

# Plate Solver Contract

Astro True North treats plate solving as an adapter boundary. The project owns
the request/result shape; external solvers such as local `astrometry.net`
`solve-field`, ASTAP, or later native libraries can be wrapped behind it.

## Adapter Interface

`astro_true_north.plate_solving` defines:

- `CameraFrame`: privacy-safe metadata for an image or frame handle.
- `PlateSolverRequest`: a frame plus optional field-of-view, pixel-scale, and
  approximate sky-coordinate hints.
- `PlateSolution`: normalized solver output with status, RA/Dec, frame,
  observation time, confidence, solver identity, field-of-view, pixel scale,
  and failure reason.
- `PlateSolver`: protocol for adapters that implement
  `solve(request) -> PlateSolution`.
- `FixturePlateSolver`: deterministic fixture-backed solver for tests.
- `AstrometryNetSolveFieldProvider`: subprocess adapter for a local
  astrometry.net `solve-field` executable.
- `AstapPlateSolverProvider`: subprocess adapter for a local ASTAP or
  `astap_cli` executable.

The adapter boundary is intentionally smaller than any single solver's native
API. Real solver wrappers should normalize their output into this shape and
hide command-specific files, logs, and temporary paths from the alignment
engine.

## Mock Solver Fixture Contract

The synthetic fixture contract uses `tests/fixtures/sensor_samples.json`.

Camera frame records must include:

- Stable `id`.
- `timestamp_utc`.
- Privacy-safe `source_handle`.
- `privacy_policy`.
- Exposure metadata.
- Pixel width and height.

Solved plate records must include:

- `frame_id` linking the solution to a frame.
- `solver_name` and `solver_version`.
- `status`, currently `solved` or `failed`.
- ICRS `ra_deg` and `dec_deg` for solved records.
- `obstime`.
- Positive `field_of_view_deg` and `pixel_scale_arcsec` when known.
- `confidence`.
- `failure_reason`, which must be `null` for solved records and present for
  failed records.

`FixturePlateSolver` returns fixture solutions by frame id and returns a clear
failed `PlateSolution` when no fixture exists.

## Privacy And Operations

Plate-solving adapters must not log raw image paths, precise observing
locations, or image content by default. Real solver adapters should use an
explicit temporary working directory, enforce timeouts, avoid network access
unless explicitly configured, and report solver/index provenance in normalized
metadata.

Default tests use only synthetic frame handles and normalized fixture data.
Real solver tests should be opt-in because local index files, executable
availability, and solve speed are machine-specific.

## Local Astrometry.net Adapter

`AstrometryNetSolveFieldProvider` wraps a local `solve-field` executable. It
uses a private temporary directory for solver output, calls the executable with
plots disabled, applies a CPU limit from `PlateSolverRequest.timeout_s`, and
normalizes successful WCS output into `PlateSolution`.

Supported request hints:

- `field_of_view_hint_deg`: passed as a degree-width scale range.
- `pixel_scale_hint_arcsec`: passed as an arcsec-per-pixel scale range when no
  field-of-view hint is supplied.
- `approximate_ra_deg`, `approximate_dec_deg`, and
  `search_radius_hint_deg`: passed as sky-position search hints when both
  coordinates are present.

The adapter reports normalized failures instead of raising for missing
executables, solver process failures, timeouts, or missing solved/WCS outputs.
It redacts the raw frame path from `command_summary`.

Current tests use a fake `solve-field` executable that writes a solved marker
and minimal WCS FITS header. A real `solve-field` plus index-file integration
test should be opt-in because install paths, indexes, and solve time vary by
machine.

## Astrometry.net Integration Test

The real `solve-field` integration test is opt-in. Default test runs skip it
so unit tests do not depend on local astrometry.net packages, index files, or a
real sky image.

Run it only on a machine with local astrometry.net, appropriate index files,
and a public or synthetic test image:

```bash
ASTRO_TRUE_NORTH_RUN_SOLVE_FIELD_TESTS=1 \
ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_IMAGE=/path/to/public-test-image.fits \
scripts/check.sh
```

Optional environment variables:

- `ASTRO_TRUE_NORTH_SOLVE_FIELD_EXECUTABLE`: path or command name for
  `solve-field`.
- `ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_FOV_DEG`: field-of-view hint in degrees.
- `ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_PIXEL_SCALE_ARCSEC`: pixel-scale hint,
  used when no FOV hint is provided.
- `ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_RA_DEG` and
  `ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_DEC_DEG`: approximate sky-position hint.
- `ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_RADIUS_DEG`: search radius for the
  approximate sky-position hint.
- `ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_TIMEOUT_S`: solver timeout in seconds.

Do not point the test at private observing images. Use a public sample image or
an intentionally synthetic local image with known provenance.

## ASTAP Adapter Comparison

`AstapPlateSolverProvider` wraps ASTAP's local command-line solver behind the
same `PlateSolver` boundary as `solve-field`. ASTAP is treated as an optional
external executable and is not vendored.

The adapter builds the ASTAP command-line form documented by the project:

- `-f`: local image file to solve.
- `-r`: search radius in degrees.
- `-fov`: image-height field-of-view hint in degrees. When the generic request
  FOV describes the longer image edge, the adapter converts it to ASTAP's image
  height convention.
- `-ra`: approximate right ascension in hours.
- `-spd`: south-pole distance, computed as declination plus 90 degrees.
- `-z 0`: automatic downsampling by default.
- `-s 500`: maximum stars to use by default.
- `-wcs`: request FITS-standard WCS output.
- `-o`: isolated temporary output base path.

Optional constructor settings can pass an ASTAP star database path/name with
`-d` and `-D`.

The adapter parses ASTAP `.wcs` output into `PlateSolution` and reads the
`.ini` sidecar for solved/failed status, database provenance, and error text.
It reports normalized failures for missing executables, process failures,
timeouts, and missing solved output. Like the astrometry.net adapter, it
redacts the raw frame path from `command_summary`.

Current tests use a fake ASTAP executable against the same contract fixtures.
Real ASTAP/database integration should be opt-in because install paths,
database downloads, and solve time vary by machine.

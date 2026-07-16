# Architecture Overview

## System Summary

Astro True North will estimate telescope pointing from coarse local sensors,
then refine the pointing solution through camera plate solving. The first
architecture should remain modular so hardware adapters, plate solvers, and
mount-control integrations can be swapped as the project learns what works.

## Context

- Observer starts alignment and approves any movement.
- Location/time provider supplies latitude, longitude, elevation, and time.
- Compass provides rough magnetic heading.
- Inclinometer provides altitude/elevation angle.
- Magnetic model converts magnetic reference toward true north.
- Astro camera provides frames for final solving.
- Plate solver returns sky coordinates from camera imagery.
- Optional mount adapter reads or writes mount pointing state.

## Components

| Component | Responsibility | Owner | Notes |
| --- | --- | --- | --- |
| Input adapters | Read GPS, compass, inclinometer, camera, and optional mount state. | Project | Start with file/mock adapters before hardware-specific code. |
| Magnetic correction | Convert magnetic heading to true-north estimate for the observing location. | Project | First model source is WMM2025; wrap an offline model provider and record validity/uncertainty. |
| Coordinate model | Convert sensor readings and time/location into estimated sky pointing. | Project | Prefer mature astronomy libraries. |
| Plate-solving adapter | Submit camera frames to a selected solver and normalize results. | Project | First spike wraps local `astrometry.net` / `solve-field`; ASTAP is the first comparison adapter. |
| Alignment engine | Compare rough estimate with solved pointing and generate correction/model update. | Project | Preserve uncertainty and confidence. |
| Operator workflow | Present simple setup, progress, success, and failure states. | Project | Child-friendly by design, not by stickers. |

## Data Model

- Observing site: latitude, longitude, optional elevation, timestamp, and source
  such as GPS, phone location, saved site, mount metadata, or manual entry.
- Sensor sample: source, value, units, calibration state, uncertainty, timestamp.
- Magnetic correction: model source/version, declination/vector result, date.
- Camera frame: source handle, exposure metadata, solve status.
- Plate solution: RA/Dec or equivalent sky coordinates, field-of-view, confidence.
- Alignment result: estimated pointing, solved pointing, correction vector,
  confidence, operator-visible status.
- Alignment math: see `docs/MATH_MODEL.md` for the first location/time plus
  azimuth/altitude plus plate-solution comparison model.
- Alignment pipeline: `astro_true_north.pipeline` wires fixture input records,
  a `PlateSolver`, and the alignment math into a privacy-safe pointing-delta
  report.
- Operator workflow: `astro_true_north.workflow` defines stable setup/result
  states and short recovery messages for family-friendly operation.
- WT901 hardware sampler: `astro_true_north.wt901` decodes live 0x55-frame
  UART packets into roll, pitch, yaw, and raw magnetometer summaries for the
  first compass/inclinometer bring-up path.
- BN-220 GPS sampler: `astro_true_north.bn220` decodes NMEA RMC/GGA sentences
  into fix status, GPS time, coarse rounded location, satellite count, HDOP,
  and altitude summaries.
- WT901 calibration/error-budget workflow: `astro_true_north.wt901` estimates
  stationary jitter, observed motion spans, magnetic magnitude variation, and
  conservative first-pass compass/inclinometer uncertainties.
- Magnetic model provider: see `docs/MAGNETIC_MODEL_PROVIDER.md` for the
  WMM2025 adapter boundary and fixture contract.
- Plate solver: see `docs/PLATE_SOLVER.md` for the solver adapter boundary and
  synthetic fixture contract.

## APIs / Integrations

- Location/time input: GPS, phone location, saved observing site, mount
  metadata, or manual entry.
- First live GPS target: Beitian BN-220 over USB TTL UART. See
  `docs/HARDWARE_BRINGUP.md` for confirmed wire colours, smoke tests, and the
  first no-fix capture summary.
- Compass/inclinometer input: hardware adapter or recorded test samples.
- First live compass/inclinometer target: WitMotion WT901 over USB TTL UART.
  See `docs/HARDWARE_BRINGUP.md` for wiring, smoke tests, and the first
  capture summary.
- Magnetic model: first spike uses WMM2025 via an offline provider, preferably
  GeographicLib `MagneticField` or NOAA/NCEI reference code. WMMHR2025 is a
  later accuracy comparison, and IGRF-14 is a reference/historical model. The
  provider interface and model-epoch update check live in
  `astro_true_north.magnetic`.
- Camera input: still frames or stream adapter.
- Plate solving: first spike uses local `astrometry.net` / `solve-field` as an
  optional external executable. ASTAP is now wrapped as the first comparison
  adapter behind the same project-owned boundary, so solver behavior can be
  compared without changing the alignment engine. The adapter protocol and
  fixture-backed test solver live in `astro_true_north.plate_solving`.
- Mount control: deferred until the alignment math and solving loop are proven.

The current CLI can run the synthetic fixture pipeline with
`--fixture-pipeline tests/fixtures/sensor_samples.json`, and can sample the
first live WT901 hardware target with `--sample-wt901 /dev/ttyUSB0` and the
first live BN-220 GPS target with `--sample-bn220 /dev/ttyUSB1`.
It can also run the first stationary WT901 error-budget capture with
`--calibrate-wt901 /dev/ttyUSB0`.

Operator-facing states and failure messages are documented in
`docs/OPERATOR_WORKFLOW.md`.

## Trust Boundaries

- Observing location and camera images may reveal private observing location or
  environment details.
- Magnetic-model queries use precise observing coordinates and timestamps; keep
  them local/offline by default and avoid logging raw coordinates.
- Any future cloud solving mode crosses a privacy boundary and must be explicit.
- Any future mount-control mode crosses a physical safety boundary.

## Runtime / Deployment Model

The first implementation is a Python CLI/library prototype. Python is the
starting point because it has strong astronomy tooling, supports fast sensor
mocking, and keeps plate-solving adapter spikes straightforward. Native/mobile
or embedded forms can follow after the alignment model is proven.

## Product Operational Estate

The repository is a Python CLI/library prototype. Public issue tracking,
release packaging, and hardware-test contribution guidance should be defined
before the first packaged release.

## Observability

For the prototype, keep structured logs for input samples, correction data,
solver attempts, solve results, and failure reasons. Avoid precise GPS in logs
unless explicitly enabled.

## Failure Modes and Recovery

- Compass disturbed by mount hardware or local magnetic fields.
- Inclinometer miscalibrated or mounted on a flexing component.
- Location/time unavailable or inaccurate.
- Magnetic model unavailable, stale, or license-constrained.
- Magnetic model within update window or past validity expiry.
- Plate solver fails due to clouds, focus, exposure, narrow field, or bad
  camera metadata.
- Mount-control integration points in the wrong direction; keep movement
  disabled until modeled and tested.

## Tradeoffs / Alternatives

- Sensor-first alignment should reduce friction but depends on calibration and
  magnetic environment quality.
- Plate solving is robust for final correction but may require decent focus,
  exposure, and star visibility.
- Offline-first operation protects privacy but may increase dependency and data
  packaging complexity.
- Calling a GPL-licensed solver as an optional external tool keeps early
  prototype integration simple; vendoring or linking solver code would need a
  separate license review.
- Astropy should own coordinate transforms for the first prototype; hand-rolled
  astronomy math is deferred unless a bounded spike proves a specific need.

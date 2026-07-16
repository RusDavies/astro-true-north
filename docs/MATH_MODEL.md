# Alignment Math Model

## Purpose

Define the first alignment model for turning observing location/time, compass azimuth,
inclinometer altitude, WMM2025 magnetic correction, and a plate-solved camera
frame into a measured pointing delta.

This is the first prototype model, not a final mount model. It should prove the
data flow, coordinate frames, uncertainty bookkeeping, and correction reporting
before any hardware movement is allowed.

## Coordinate Conventions

- Angles are degrees unless a field explicitly says otherwise.
- Azimuth is measured clockwise from true north in the local horizon frame.
- Altitude is measured above the local horizon.
- Magnetic declination is east-positive. In this convention:
  `true_azimuth = magnetic_azimuth + magnetic_declination`.
- Normalize azimuth into `[0, 360)`.
- Normalize signed azimuth deltas into `[-180, 180]`.
- Timestamps are UTC instants.
- Latitude and longitude are WGS 84 geodetic coordinates.
- Elevation is meters above the WGS 84 ellipsoid unless the input adapter says
  otherwise.

The sign convention for magnetic declination needs a fixture test before real
hardware use. A wrong sign can be a beautifully consistent way to point the
telescope in the wrong direction.

## Inputs

### Observing Site

- `latitude_deg`
- `longitude_deg`
- `elevation_m`
- `timestamp_utc`
- `location_precision`
- `privacy_policy`

### Compass Sample

- `magnetic_azimuth_deg`
- `calibration_state`
- `uncertainty_deg`
- `timestamp_utc`
- `sensor_mount_offset_deg`
- `hard_iron_soft_iron_notes`

### Inclinometer Sample

- `altitude_deg`
- `calibration_state`
- `uncertainty_deg`
- `timestamp_utc`
- `sensor_mount_offset_deg`

### Magnetic Correction

- `declination_deg`
- `inclination_deg`
- `field_vector`
- `annual_change`
- `uncertainty`
- `model_name`
- `model_version`
- `validity_range`

### Plate Solution

- `ra_deg`
- `dec_deg`
- `frame`
- `obstime`
- `field_of_view`
- `pixel_scale`
- `confidence`
- `solver_name`
- `solver_version`
- `failure_reason`

The first prototype treats the plate-solved camera center as the authoritative
actual pointing direction. If the camera optical axis is not the same as the
telescope optical axis, a boresight calibration offset must be applied before
comparing the rough estimate with the solve.

## Rough Pointing Estimate

1. Validate that site, compass, inclinometer, magnetic correction, and time are
   from compatible timestamps.
2. Apply compass calibration and sensor mount offset:

   ```text
   corrected_magnetic_azimuth =
       magnetic_azimuth_deg
       + compass_sensor_mount_offset_deg
       + compass_calibration_offset_deg
   ```

3. Convert magnetic azimuth to true azimuth:

   ```text
   rough_true_azimuth =
       normalize_360(corrected_magnetic_azimuth + magnetic_declination_deg)
   ```

4. Apply inclinometer calibration and sensor mount offset:

   ```text
   rough_altitude =
       inclinometer_altitude_deg
       + inclinometer_sensor_mount_offset_deg
       + inclinometer_calibration_offset_deg
   ```

5. Clamp or reject impossible altitude values outside the physical range.
6. Create an Astropy `AltAz` coordinate for the rough pointing using
   `EarthLocation`, `Time`, and the observer site.
7. Transform that coordinate to the chosen sky frame, initially ICRS.

The first model should use Astropy for coordinate transforms rather than
project-owned spherical astronomy code.

## Plate-Solved Actual Pointing

1. Normalize the solver result into a `PlateSolution`.
2. Convert the solver output into the same comparison frame as the rough
   pointing estimate, initially ICRS.
3. Also transform the solved coordinate into the same local `AltAz` frame for
   operator-readable azimuth/altitude deltas.

## Correction Output

The alignment result should include:

- `estimated_pointing_icrs`
- `solved_pointing_icrs`
- `estimated_pointing_altaz`
- `solved_pointing_altaz`
- `sky_separation_deg`
- `sky_position_angle_deg`
- `local_azimuth_delta_deg`
- `local_altitude_delta_deg`
- `confidence`
- `uncertainty_summary`
- `status`
- `operator_message`

The prototype should compute:

```text
sky_separation = estimated_icrs.separation(solved_icrs)
sky_position_angle = estimated_icrs.position_angle(solved_icrs)
local_azimuth_delta = signed_angle_delta(solved_altaz.az, estimated_altaz.az)
local_altitude_delta = solved_altaz.alt - estimated_altaz.alt
```

The local azimuth/altitude deltas are easier to present to an operator. The
sky separation and position angle are better for model fitting and regression
tests.

`astro_true_north.pipeline` now wires this flow into a prototype pipeline:

1. Load privacy-safe site, sensor, camera-frame, magnetic-correction, and
   fixture plate-solution records.
2. Submit the camera frame through a `PlateSolver`.
3. Pass the solved `PlateSolution` into `calculate_alignment`.
4. Report a concise estimated-vs-solved pointing delta without printing the
   precise observing coordinates or raw image path.

The CLI can run the synthetic fixture pipeline:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --fixture-pipeline tests/fixtures/sensor_samples.json
```

## Uncertainty Model

The first implementation preserves uncertainty rather than pretending to solve
it perfectly.

Track these contributors:

- Observing location uncertainty.
- Time uncertainty.
- Compass raw accuracy.
- Compass calibration state and local magnetic disturbance.
- Magnetic model uncertainty.
- Inclinometer accuracy and calibration state.
- Camera/OTA boresight calibration.
- Plate-solver confidence and pixel scale.
- Atmospheric refraction assumption.

Initial propagation can be conservative and metadata-based:

- Report component uncertainties separately.
- Mark the result `rough`, `solved`, `degraded`, or `failed`.
- Use the largest expected contributors for operator messaging.
- Add Monte Carlo or local-linear covariance propagation only after fixture
  tests and real sensor data exist.

## Refraction And Atmosphere

The first model should run with no atmospheric refraction correction unless
atmospheric pressure/temperature inputs are available and deliberately enabled.
Record this as a systematic approximation, especially at low altitude.

## Failure Conditions

Return a clear failure instead of a correction when:

- Required site/time data is missing.
- Magnetic model date is outside its valid range.
- Compass or inclinometer calibration is unknown and strict mode is enabled.
- Rough altitude is outside the physical range.
- Plate solving fails.
- Plate-solver output lacks enough metadata for comparison.
- Camera/OTA boresight is unknown in a mode that requires it.

## First Test Fixtures

The first fixture set should include:

- Known site/time plus magnetic declination sign test.
- A rough azimuth/altitude pair transformed to ICRS.
- A synthetic plate solution offset by a small known azimuth/altitude delta.
- A wraparound azimuth case near 0/360 degrees.
- A low-altitude case that records the no-refraction approximation.

The initial synthetic fixtures live in `tests/fixtures/`. They are deliberately
privacy-safe and do not contain real observing locations or image data.

## Sources

- Astropy coordinates overview:
  https://docs.astropy.org/en/stable/coordinates/index.html
- Astropy coordinate transforms:
  https://docs.astropy.org/en/latest/coordinates/transforming.html
- Astropy `AltAz` frame:
  https://docs.astropy.org/en/stable/api/astropy.coordinates.AltAz.html
- Astropy separation and position angle helpers:
  https://docs.astropy.org/en/stable/coordinates/matchsep.html

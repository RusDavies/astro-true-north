# Operator Workflow

Astro True North should feel like a short setup flow, not a quiz about star
names. The first workflow vocabulary is deliberately plain: it tells the
operator what is happening, what to do next, and when movement is still locked.

## Workflow States

The prototype defines these stable state IDs in `astro_true_north.workflow`:

- `start_setup`: set the telescope down safely and confirm it is stable.
- `check_location_time`: check observing place and time from GPS, saved site,
  or manual entry.
- `check_sensors`: check compass and tilt readings, away from metal and power
  cables.
- `capture_frame`: take a focused sky image.
- `solve_frame`: match the image to the sky map.
- `report_delta`: show the estimated-vs-solved pointing correction.
- `ready_to_adjust`: correction is ready for operator review.

Only `ready_to_adjust` allows future mount movement, and even there the next
action says the operator must approve movement. Hardware motion stays locked
until a later mount-control design adds explicit approval and stop controls.

## Failure Messages

Failure messages use stable codes and recovery actions:

- `missing_location_time`: choose GPS, a saved site, or manual site entry.
- `magnetic_model_unavailable`: check that the magnetic model is installed and
  valid.
- `compass_uncalibrated`: calibrate away from metal, motors, and cables.
- `tilt_out_of_range`: check sensor mounting and retry.
- `plate_solver_missing`: install the selected solver or use the fixture
  solver.
- `plate_solver_timeout`: improve focus, shorten the search radius, or wait
  for clearer sky.
- `plate_solver_failed`: check focus, clouds, lens cap, exposure, and take
  another image.
- `unsafe_mount_motion_locked`: review the correction and approve any movement
  manually.

The text should stay short, calm, and recoverable. Avoid expert-only language
in operator-facing strings unless the detail is needed for the next action.

## Pipeline Integration

`run_alignment_pipeline` now maps plate-solver failures into these operator
messages. Successful solves report:

```text
Sky check complete. Correction: azimuth +1.25 deg, altitude -0.50 deg.
Review it before moving anything.
```

The detailed report can still include RA/Dec and sky-separation values for
debugging, but the operator message should lead with the local correction and
the review-before-motion rule.

# Calibration And Error Budget

## Purpose

The first calibration workflow estimates practical sensor uncertainty before
those values are fed into the alignment pipeline. It does not certify the
sensor as calibrated. It records evidence, recommends conservative uncertainty
inputs, and flags captures that moved too much to be useful as stationary
samples.

## WT901 Stationary Capture

Run a stationary WT901 capture with:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --calibrate-wt901 /dev/ttyUSB0 \
  --wt901-duration 15
```

Keep the unit still until the capture finishes.

The workflow reports:

- Angle-frame and magnetometer-frame counts.
- Stationary roll, pitch, and yaw jitter.
- Observed roll, pitch, and yaw spans.
- Magnetometer magnitude variation.
- Recommended first-pass compass and inclinometer uncertainty values.

## First Live Result

On 2026-07-15, a 15-second stationary WT901 capture over `/dev/ttyUSB0`
produced:

- 301 decoded samples.
- 151 angle frames.
- 150 magnetometer frames.
- Roll jitter: 0.007 degrees.
- Pitch jitter: 0.001 degrees.
- Yaw jitter: 0.000 degrees.
- Roll span: 0.02 degrees.
- Pitch span: 0.01 degrees.
- Yaw span: 0.00 degrees.
- Magnetometer magnitude variation: 2.2%.
- Recommended compass uncertainty: 2.0 degrees.
- Recommended inclinometer uncertainty: 0.5 degrees.

These are stationary bench values. They are not yet telescope-mounted values.
The compass uncertainty should remain conservative until captures are repeated
near the real mount, camera, batteries, cables, and any steel hardware.

## Follow-Up Captures

The next calibration work should capture:

- WT901 stationary on the telescope or intended mounting bracket.
- WT901 near powered camera and GPS cabling.
- WT901 after a deliberate magnetometer calibration routine, if supported.
- A slow yaw sweep to observe heading continuity and local magnetic distortion.

Only after mounted magnetic disturbance is measured should the project compare
whether WMMHR2025 improves the total practical heading budget.

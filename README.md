# astro-true-north

## Purpose

Astro True North is an open-source software project for automatic telescope
alignment. The core idea is to make initial alignment approachable, fast, and
child-friendly by combining rough sensor-based pointing with final camera-based
plate solving.

The first useful outcome is a documented alignment model and prototype flow
that can estimate where the telescope is pointed from:

- Observing location and time, from GPS or another location/time source.
- A scope-mounted compass for rough azimuth.
- A scope-mounted inclinometer for altitude.
- Magnetic declination/vector data to infer true north from magnetic north.
- An astro camera stream for fine plate-solving correction.

## Product Shape

This is intended to become public/open-source software under the MIT license.

The early project emphasis is on correctness and usability before hardware
polish:

- Define the coordinate transforms and calibration assumptions.
- Identify practical sensor error budgets.
- Choose a plate-solving integration path.
- Build a small proof-of-concept alignment pipeline.
- Keep the operator workflow simple enough for a child-assisted setup.

## Prototype Platform

The first prototype is a Python CLI/library. Python is the starting point
because the astronomy ecosystem is strong there and it keeps early coordinate
math, sensor mocks, and plate-solving adapter spikes easy to test.

## Repository Map

- `docs/PRODUCT_BRIEF.md`: product framing and user problem.
- `docs/GOAL.md`: concrete project goal and success criteria.
- `docs/REQUIREMENTS.md`: initial functional and non-functional requirements.
- `docs/ARCHITECTURE.md`: first-pass system architecture.
- `docs/MATH_MODEL.md`: first alignment math model and coordinate conventions.
- `docs/MAGNETIC_MODEL_PROVIDER.md`: magnetic correction adapter contract.
- `docs/PLATE_SOLVER.md`: plate-solving adapter and fixture contract.
- `docs/OPERATOR_WORKFLOW.md`: child-friendly workflow states and recovery
  messages.
- `docs/HARDWARE_BRINGUP.md`: first WT901 USB-UART wiring, smoke test, and
  live sampler notes.
- `docs/CALIBRATION_ERROR_BUDGET.md`: WT901 stationary calibration workflow and
  first error-budget capture.
- `LICENSE`: MIT license.
- `src/astro_true_north/`: Python package, including first alignment math,
  magnetic model provider boundary, plate-solving adapter boundary, and
  prototype alignment pipeline.
- `tests/`: stdlib smoke tests and synthetic fixture validation.
- `tests/fixtures/`: privacy-safe mock sensor and alignment math fixtures.

## Verification

Run:

```bash
scripts/check.sh
```

Try the current placeholder CLI with:

```bash
PYTHONPATH=src python -m astro_true_north.cli --version
```

Run the current synthetic fixture pipeline with:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --fixture-pipeline tests/fixtures/sensor_samples.json
```

Sample a live WT901 over USB UART with:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --sample-wt901 auto \
  --wt901-duration 20
```

Sample a live BN-220 GPS over USB UART with:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --sample-bn220 auto \
  --gps-duration 20
```

Run the first WT901 stationary error-budget capture with:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --calibrate-wt901 auto \
  --wt901-duration 15
```

When multiple serial adapters are attached, inspect the detected streams with:

```bash
PYTHONPATH=src python -m astro_true_north.cli --discover-serial
```

Read basic Celestron NexStar hand-controller status without moving the mount:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --nexstar-status /dev/ttyUSB2
```

Validate a guarded slow-yaw plan without sending motor commands:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --plan-nexstar-slow-yaw right \
  --nexstar-yaw-rate-deg-sec 0.2 \
  --nexstar-yaw-duration 10 \
  --approve-mount-motion \
  --mount-abort-ready
```

The current prototype deliberately does not emit NexStar motor commands.

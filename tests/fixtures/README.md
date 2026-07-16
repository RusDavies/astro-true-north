# Test Fixtures

These fixtures are synthetic and intentionally privacy-safe. They exercise the
shape of the first prototype inputs and the deterministic math conventions
before real sensors, real observing sites, or real plate-solver output are
introduced.

- `sensor_samples.json`: mock observing site, compass, inclinometer, camera
  frame, magnetic correction, and plate-solution records. The camera and
  plate-solution records satisfy the mock `PlateSolver` fixture contract in
  `docs/PLATE_SOLVER.md`, and the same file drives the prototype alignment
  pipeline fixture.
- `alignment_math_cases.json`: deterministic cases for magnetic declination
  sign, azimuth wraparound, local azimuth/altitude deltas, and low-altitude
  no-refraction metadata.

Do not replace these with private observing locations or real images. Add new
real-world evidence under a separate opt-in fixture policy when the project is
ready for field data.

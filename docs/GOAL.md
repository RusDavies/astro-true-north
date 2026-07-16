# Goal

Create open-source software that can automatically align a telescope using a
short, friendly workflow instead of traditional two-star or three-star manual
alignment.

## Target Outcome

Given observing location, time, rough azimuth from a scope-mounted compass,
altitude from a scope-mounted inclinometer, and an astro camera stream, the
software should guide or drive the telescope to a reliable sky model alignment.
Magnetic declination/vector-map data should be used to translate magnetic north
into true north for the current observing location.

## Success Criteria

- A user can set up the telescope without manually identifying alignment stars.
- The system can obtain a rough pointing estimate from observing location/time,
  compass, and inclinometer inputs.
- The system can refine pointing through plate solving from the camera stream.
- The alignment process is understandable and low-friction for a family/child
  assisted observing session.
- The design records sensor assumptions, error budgets, and fallback behavior
  clearly enough to support real hardware testing.

## Non-Goals For The First Prototype

- Building custom telescope motor-control hardware.
- Supporting every mount protocol on day one.
- Replacing mature plate solvers with a from-scratch solver.
- Claiming precision without measured field tests.

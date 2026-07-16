# Product Brief

## Summary

Astro True North is open-source telescope alignment software that combines
location, orientation sensors, magnetic model correction, and camera plate
solving to automate telescope alignment.

## Problem

Traditional two-star and three-star telescope alignment is slow, fussy, and not
especially child-friendly. It assumes the operator can identify stars, center
targets accurately, and tolerate a workflow that feels more like a ritual than
an observing session.

The project should make alignment more automatic: use sensors for the rough
pointing estimate, then use an astro camera and plate solving for final
correction.

## Goals

- Reduce or remove manual star-identification alignment steps.
- Use observing location/time, compass, inclinometer, and magnetic
  vector/declination data for fast coarse alignment.
- Use camera-based plate solving for fine alignment and sky-model correction.
- Keep the setup workflow accessible for families and young observers.
- Build on established astronomy/plate-solving tools instead of inventing weak
  versions of hard solved problems.

## Non-Goals

- First release support for every commercial mount.
- A custom hardware product or packaged electronics board.
- Safety-critical autonomous slewing without operator override.
- Offline global magnetic-model distribution decisions before licensing and
  data-size tradeoffs are understood.

## Users / Stakeholders

- User or role: amateur astronomer setting up a telescope.
- User or role: parent/child observing team.
- Stakeholder: open-source maintainers and hardware testers.

## Current Alternatives

Manual mount alignment, polar alignment tools, planetarium software, electronic
assisted astronomy workflows, and plate-solving utilities all solve pieces of
the problem. The gap is a friendly full alignment flow that starts from rough
consumer-grade orientation sensors and ends with camera-confirmed sky
alignment.

## Competitive Landscape

- Alternative: manual two-star/three-star alignment.
  - What it solves: mount sky-model initialization.
  - Where it wins: no extra hardware beyond normal setup.
  - Where it falls short: unfriendly, slow, star-knowledge dependent.
- Alternative: plate-solving-assisted astrophotography stacks.
  - What it solves: accurate pointing refinement.
  - Where it wins: mature solving and imaging workflows.
  - Where it falls short: often assumes a more technical user and a partially
    aligned mount.
- Differentiation hypothesis: a sensor-first, plate-solve-final workflow can
  make alignment feel like setup automation instead of astronomy homework.
- Evidence gathered: initial project discussion, early hardware tests, and
  source research on magnetic models, coordinate transforms, and plate-solving
  integrations.

## Assumptions

- Observing location and time are available from GPS, phone location, a saved
  observing site, mount metadata, or manual entry.
- A mounted compass and inclinometer can provide a useful coarse pointing
  estimate after calibration.
- Magnetic declination/vector-map data can improve true-north estimation enough
  for rough pointing.
- Plate solving is the authoritative final correction step.

## Unknowns

- Which mount protocol should be targeted first, if any.
- Expected compass/inclinometer accuracy near typical telescope hardware.
- Whether the first user-facing prototype after the CLI/library should be
  desktop, mobile, embedded, or service/library oriented.

## Security / Privacy Notes

Observing location can be sensitive. The default design should avoid
unnecessary cloud transmission of precise observing locations and should make
any network dependency explicit.

## Operational Notes

Early operation is local development and field testing. Before any packaged
public release, define supported platforms, dependency update expectations,
hardware safety boundaries, and a clear issue-reporting path.

## Release Notes

The project is pre-alpha. Before a packaged release, define supported platforms,
dependency update expectations, hardware safety boundaries, and a clear
issue-reporting path.

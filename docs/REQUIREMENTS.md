# Requirements Spec

## Scope

Initial software design and prototype for automatic telescope alignment using
sensor-assisted rough pointing and camera-based plate-solving refinement.

## Out of Scope

- Custom motor-control hardware.
- Unsupported autonomous slewing without a user-visible stop/override.
- Production packaging or mobile app store release in the first prototype.

## Users / Roles

- Role: observer
- Permissions: can provide/approve GPS location, start alignment, stop motion,
  and review alignment result.
- Needs: fast setup, minimal astronomy jargon, clear failure recovery.

## Functional Requirements

| ID | Requirement | Acceptance Criteria | Priority |
| --- | --- | --- | --- |
| FR-1 | Accept observing location and current time as alignment inputs. | The alignment model can run from provided latitude, longitude, elevation when available, and timestamp; GPS is one provider, not the only source. | Must |
| FR-2 | Accept rough azimuth from a scope-mounted compass. | The system records compass heading, calibration status, and uncertainty. | Must |
| FR-3 | Accept altitude/inclination from a scope-mounted inclinometer. | The system records inclination, calibration status, and uncertainty. | Must |
| FR-4 | Correct magnetic north toward true north using location-aware magnetic data. | The design uses WMM2025 first, records model version/validity/uncertainty, and applies declination/vector correction for the GPS location. | Must |
| FR-5 | Use an astro camera stream/image for plate-solving refinement. | A captured frame can be passed to a selected plate solver and return sky coordinates or a clear failure. | Must |
| FR-6 | Produce an alignment correction or mount-model update. | The prototype can report the delta between estimated pointing and solved pointing. | Should |
| FR-7 | Provide a child-friendly alignment flow. | The main flow avoids expert-only star identification steps and gives stable setup/result states plus simple recovery messages. | Should |

## Non-Functional Requirements

| ID | Requirement | Acceptance Criteria | Priority |
| --- | --- | --- | --- |
| NFR-1 | Prefer established astronomy libraries for plate solving and coordinate transforms. | Architecture records selected libraries and rejected alternatives. | Must |
| NFR-4 | Keep the first alignment math model source-grounded and fixture-testable. | `docs/MATH_MODEL.md` defines coordinate conventions, input/output fields, correction calculations, uncertainty handling, and first fixtures. | Must |
| NFR-2 | Work without sending precise location or images to a cloud service by default. | Any network dependency is optional and documented. | Should |
| NFR-3 | Preserve sensor uncertainty through the model. | Error/uncertainty notes are recorded with each input source. | Should |

## Security Requirements

| ID | Requirement | Acceptance Criteria | Priority |
| --- | --- | --- | --- |
| SEC-1 | Avoid unsafe mount movement. | Any future motor-control integration includes explicit stop/abort controls and movement limits. | Must |

## Privacy / Data Requirements

| ID | Requirement | Acceptance Criteria | Priority |
| --- | --- | --- | --- |
| PRIV-1 | Treat observing location as private by default. | Logs and bug reports avoid precise location unless the user explicitly includes it. | Must |
| PRIV-2 | Keep magnetic-model coordinate lookups offline by default. | Magnetic correction does not require sending precise location/time to a network service. | Should |

## Operational Requirements

| ID | Requirement | Acceptance Criteria | Priority |
| --- | --- | --- | --- |
| OPS-1 | Maintain reproducible setup and verification. | `scripts/check.sh` passes and documents current validation coverage. | Must |
| OPS-2 | Use Python CLI/library as the first prototype platform. | Repository contains a minimal Python package scaffold and smoke test. | Must |

## Open Questions

- Which mount family/protocol should be the first integration target?
- How much calibration does a practical scope-mounted compass need around metal,
  motors, and power cables?

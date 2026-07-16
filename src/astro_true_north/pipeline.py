"""Prototype alignment pipeline wiring sensors, solving, and delta reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from astro_true_north.alignment import (
    AlignmentResult,
    CompassSample,
    InclinometerSample,
    MagneticCorrection,
    ObservingSite,
    calculate_alignment,
)
from astro_true_north.plate_solving import (
    CameraFrame,
    FixturePlateSolver,
    PlateSolution,
    PlateSolver,
    PlateSolverRequest,
    camera_frame_from_record,
    plate_solution_from_record,
)
from astro_true_north.workflow import (
    classify_plate_solver_failure,
    pointing_correction_message,
)


@dataclass(frozen=True)
class AlignmentPipelineInput:
    site: ObservingSite
    compass: CompassSample
    inclinometer: InclinometerSample
    magnetic_correction: MagneticCorrection
    camera_frame: CameraFrame
    field_of_view_hint_deg: float | None = None
    pixel_scale_hint_arcsec: float | None = None


@dataclass(frozen=True)
class AlignmentPipelineResult:
    status: str
    plate_solution: PlateSolution
    alignment: AlignmentResult | None
    operator_message: str
    report_lines: tuple[str, ...]


def run_alignment_pipeline(
    pipeline_input: AlignmentPipelineInput,
    plate_solver: PlateSolver,
) -> AlignmentPipelineResult:
    """Solve a camera frame and compare it with the rough sensor estimate."""

    plate_solution = plate_solver.solve(
        PlateSolverRequest(
            camera_frame=pipeline_input.camera_frame,
            field_of_view_hint_deg=pipeline_input.field_of_view_hint_deg,
            pixel_scale_hint_arcsec=pipeline_input.pixel_scale_hint_arcsec,
        )
    )
    if plate_solution.status != "solved":
        message = plate_solution.failure_reason or "plate solving failed"
        failure = classify_plate_solver_failure(message)
        return AlignmentPipelineResult(
            status="failed",
            plate_solution=plate_solution,
            alignment=None,
            operator_message=f"{failure.operator_message} {failure.next_action}",
            report_lines=(
                "Estimated-vs-solved pointing delta",
                "Status: failed",
                f"Operator message: {failure.operator_message}",
                f"Plate solver: {plate_solution.solver_name}",
                f"Failure: {failure.title}",
                f"Next action: {failure.next_action}",
            ),
        )

    alignment = calculate_alignment(
        pipeline_input.site,
        pipeline_input.compass,
        pipeline_input.inclinometer,
        pipeline_input.magnetic_correction,
        plate_solution,
    )
    return AlignmentPipelineResult(
        status=alignment.status,
        plate_solution=plate_solution,
        alignment=alignment,
        operator_message=_operator_delta_message(alignment),
        report_lines=tuple(
            format_alignment_delta_report(
                alignment,
                plate_solution,
                operator_message=_operator_delta_message(alignment),
            )
        ),
    )


def load_fixture_pipeline(path: str | Path) -> tuple[AlignmentPipelineInput, PlateSolver]:
    """Build a deterministic pipeline and fixture solver from fixture JSON."""

    with Path(path).open(encoding="utf-8") as handle:
        fixture = json.load(handle)
    return fixture_pipeline_from_record(fixture)


def fixture_pipeline_from_record(
    fixture: Mapping[str, Any],
) -> tuple[AlignmentPipelineInput, PlateSolver]:
    site_record = fixture["observing_sites"][0]
    compass_record = fixture["compass_samples"][0]
    inclinometer_record = fixture["inclinometer_samples"][0]
    magnetic_record = fixture["magnetic_corrections"][0]
    camera_frame = camera_frame_from_record(fixture["camera_frames"][0])
    plate_solution = plate_solution_from_record(fixture["plate_solutions"][0])

    pipeline_input = AlignmentPipelineInput(
        site=ObservingSite(
            latitude_deg=float(site_record["latitude_deg"]),
            longitude_deg=float(site_record["longitude_deg"]),
            elevation_m=float(site_record["elevation_m"]),
            timestamp_utc=str(site_record["timestamp_utc"]),
            location_precision=str(site_record["location_precision"]),
            privacy_policy=str(site_record["privacy_policy"]),
        ),
        compass=CompassSample(
            magnetic_azimuth_deg=float(compass_record["magnetic_azimuth_deg"]),
            calibration_state=str(compass_record["calibration_state"]),
            uncertainty_deg=float(compass_record["uncertainty_deg"]),
            sensor_mount_offset_deg=float(compass_record["sensor_mount_offset_deg"]),
            calibration_offset_deg=float(compass_record["calibration_offset_deg"]),
        ),
        inclinometer=InclinometerSample(
            altitude_deg=float(inclinometer_record["altitude_deg"]),
            calibration_state=str(inclinometer_record["calibration_state"]),
            uncertainty_deg=float(inclinometer_record["uncertainty_deg"]),
            sensor_mount_offset_deg=float(
                inclinometer_record["sensor_mount_offset_deg"]
            ),
            calibration_offset_deg=float(inclinometer_record["calibration_offset_deg"]),
        ),
        magnetic_correction=MagneticCorrection(
            declination_deg=float(magnetic_record["declination_deg"]),
            model_name=str(magnetic_record["model_name"]),
            model_version=str(magnetic_record["model_version"]),
            valid_from=str(magnetic_record["valid_from"]),
            valid_until=str(magnetic_record["valid_until"]),
            uncertainty_deg=float(
                magnetic_record["uncertainty"]["declination_deg_1sigma"]
            ),
        ),
        camera_frame=camera_frame,
        field_of_view_hint_deg=plate_solution.field_of_view_deg,
        pixel_scale_hint_arcsec=plate_solution.pixel_scale_arcsec,
    )
    solver = FixturePlateSolver({camera_frame.id: plate_solution})
    return pipeline_input, solver


def format_alignment_delta_report(
    alignment: AlignmentResult,
    plate_solution: PlateSolution,
    *,
    operator_message: str | None = None,
) -> list[str]:
    lines = [
        "Estimated-vs-solved pointing delta",
        f"Status: {alignment.status}",
    ]
    if operator_message:
        lines.append(f"Operator message: {operator_message}")
    lines.extend(
        [
            f"Plate solver: {plate_solution.solver_name} {plate_solution.solver_version}",
            (
                "Rough local pointing: "
                f"az {alignment.rough_true_azimuth_deg:.3f} deg, "
                f"alt {alignment.rough_altitude_deg:.3f} deg"
            ),
            (
                "Estimated sky: "
                f"RA {alignment.estimated_ra_deg:.6f} deg, "
                f"Dec {alignment.estimated_dec_deg:.6f} deg"
            ),
            (
                "Solved sky: "
                f"RA {alignment.solved_ra_deg:.6f} deg, "
                f"Dec {alignment.solved_dec_deg:.6f} deg"
            ),
            (
                "Local correction: "
                f"az {alignment.local_azimuth_delta_deg:+.3f} deg, "
                f"alt {alignment.local_altitude_delta_deg:+.3f} deg"
            ),
            (
                "Sky separation: "
                f"{alignment.sky_separation_deg:.6f} deg at position angle "
                f"{alignment.sky_position_angle_deg:.3f} deg"
            ),
            (
                "Uncertainty inputs: "
                f"compass "
                f"{alignment.uncertainty_summary['compass_uncertainty_deg']} deg, "
                "inclinometer "
                f"{alignment.uncertainty_summary['inclinometer_uncertainty_deg']} deg, "
                "magnetic model "
                f"{alignment.uncertainty_summary['magnetic_model_uncertainty_deg']} deg"
            ),
        ]
    )
    return lines


def _operator_delta_message(alignment: AlignmentResult) -> str:
    return pointing_correction_message(
        alignment.local_azimuth_delta_deg,
        alignment.local_altitude_delta_deg,
    )

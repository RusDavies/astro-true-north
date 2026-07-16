"""Operator workflow states and plain-language recovery messages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorWorkflowState:
    id: str
    phase: str
    title: str
    operator_message: str
    next_action: str
    severity: str = "info"
    allows_mount_motion: bool = False


@dataclass(frozen=True)
class OperatorFailureMessage:
    code: str
    title: str
    operator_message: str
    next_action: str
    severity: str
    retry_allowed: bool


WORKFLOW_STATES: tuple[OperatorWorkflowState, ...] = (
    OperatorWorkflowState(
        id="start_setup",
        phase="setup",
        title="Start setup",
        operator_message="Set the telescope down safely and start setup.",
        next_action="Confirm the telescope is stable before taking readings.",
    ),
    OperatorWorkflowState(
        id="check_location_time",
        phase="setup",
        title="Check place and time",
        operator_message="Check the observing place and time.",
        next_action="Use GPS, a saved site, or a manual site entry.",
    ),
    OperatorWorkflowState(
        id="check_sensors",
        phase="sensors",
        title="Check direction sensors",
        operator_message="Check the compass and tilt readings.",
        next_action="Keep metal, magnets, and power cables away from the compass.",
    ),
    OperatorWorkflowState(
        id="capture_frame",
        phase="camera",
        title="Take sky image",
        operator_message="Take a focused sky image.",
        next_action="Point at open sky, focus the camera, and capture a frame.",
    ),
    OperatorWorkflowState(
        id="solve_frame",
        phase="solving",
        title="Match the sky",
        operator_message="Match the camera image to the sky map.",
        next_action="Wait for the plate solver to finish.",
    ),
    OperatorWorkflowState(
        id="report_delta",
        phase="result",
        title="Show correction",
        operator_message="Show how far the rough aim was from the solved aim.",
        next_action="Review the correction before moving anything.",
    ),
    OperatorWorkflowState(
        id="ready_to_adjust",
        phase="result",
        title="Ready to adjust",
        operator_message="Sky check complete. A careful adjustment is ready.",
        next_action="Move only after the operator approves the correction.",
        allows_mount_motion=True,
    ),
)


FAILURE_MESSAGES: tuple[OperatorFailureMessage, ...] = (
    OperatorFailureMessage(
        code="missing_location_time",
        title="Missing place or time",
        operator_message="I need the observing place and time before this can work.",
        next_action="Turn on GPS, choose a saved site, or enter the site manually.",
        severity="blocked",
        retry_allowed=True,
    ),
    OperatorFailureMessage(
        code="magnetic_model_unavailable",
        title="Magnetic correction unavailable",
        operator_message="I cannot correct magnetic north to true north yet.",
        next_action="Check that the magnetic model is installed and still valid.",
        severity="blocked",
        retry_allowed=True,
    ),
    OperatorFailureMessage(
        code="compass_uncalibrated",
        title="Compass needs calibration",
        operator_message="The compass reading is not trustworthy yet.",
        next_action="Calibrate the compass away from metal, motors, and cables.",
        severity="warning",
        retry_allowed=True,
    ),
    OperatorFailureMessage(
        code="tilt_out_of_range",
        title="Tilt reading is impossible",
        operator_message="The tilt reading is outside the telescope's real range.",
        next_action="Check that the sensor is mounted correctly and try again.",
        severity="blocked",
        retry_allowed=True,
    ),
    OperatorFailureMessage(
        code="plate_solver_missing",
        title="Sky matcher is not installed",
        operator_message="The sky matcher is not installed on this computer.",
        next_action="Install the selected plate solver or choose a fixture solver.",
        severity="blocked",
        retry_allowed=True,
    ),
    OperatorFailureMessage(
        code="plate_solver_timeout",
        title="Sky match took too long",
        operator_message="The sky matcher took too long and stopped.",
        next_action="Try a better focus, shorter search radius, or clearer sky.",
        severity="warning",
        retry_allowed=True,
    ),
    OperatorFailureMessage(
        code="plate_solver_failed",
        title="Sky image did not match",
        operator_message="The camera image did not match the sky map.",
        next_action="Check focus, clouds, lens cap, exposure, and try another image.",
        severity="warning",
        retry_allowed=True,
    ),
    OperatorFailureMessage(
        code="unsafe_mount_motion_locked",
        title="Mount movement locked",
        operator_message="Automatic mount movement is still locked.",
        next_action="Review the correction and approve any movement yourself.",
        severity="blocked",
        retry_allowed=False,
    ),
)


def workflow_state(state_id: str) -> OperatorWorkflowState:
    for state in WORKFLOW_STATES:
        if state.id == state_id:
            return state
    raise KeyError(f"unknown workflow state: {state_id}")


def failure_message(code: str) -> OperatorFailureMessage:
    for message in FAILURE_MESSAGES:
        if message.code == code:
            return message
    raise KeyError(f"unknown failure message: {code}")


def classify_plate_solver_failure(reason: str) -> OperatorFailureMessage:
    normalized = reason.lower()
    if "executable not found" in normalized or "not installed" in normalized:
        return failure_message("plate_solver_missing")
    if "timed out" in normalized or "timeout" in normalized:
        return failure_message("plate_solver_timeout")
    return failure_message("plate_solver_failed")


def pointing_correction_message(
    local_azimuth_delta_deg: float,
    local_altitude_delta_deg: float,
) -> str:
    return (
        "Sky check complete. "
        f"Correction: azimuth {local_azimuth_delta_deg:+.2f} deg, "
        f"altitude {local_altitude_delta_deg:+.2f} deg. "
        "Review it before moving anything."
    )

from __future__ import annotations

import unittest

from astro_true_north.workflow import (
    FAILURE_MESSAGES,
    WORKFLOW_STATES,
    classify_plate_solver_failure,
    failure_message,
    pointing_correction_message,
    workflow_state,
)


class OperatorWorkflowTests(unittest.TestCase):
    def test_workflow_states_have_child_friendly_actions(self) -> None:
        state_ids = {state.id for state in WORKFLOW_STATES}

        self.assertIn("check_location_time", state_ids)
        self.assertIn("capture_frame", state_ids)
        self.assertIn("ready_to_adjust", state_ids)
        self.assertTrue(workflow_state("ready_to_adjust").allows_mount_motion)
        for state in WORKFLOW_STATES:
            self.assertNotIn("star alignment", state.operator_message.lower())
            self.assertLessEqual(len(state.operator_message), 80)
            self.assertTrue(state.next_action)

    def test_failure_messages_are_plain_and_recoverable(self) -> None:
        codes = {message.code for message in FAILURE_MESSAGES}

        self.assertIn("plate_solver_failed", codes)
        self.assertIn("compass_uncalibrated", codes)
        self.assertIn("unsafe_mount_motion_locked", codes)
        for message in FAILURE_MESSAGES:
            self.assertNotIn("fatal", message.operator_message.lower())
            self.assertNotIn("stack trace", message.operator_message.lower())
            self.assertTrue(message.next_action)
            self.assertIn(message.severity, {"info", "warning", "blocked"})

    def test_plate_solver_failure_classification(self) -> None:
        self.assertEqual(
            classify_plate_solver_failure("solve-field executable not found").code,
            "plate_solver_missing",
        )
        self.assertEqual(
            classify_plate_solver_failure("ASTAP timed out after 60s").code,
            "plate_solver_timeout",
        )
        self.assertEqual(
            classify_plate_solver_failure("no stars found").code,
            "plate_solver_failed",
        )

    def test_pointing_correction_message_requires_review(self) -> None:
        message = pointing_correction_message(1.25, -0.5)

        self.assertIn("Sky check complete", message)
        self.assertIn("azimuth +1.25 deg", message)
        self.assertIn("altitude -0.50 deg", message)
        self.assertIn("Review", message)

    def test_unknown_workflow_entries_fail_clearly(self) -> None:
        with self.assertRaises(KeyError):
            workflow_state("missing")
        with self.assertRaises(KeyError):
            failure_message("missing")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from astro_true_north.nexstar import (
    MountMotionLockedError,
    NexStarProtocolError,
    hex_angle_to_degrees,
    parse_ascii_digit_flag,
    parse_flag_response,
    parse_nexstar_angle_pair,
    validate_slow_yaw_plan,
)


class NexStarParsingTests(unittest.TestCase):
    def test_parse_flag_response(self) -> None:
        self.assertFalse(parse_flag_response(b"\x00"))
        self.assertTrue(parse_flag_response(b"\x01"))

    def test_parse_ascii_digit_flag(self) -> None:
        self.assertFalse(parse_ascii_digit_flag(b"0"))
        self.assertTrue(parse_ascii_digit_flag(b"1"))

    def test_parse_nexstar_angle_pair(self) -> None:
        azimuth, altitude = parse_nexstar_angle_pair(b"4000,8000")

        self.assertAlmostEqual(azimuth, 90.0)
        self.assertAlmostEqual(altitude, 180.0)

    def test_parse_precise_nexstar_angle(self) -> None:
        self.assertAlmostEqual(hex_angle_to_degrees("40000000"), 90.0)

    def test_invalid_angle_raises_protocol_error(self) -> None:
        with self.assertRaises(NexStarProtocolError):
            hex_angle_to_degrees("xyz")


class SlowYawGuardTests(unittest.TestCase):
    def test_valid_plan_reports_sweep(self) -> None:
        plan = validate_slow_yaw_plan(
            direction="right",
            rate_deg_per_sec=0.25,
            duration_seconds=20.0,
            operator_approved=True,
            abort_ready=True,
        )

        self.assertEqual(plan.direction, "right")
        self.assertAlmostEqual(plan.sweep_degrees, 5.0)
        self.assertIn("disabled", "\n".join(plan.report_lines()))

    def test_requires_operator_approval(self) -> None:
        with self.assertRaisesRegex(MountMotionLockedError, "operator approval"):
            validate_slow_yaw_plan(
                direction="left",
                rate_deg_per_sec=0.25,
                duration_seconds=20.0,
                operator_approved=False,
                abort_ready=True,
            )

    def test_requires_abort_ready(self) -> None:
        with self.assertRaisesRegex(MountMotionLockedError, "abort"):
            validate_slow_yaw_plan(
                direction="left",
                rate_deg_per_sec=0.25,
                duration_seconds=20.0,
                operator_approved=True,
                abort_ready=False,
            )

    def test_rate_limit(self) -> None:
        with self.assertRaisesRegex(MountMotionLockedError, "rate exceeds"):
            validate_slow_yaw_plan(
                direction="left",
                rate_deg_per_sec=1.0,
                duration_seconds=20.0,
                operator_approved=True,
                abort_ready=True,
            )


if __name__ == "__main__":
    unittest.main()

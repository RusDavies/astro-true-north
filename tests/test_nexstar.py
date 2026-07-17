from __future__ import annotations

import unittest
from unittest import mock

from astro_true_north.nexstar import (
    MountMotionLockedError,
    NexStarProtocolError,
    build_azimuth_stop_commands,
    build_variable_rate_azimuth_command,
    execute_slow_yaw,
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
        self.assertIn("explicit execution", "\n".join(plan.report_lines()))

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


class SlowYawCommandTests(unittest.TestCase):
    def test_build_variable_rate_azimuth_command(self) -> None:
        command = build_variable_rate_azimuth_command(
            direction="right",
            rate_deg_per_sec=0.2,
        )

        self.assertEqual(command, b"P\x03\x10\x06\x0b@\x00\x00")

    def test_build_variable_rate_azimuth_command_negative(self) -> None:
        command = build_variable_rate_azimuth_command(
            direction="left",
            rate_deg_per_sec=0.2,
        )

        self.assertEqual(command, b"P\x03\x10\x07\x0b@\x00\x00")

    def test_build_azimuth_stop_commands(self) -> None:
        self.assertEqual(
            build_azimuth_stop_commands(),
            (
                b"P\x02\x10\x24\x00\x00\x00\x00",
                b"P\x02\x10\x25\x00\x00\x00\x00",
            ),
        )

    def test_execute_slow_yaw_sends_stop_after_sleep(self) -> None:
        plan = validate_slow_yaw_plan(
            direction="right",
            rate_deg_per_sec=0.2,
            duration_seconds=10.0,
            operator_approved=True,
            abort_ready=True,
        )
        fake = FakeNexStarSerial()

        with mock.patch("astro_true_north.nexstar.NexStarSerial", return_value=fake):
            lines = execute_slow_yaw(
                "/dev/test",
                plan,
                sleeper=lambda _: None,
            )

        self.assertIn("executed", "\n".join(lines))
        self.assertEqual(fake.commands[-3], b"P\x03\x10\x06\x0b@\x00\x00")
        self.assertEqual(fake.commands[-2:], list(build_azimuth_stop_commands()))

    def test_execute_slow_yaw_sends_stop_when_sleep_fails(self) -> None:
        plan = validate_slow_yaw_plan(
            direction="right",
            rate_deg_per_sec=0.2,
            duration_seconds=10.0,
            operator_approved=True,
            abort_ready=True,
        )
        fake = FakeNexStarSerial()

        def fail_sleep(_: float) -> None:
            raise RuntimeError("interrupted")

        with (
            mock.patch("astro_true_north.nexstar.NexStarSerial", return_value=fake),
            self.assertRaisesRegex(RuntimeError, "interrupted"),
        ):
            execute_slow_yaw(
                "/dev/test",
                plan,
                sleeper=fail_sleep,
            )

        self.assertEqual(fake.commands[-2:], list(build_azimuth_stop_commands()))


class FakeNexStarSerial:
    def __init__(self) -> None:
        self.commands: list[bytes] = []
        self.responses = [
            b"x",
            b"\x05\x1f",
            b"\x0c",
            b"\x00",
            b"0",
            b"\x00",
            b"0000,0000",
            b"",
            b"",
            b"",
        ]

    def __enter__(self) -> "FakeNexStarSerial":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def transact(self, payload: bytes) -> bytes:
        self.commands.append(payload)
        if not self.responses:
            return b""
        return self.responses.pop(0)


if __name__ == "__main__":
    unittest.main()

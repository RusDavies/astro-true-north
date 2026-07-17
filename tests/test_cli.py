from __future__ import annotations

import contextlib
import io
import pathlib
import unittest
from unittest import mock

from astro_true_north.bn220 import Bn220CaptureSummary, Bn220GpsFix
from astro_true_north.cli import main
from astro_true_north.nexstar import NexStarProtocolError, NexStarStatus
from astro_true_north.wt901 import (
    Wt901Angle,
    Wt901CalibrationReport,
    Wt901CaptureSummary,
)

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


class CliTests(unittest.TestCase):
    def test_version_output(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(["--version"])

        self.assertEqual(result, 0)
        self.assertIn("astro-true-north", stdout.getvalue())

    def test_fixture_pipeline_output(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(
                [
                    "--fixture-pipeline",
                    str(FIXTURE_DIR / "sensor_samples.json"),
                ]
            )

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("Estimated-vs-solved pointing delta", output)
        self.assertIn("Local correction:", output)

    def test_wt901_sampler_output(self) -> None:
        summary = Wt901CaptureSummary(
            samples_seen=2,
            angle_samples=2,
            magnetic_samples=0,
            first_angle=Wt901Angle(roll_deg=1.0, pitch_deg=2.0, yaw_deg=3.0),
            last_angle=Wt901Angle(roll_deg=4.0, pitch_deg=5.0, yaw_deg=6.0),
            min_yaw_deg=3.0,
            max_yaw_deg=6.0,
            min_pitch_deg=2.0,
            max_pitch_deg=5.0,
            min_roll_deg=1.0,
            max_roll_deg=4.0,
            min_magnetic_magnitude=None,
            max_magnetic_magnitude=None,
        )
        stdout = io.StringIO()

        with (
            mock.patch("astro_true_north.cli.capture_wt901", return_value=summary) as capture,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(
                [
                    "--sample-wt901",
                    "/dev/ttyUSB0",
                    "--wt901-duration",
                    "0.5",
                ]
            )

        self.assertEqual(result, 0)
        capture.assert_called_once()
        self.assertIn("WT901 sample summary", stdout.getvalue())

    def test_wt901_auto_port_resolution(self) -> None:
        summary = Wt901CaptureSummary(
            samples_seen=1,
            angle_samples=1,
            magnetic_samples=0,
            first_angle=Wt901Angle(roll_deg=1.0, pitch_deg=2.0, yaw_deg=3.0),
            last_angle=Wt901Angle(roll_deg=1.0, pitch_deg=2.0, yaw_deg=3.0),
            min_yaw_deg=3.0,
            max_yaw_deg=3.0,
            min_pitch_deg=2.0,
            max_pitch_deg=2.0,
            min_roll_deg=1.0,
            max_roll_deg=1.0,
            min_magnetic_magnitude=None,
            max_magnetic_magnitude=None,
        )
        stdout = io.StringIO()

        with (
            mock.patch(
                "astro_true_north.cli.resolve_sensor_port",
                return_value=("/dev/ttyUSB1", []),
            ) as resolve,
            mock.patch("astro_true_north.cli.capture_wt901", return_value=summary) as capture,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(["--sample-wt901", "auto", "--serial-probe-duration", "0.1"])

        self.assertEqual(result, 0)
        resolve.assert_called_once()
        capture.assert_called_once()
        self.assertEqual(capture.call_args.args[0], "/dev/ttyUSB1")
        self.assertIn("Using /dev/ttyUSB1.", stdout.getvalue())

    def test_wt901_stream_output(self) -> None:
        stdout = io.StringIO()

        with (
            mock.patch(
                "astro_true_north.cli.stream_wt901_channel_lines",
                return_value=iter(["0.000000,angle,,,,,,,0.0,0.0,1.0,,,,"]),
            ) as stream,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(["--stream-wt901", "/dev/ttyUSB1", "--wt901-duration", "0.5"])

        self.assertEqual(result, 0)
        stream.assert_called_once()
        output = stdout.getvalue()
        self.assertIn("elapsed_s,channel", output)
        self.assertIn("angle", output)

    def test_wt901_stream_overwrite_output(self) -> None:
        stdout = io.StringIO()

        with (
            mock.patch(
                "astro_true_north.cli.stream_wt901_channel_lines",
                return_value=iter(
                    [
                        "0.000000,accel,1.0,2.0,3.0,,,,,,,,,,",
                        "0.100000,gyro,,,,4.0,5.0,6.0,,,,,,,",
                        "0.200000,angle,,,,,,,7.0,8.0,9.0,,,,",
                        "0.300000,mag,,,,,,,,,,10,11,12,19.104973",
                    ]
                ),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = main(
                [
                    "--stream-wt901",
                    "/dev/ttyUSB1",
                    "--wt901-duration",
                    "0.5",
                    "--wt901-overwrite",
                ]
            )

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertNotIn("elapsed_s,channel", output)
        self.assertIn("accel: waiting for frame", output)
        self.assertIn("mag: waiting for frame", output)
        self.assertIn("\x1b[4F", output)
        self.assertIn("accel_x_g=1.0", output)
        self.assertIn("gyro_z_deg_s=6.0", output)
        self.assertIn("roll_deg=7.0", output)
        self.assertIn("pitch_deg=8.0", output)
        self.assertIn("yaw_deg=9.0", output)
        self.assertIn("mag_magnitude=19.104973", output)

    def test_wt901_calibration_output(self) -> None:
        report = Wt901CalibrationReport(
            samples_seen=4,
            angle_samples=2,
            magnetic_samples=2,
            roll_stddev_deg=0.1,
            pitch_stddev_deg=0.2,
            yaw_stddev_deg=0.3,
            roll_span_deg=0.2,
            pitch_span_deg=0.4,
            yaw_span_deg=0.6,
            magnetic_variation_percent=1.5,
            recommended_compass_uncertainty_deg=2.0,
            recommended_inclinometer_uncertainty_deg=0.6,
            status="stationary-estimate",
        )
        stdout = io.StringIO()

        with (
            mock.patch(
                "astro_true_north.cli.capture_wt901_calibration",
                return_value=report,
            ) as capture,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(
                [
                    "--calibrate-wt901",
                    "/dev/ttyUSB0",
                    "--wt901-duration",
                    "0.5",
                ]
            )

        self.assertEqual(result, 0)
        capture.assert_called_once()
        self.assertIn("WT901 calibration/error-budget summary", stdout.getvalue())

    def test_bn220_sampler_output(self) -> None:
        summary = Bn220CaptureSummary(
            sentences_seen=2,
            valid_sentences=2,
            rmc_sentences=1,
            gga_sentences=1,
            fix=Bn220GpsFix(
                has_fix=True,
                timestamp_utc=None,
                latitude_deg=44.123,
                longitude_deg=-76.456,
                satellites=7,
                hdop=1.2,
                altitude_m=80.0,
                source_sentences=("GNRMC", "GNGGA"),
            ),
        )
        stdout = io.StringIO()

        with (
            mock.patch("astro_true_north.cli.capture_bn220", return_value=summary) as capture,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(
                [
                    "--sample-bn220",
                    "/dev/ttyUSB1",
                    "--gps-duration",
                    "0.5",
                ]
            )

        self.assertEqual(result, 0)
        capture.assert_called_once()
        self.assertIn("BN-220 GPS sample summary", stdout.getvalue())

    def test_nexstar_status_output(self) -> None:
        status = NexStarStatus(
            port="/dev/ttyUSB2",
            version_major=5,
            version_minor=31,
            model_code=12,
            model_name="6/8 SE",
            alignment_complete=False,
            goto_in_progress=False,
            tracking_mode=0,
            azimuth_deg=0.0,
            altitude_deg=0.0,
        )
        stdout = io.StringIO()

        with (
            mock.patch("astro_true_north.cli.query_nexstar_status", return_value=status) as query,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(["--nexstar-status", "/dev/ttyUSB2"])

        self.assertEqual(result, 0)
        query.assert_called_once()
        self.assertIn("NexStar on /dev/ttyUSB2", stdout.getvalue())

    def test_nexstar_status_reports_read_failure(self) -> None:
        stdout = io.StringIO()

        with (
            mock.patch(
                "astro_true_north.cli.query_nexstar_status",
                side_effect=NexStarProtocolError("timed out"),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = main(["--nexstar-status", "/dev/ttyUSB2"])

        self.assertEqual(result, 1)
        self.assertIn("NexStar status read failed", stdout.getvalue())

    def test_nexstar_slow_yaw_plan_requires_approval(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = main(["--plan-nexstar-slow-yaw", "right"])

        self.assertEqual(result, 1)
        self.assertIn("locked", stdout.getvalue())

    def test_nexstar_slow_yaw_plan_output(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = main(
                [
                    "--plan-nexstar-slow-yaw",
                    "right",
                    "--nexstar-yaw-rate-deg-sec",
                    "0.2",
                    "--nexstar-yaw-duration",
                    "10",
                    "--approve-mount-motion",
                    "--mount-abort-ready",
                ]
            )

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("NexStar slow-yaw plan validated", output)
        self.assertIn("Motor command emission: requires explicit execution", output)

    def test_nexstar_slow_yaw_execute_requires_plan(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = main(["--execute-nexstar-slow-yaw", "/dev/ttyUSB2"])

        self.assertEqual(result, 1)
        self.assertIn("requires --plan-nexstar-slow-yaw", stdout.getvalue())

    def test_nexstar_slow_yaw_execute_output(self) -> None:
        stdout = io.StringIO()

        with (
            mock.patch(
                "astro_true_north.cli.execute_slow_yaw",
                return_value=["NexStar slow-yaw command executed."],
            ) as execute,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(
                [
                    "--plan-nexstar-slow-yaw",
                    "right",
                    "--execute-nexstar-slow-yaw",
                    "/dev/ttyUSB2",
                    "--nexstar-yaw-rate-deg-sec",
                    "0.2",
                    "--nexstar-yaw-duration",
                    "10",
                    "--approve-mount-motion",
                    "--mount-abort-ready",
                ]
            )

        self.assertEqual(result, 0)
        execute.assert_called_once()
        self.assertIn("executed", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

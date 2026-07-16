from __future__ import annotations

import contextlib
import io
import pathlib
import unittest
from unittest import mock

from astro_true_north.bn220 import Bn220CaptureSummary, Bn220GpsFix
from astro_true_north.cli import main
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


if __name__ == "__main__":
    unittest.main()

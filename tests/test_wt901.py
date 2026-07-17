from __future__ import annotations

import io
import struct
import unittest

from astro_true_north.wt901 import (
    ACCELERATION_FRAME,
    ANGLE_FRAME,
    GYRO_FRAME,
    MAGNETIC_FRAME,
    circular_span_deg,
    decode_wt901_frame,
    estimate_wt901_error_budget,
    format_wt901_stream_header,
    format_wt901_stream_sample,
    iter_wt901_samples,
    summarize_wt901_samples,
)


def wt901_frame(kind: int, values: tuple[int, int, int, int]) -> bytes:
    payload = bytes([0x55, kind]) + struct.pack("<hhhh", *values)
    return payload + bytes([sum(payload) & 0xFF])


class Wt901Tests(unittest.TestCase):
    def test_decode_acceleration_frame(self) -> None:
        frame = wt901_frame(ACCELERATION_FRAME, (2048, -4096, 8192, 0))

        sample = decode_wt901_frame(frame, now=1.5)

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertIsNotNone(sample.acceleration)
        assert sample.acceleration is not None
        self.assertAlmostEqual(sample.acceleration.x_g, 1.0)
        self.assertAlmostEqual(sample.acceleration.y_g, -2.0)
        self.assertAlmostEqual(sample.acceleration.z_g, 4.0)

    def test_decode_gyro_frame(self) -> None:
        frame = wt901_frame(GYRO_FRAME, (16384, -8192, 4096, 0))

        sample = decode_wt901_frame(frame, now=1.5)

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertIsNotNone(sample.gyro)
        assert sample.gyro is not None
        self.assertAlmostEqual(sample.gyro.x_deg_s, 1000.0)
        self.assertAlmostEqual(sample.gyro.y_deg_s, -500.0)
        self.assertAlmostEqual(sample.gyro.z_deg_s, 250.0)

    def test_decode_angle_frame(self) -> None:
        frame = wt901_frame(ANGLE_FRAME, (16384, -8192, 4096, 0))

        sample = decode_wt901_frame(frame, now=12.5)

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertIsNotNone(sample.angle)
        assert sample.angle is not None
        self.assertAlmostEqual(sample.angle.roll_deg, 90.0)
        self.assertAlmostEqual(sample.angle.pitch_deg, -45.0)
        self.assertAlmostEqual(sample.angle.yaw_deg, 22.5)
        self.assertEqual(sample.timestamp_monotonic, 12.5)

    def test_decode_magnetic_frame(self) -> None:
        frame = wt901_frame(MAGNETIC_FRAME, (100, -200, 300, 0))

        sample = decode_wt901_frame(frame, now=1.0)

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertIsNotNone(sample.magnetic_field)
        assert sample.magnetic_field is not None
        self.assertEqual(sample.magnetic_field.x, 100)
        self.assertEqual(sample.magnetic_field.y, -200)
        self.assertEqual(sample.magnetic_field.z, 300)

    def test_bad_checksum_is_ignored(self) -> None:
        frame = bytearray(wt901_frame(ANGLE_FRAME, (1, 2, 3, 4)))
        frame[-1] ^= 0xFF

        self.assertIsNone(decode_wt901_frame(bytes(frame)))

    def test_format_stream_rows(self) -> None:
        sample = decode_wt901_frame(wt901_frame(ANGLE_FRAME, (0, 0, 8192, 0)), now=12.5)

        self.assertIn("elapsed_s,channel", format_wt901_stream_header())
        self.assertEqual(
            format_wt901_stream_sample(sample, start_time_monotonic=10.0),
            "2.500000,angle,,,,,,,0.000000,0.000000,45.000000,,,,",
        )

    def test_stream_parser_resynchronizes(self) -> None:
        stream = io.BytesIO(
            b"noise"
            + wt901_frame(MAGNETIC_FRAME, (1, 2, 3, 0))
            + b"\x00"
            + wt901_frame(ANGLE_FRAME, (0, 0, 8192, 0))
        )

        samples = list(iter_wt901_samples(stream))

        self.assertEqual(len(samples), 2)
        self.assertIsNotNone(samples[0].magnetic_field)
        self.assertIsNotNone(samples[1].angle)
        assert samples[1].angle is not None
        self.assertAlmostEqual(samples[1].angle.yaw_deg, 45.0)

    def test_summary_reports_angle_and_magnetic_ranges(self) -> None:
        samples = [
            decode_wt901_frame(wt901_frame(ANGLE_FRAME, (0, 0, 0, 0)), now=1.0),
            decode_wt901_frame(wt901_frame(ANGLE_FRAME, (1000, -2000, 3000, 0)), now=2.0),
            decode_wt901_frame(wt901_frame(MAGNETIC_FRAME, (3, 4, 0, 0)), now=3.0),
        ]

        summary = summarize_wt901_samples([sample for sample in samples if sample])

        self.assertEqual(summary.samples_seen, 3)
        self.assertEqual(summary.angle_samples, 2)
        self.assertEqual(summary.magnetic_samples, 1)
        self.assertIn("WT901 sample summary", "\n".join(summary.report_lines()))
        self.assertEqual(summary.min_magnetic_magnitude, 5.0)

    def test_circular_span_handles_yaw_wraparound(self) -> None:
        self.assertAlmostEqual(circular_span_deg([179.0, -179.0, 178.0]) or 0.0, 3.0)

    def test_error_budget_from_stationary_samples(self) -> None:
        samples = [
            decode_wt901_frame(wt901_frame(ANGLE_FRAME, (0, 0, 0, 0)), now=1.0),
            decode_wt901_frame(wt901_frame(ANGLE_FRAME, (10, -10, 15, 0)), now=2.0),
            decode_wt901_frame(wt901_frame(ANGLE_FRAME, (-10, 10, -15, 0)), now=3.0),
            decode_wt901_frame(wt901_frame(MAGNETIC_FRAME, (100, 0, 0, 0)), now=4.0),
            decode_wt901_frame(wt901_frame(MAGNETIC_FRAME, (101, 0, 0, 0)), now=5.0),
        ]

        report = estimate_wt901_error_budget([sample for sample in samples if sample])

        self.assertEqual(report.status, "stationary-estimate")
        self.assertEqual(report.angle_samples, 3)
        self.assertEqual(report.magnetic_samples, 2)
        self.assertGreaterEqual(report.recommended_compass_uncertainty_deg or 0.0, 2.0)
        self.assertGreaterEqual(report.recommended_inclinometer_uncertainty_deg or 0.0, 0.5)
        self.assertIn("Recommended compass uncertainty", "\n".join(report.report_lines()))

    def test_error_budget_flags_motion_during_stationary_capture(self) -> None:
        samples = [
            decode_wt901_frame(wt901_frame(ANGLE_FRAME, (0, 0, 0, 0)), now=1.0),
            decode_wt901_frame(wt901_frame(ANGLE_FRAME, (6000, 0, 0, 0)), now=2.0),
        ]

        report = estimate_wt901_error_budget([sample for sample in samples if sample])

        self.assertEqual(report.status, "moving-during-capture")


if __name__ == "__main__":
    unittest.main()

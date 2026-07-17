from __future__ import annotations

import struct
import unittest

from astro_true_north.serial_discovery import (
    SerialProbeResult,
    count_nmea_sentences,
    count_wt901_frames,
    resolve_sensor_port,
)
from astro_true_north.wt901 import ANGLE_FRAME, MAGNETIC_FRAME


def wt901_frame(kind: int, values: tuple[int, int, int, int]) -> bytes:
    payload = bytes([0x55, kind]) + struct.pack("<hhhh", *values)
    return payload + bytes([sum(payload) & 0xFF])


class SerialDiscoveryTests(unittest.TestCase):
    def test_counts_wt901_frames_in_mixed_bytes(self) -> None:
        data = (
            b"noise"
            + wt901_frame(ANGLE_FRAME, (0, 0, 8192, 0))
            + b"\x00"
            + wt901_frame(MAGNETIC_FRAME, (10, 20, 30, 0))
        )

        self.assertEqual(count_wt901_frames(data), 2)

    def test_counts_valid_nmea_sentence_types(self) -> None:
        count, sentence_types = count_nmea_sentences(
            b"$GNRMC,092751.000,V,,,,,,,280511,,,N\n"
            b"$GNGGA,092752.000,,,,,0,00,100.0,,,,,,\n"
            b"not a sentence\n"
        )

        self.assertEqual(count, 2)
        self.assertEqual(sentence_types, ("GNRMC", "GNGGA"))

    def test_resolves_first_matching_wt901_port(self) -> None:
        resolved, results = resolve_sensor_port(
            "wt901",
            ports=[],
            duration_seconds=0.1,
        )

        self.assertIsNone(resolved)
        self.assertEqual(results, [])

    def test_probe_result_labels_known_streams(self) -> None:
        wt901 = SerialProbeResult(
            port="/dev/example",
            bytes_read=11,
            wt901_frames=1,
            nmea_sentences=0,
            nmea_types=(),
        )
        bn220 = SerialProbeResult(
            port="/dev/example2",
            bytes_read=80,
            wt901_frames=0,
            nmea_sentences=2,
            nmea_types=("GNRMC", "GNGGA"),
        )

        self.assertTrue(wt901.looks_like_wt901)
        self.assertIn("WT901", wt901.report_line())
        self.assertTrue(bn220.looks_like_bn220)
        self.assertIn("BN-220", bn220.report_line())


if __name__ == "__main__":
    unittest.main()

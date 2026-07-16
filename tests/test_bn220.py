from __future__ import annotations

import pathlib
import unittest

from astro_true_north.bn220 import (
    is_valid_nmea,
    parse_gga,
    parse_nmea_coordinate,
    parse_rmc,
    summarize_bn220_sentences,
)


FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


class Bn220Tests(unittest.TestCase):
    def test_validates_nmea_checksum(self) -> None:
        self.assertTrue(
            is_valid_nmea("$GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A*46")
        )
        self.assertFalse(
            is_valid_nmea("$GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A*00")
        )

    def test_parse_coordinate(self) -> None:
        self.assertAlmostEqual(
            parse_nmea_coordinate("5321.6802", "N") or 0.0,
            53.3613366667,
        )
        self.assertAlmostEqual(
            parse_nmea_coordinate("00630.3372", "W") or 0.0,
            -6.50562,
        )

    def test_parse_rmc_fix(self) -> None:
        parsed = parse_rmc(
            "$GNRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A"
        )

        self.assertTrue(parsed["has_fix"])
        self.assertAlmostEqual(parsed["latitude_deg"], 53.3613366667)
        self.assertAlmostEqual(parsed["longitude_deg"], -6.50562)
        self.assertEqual(
            parsed["timestamp_utc"].isoformat(),
            "2011-05-28T09:27:51+00:00",
        )

    def test_parse_gga_fix_quality(self) -> None:
        parsed = parse_gga(
            "$GNGGA,092752.000,5321.6802,N,00630.3372,W,1,08,1.03,73.5,M,55.2,M,,"
        )

        self.assertTrue(parsed["has_fix"])
        self.assertEqual(parsed["satellites"], 8)
        self.assertEqual(parsed["hdop"], 1.03)
        self.assertEqual(parsed["altitude_m"], 73.5)

    def test_summary_uses_latest_rmc_and_gga(self) -> None:
        summary = summarize_bn220_sentences(
            [
                "$GNRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A",
                "$GNGGA,092752.000,5321.6802,N,00630.3372,W,1,08,1.03,73.5,M,55.2,M,,",
            ]
        )

        self.assertEqual(summary.sentences_seen, 2)
        self.assertEqual(summary.valid_sentences, 2)
        self.assertEqual(summary.rmc_sentences, 1)
        self.assertEqual(summary.gga_sentences, 1)
        self.assertIsNotNone(summary.fix)
        assert summary.fix is not None
        self.assertTrue(summary.fix.has_fix)
        self.assertEqual(summary.fix.satellites, 8)
        report = "\n".join(summary.report_lines())
        self.assertIn("Coarse location: 53.4, -6.5", report)
        self.assertNotIn("53.361336", report)

    def test_summary_reports_no_fix(self) -> None:
        summary = summarize_bn220_sentences(
            ["$GNRMC,092751.000,V,,,,,,,280511,,,N"]
        )

        self.assertIsNotNone(summary.fix)
        assert summary.fix is not None
        self.assertFalse(summary.fix.has_fix)
        self.assertIn("Fix status: not fixed", "\n".join(summary.report_lines()))

    def test_live_no_fix_fixture_decodes(self) -> None:
        sentences = (FIXTURE_DIR / "bn220_no_fix_nmea.txt").read_text(
            encoding="ascii"
        ).splitlines()

        summary = summarize_bn220_sentences(sentences)

        self.assertEqual(summary.sentences_seen, 8)
        self.assertEqual(summary.valid_sentences, 8)
        self.assertEqual(summary.rmc_sentences, 1)
        self.assertEqual(summary.gga_sentences, 1)
        self.assertIsNotNone(summary.fix)
        assert summary.fix is not None
        self.assertFalse(summary.fix.has_fix)
        self.assertEqual(summary.fix.satellites, 0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import pathlib
import unittest

from astro_true_north.alignment import (
    CompassSample,
    InclinometerSample,
    MagneticCorrection,
    ObservingSite,
    PlateSolution,
    calculate_alignment,
    corrected_altitude,
    corrected_true_azimuth,
    normalize_360,
    signed_angle_delta,
)

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def build_fixture_inputs() -> tuple[
    ObservingSite,
    CompassSample,
    InclinometerSample,
    MagneticCorrection,
    PlateSolution,
]:
    fixture = load_fixture("sensor_samples.json")
    site_data = fixture["observing_sites"][0]
    compass_data = fixture["compass_samples"][0]
    inclinometer_data = fixture["inclinometer_samples"][0]
    magnetic_data = fixture["magnetic_corrections"][0]
    plate_data = fixture["plate_solutions"][0]

    return (
        ObservingSite(
            latitude_deg=site_data["latitude_deg"],
            longitude_deg=site_data["longitude_deg"],
            elevation_m=site_data["elevation_m"],
            timestamp_utc=site_data["timestamp_utc"],
            location_precision=site_data["location_precision"],
            privacy_policy=site_data["privacy_policy"],
        ),
        CompassSample(
            magnetic_azimuth_deg=compass_data["magnetic_azimuth_deg"],
            calibration_state=compass_data["calibration_state"],
            uncertainty_deg=compass_data["uncertainty_deg"],
            sensor_mount_offset_deg=compass_data["sensor_mount_offset_deg"],
            calibration_offset_deg=compass_data["calibration_offset_deg"],
        ),
        InclinometerSample(
            altitude_deg=inclinometer_data["altitude_deg"],
            calibration_state=inclinometer_data["calibration_state"],
            uncertainty_deg=inclinometer_data["uncertainty_deg"],
            sensor_mount_offset_deg=inclinometer_data["sensor_mount_offset_deg"],
            calibration_offset_deg=inclinometer_data["calibration_offset_deg"],
        ),
        MagneticCorrection(
            declination_deg=magnetic_data["declination_deg"],
            model_name=magnetic_data["model_name"],
            model_version=magnetic_data["model_version"],
            valid_from=magnetic_data["valid_from"],
            valid_until=magnetic_data["valid_until"],
            uncertainty_deg=magnetic_data["uncertainty"]["declination_deg_1sigma"],
        ),
        PlateSolution(
            ra_deg=plate_data["ra_deg"],
            dec_deg=plate_data["dec_deg"],
            frame=plate_data["frame"],
            obstime=plate_data["obstime"],
            confidence=plate_data["confidence"],
            solver_name=plate_data["solver_name"],
            solver_version=plate_data["solver_version"],
        ),
    )


class AngleHelperTests(unittest.TestCase):
    def test_normalize_360(self) -> None:
        self.assertAlmostEqual(normalize_360(370.0), 10.0)
        self.assertAlmostEqual(normalize_360(-8.0), 352.0)

    def test_signed_angle_delta(self) -> None:
        self.assertAlmostEqual(signed_angle_delta(2.0, 359.0), 3.0)
        self.assertAlmostEqual(signed_angle_delta(359.0, 2.0), -3.0)


class AlignmentCalculationTests(unittest.TestCase):
    def test_corrected_true_azimuth_uses_east_positive_declination(self) -> None:
        _, compass, _, magnetic_correction, _ = build_fixture_inputs()

        self.assertAlmostEqual(
            corrected_true_azimuth(compass, magnetic_correction),
            22.0,
        )

    def test_corrected_altitude_applies_offsets(self) -> None:
        _, _, inclinometer, _, _ = build_fixture_inputs()

        self.assertAlmostEqual(corrected_altitude(inclinometer), 41.5)

    def test_calculate_alignment_returns_rough_vs_solved_delta(self) -> None:
        site, compass, inclinometer, magnetic_correction, plate_solution = (
            build_fixture_inputs()
        )

        result = calculate_alignment(
            site,
            compass,
            inclinometer,
            magnetic_correction,
            plate_solution,
        )

        self.assertEqual(result.status, "solved")
        self.assertEqual(result.confidence, "fixture-high")
        self.assertAlmostEqual(result.rough_true_azimuth_deg, 22.0)
        self.assertAlmostEqual(result.rough_altitude_deg, 41.5)
        self.assertGreaterEqual(result.estimated_ra_deg, 0.0)
        self.assertLess(result.estimated_ra_deg, 360.0)
        self.assertGreaterEqual(result.solved_ra_deg, 0.0)
        self.assertLess(result.solved_ra_deg, 360.0)
        self.assertGreater(result.sky_separation_deg, 0.0)
        self.assertGreaterEqual(result.sky_position_angle_deg, 0.0)
        self.assertLess(result.sky_position_angle_deg, 360.0)
        self.assertGreaterEqual(result.solved_azimuth_deg, 0.0)
        self.assertLess(result.solved_azimuth_deg, 360.0)
        self.assertEqual(result.uncertainty_summary["refraction_model"], "none")

    def test_model_date_outside_validity_fails(self) -> None:
        site, compass, inclinometer, magnetic_correction, plate_solution = (
            build_fixture_inputs()
        )
        expired_site = ObservingSite(
            latitude_deg=site.latitude_deg,
            longitude_deg=site.longitude_deg,
            elevation_m=site.elevation_m,
            timestamp_utc="2031-01-01T00:00:00Z",
        )

        with self.assertRaises(ValueError):
            calculate_alignment(
                expired_site,
                compass,
                inclinometer,
                magnetic_correction,
                plate_solution,
            )

    def test_unsupported_plate_frame_fails(self) -> None:
        site, compass, inclinometer, magnetic_correction, plate_solution = (
            build_fixture_inputs()
        )
        bad_solution = PlateSolution(
            ra_deg=plate_solution.ra_deg,
            dec_deg=plate_solution.dec_deg,
            frame="GALACTIC",
            obstime=plate_solution.obstime,
            confidence=plate_solution.confidence,
            solver_name=plate_solution.solver_name,
            solver_version=plate_solution.solver_version,
        )

        with self.assertRaises(ValueError):
            calculate_alignment(
                site,
                compass,
                inclinometer,
                magnetic_correction,
                bad_solution,
            )


if __name__ == "__main__":
    unittest.main()

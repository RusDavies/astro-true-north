from __future__ import annotations

import json
import pathlib
import unittest

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def normalize_360(angle_deg: float) -> float:
    return angle_deg % 360.0


def signed_angle_delta(target_deg: float, reference_deg: float) -> float:
    return (target_deg - reference_deg + 180.0) % 360.0 - 180.0


class SensorFixtureTests(unittest.TestCase):
    def test_sensor_fixture_contains_first_input_shapes(self) -> None:
        fixture = load_fixture("sensor_samples.json")

        self.assertEqual(fixture["schema_version"], 1)
        self.assertEqual(len(fixture["observing_sites"]), 1)
        self.assertEqual(len(fixture["compass_samples"]), 1)
        self.assertEqual(len(fixture["inclinometer_samples"]), 1)
        self.assertEqual(len(fixture["camera_frames"]), 1)
        self.assertEqual(len(fixture["plate_solutions"]), 1)
        self.assertEqual(len(fixture["magnetic_corrections"]), 1)

    def test_sensor_fixture_uses_privacy_safe_handles(self) -> None:
        fixture = load_fixture("sensor_samples.json")
        site = fixture["observing_sites"][0]
        frame = fixture["camera_frames"][0]

        self.assertIn("synthetic", site["location_precision"])
        self.assertEqual(site["privacy_policy"], "do-not-log-precise-location")
        self.assertTrue(frame["source_handle"].startswith("synthetic://"))
        self.assertEqual(frame["privacy_policy"], "synthetic-no-image-data")

    def test_plate_solution_has_comparison_frame_metadata(self) -> None:
        fixture = load_fixture("sensor_samples.json")
        solution = fixture["plate_solutions"][0]

        self.assertEqual(solution["status"], "solved")
        self.assertEqual(solution["frame"], "ICRS")
        self.assertIsInstance(solution["ra_deg"], float)
        self.assertIsInstance(solution["dec_deg"], float)
        self.assertIsNone(solution["failure_reason"])


class AlignmentMathFixtureTests(unittest.TestCase):
    def test_declination_cases_match_documented_sign_convention(self) -> None:
        cases = {
            case["id"]: case for case in load_fixture("alignment_math_cases.json")["cases"]
        }

        for case_id in ("east_positive_declination", "west_declination_wraparound"):
            with self.subTest(case_id=case_id):
                case = cases[case_id]
                inputs = case["inputs"]
                expected = case["expected"]
                calculated = normalize_360(
                    inputs["magnetic_azimuth_deg"]
                    + inputs["magnetic_declination_deg"]
                    + inputs["compass_mount_offset_deg"]
                    + inputs["compass_calibration_offset_deg"]
                )

                self.assertAlmostEqual(calculated, expected["true_azimuth_deg"])

    def test_signed_azimuth_delta_cases_use_shortest_direction(self) -> None:
        cases = {
            case["id"]: case for case in load_fixture("alignment_math_cases.json")["cases"]
        }

        for case_id in ("local_azimuth_delta_wraparound", "synthetic_plate_delta"):
            with self.subTest(case_id=case_id):
                case = cases[case_id]
                inputs = case["inputs"]
                expected = case["expected"]
                calculated = signed_angle_delta(
                    inputs["solved_azimuth_deg"],
                    inputs["estimated_azimuth_deg"],
                )

                self.assertAlmostEqual(calculated, expected["local_azimuth_delta_deg"])

    def test_altitude_delta_case_is_direct_difference(self) -> None:
        cases = {
            case["id"]: case for case in load_fixture("alignment_math_cases.json")["cases"]
        }
        case = cases["synthetic_plate_delta"]
        inputs = case["inputs"]
        expected = case["expected"]

        calculated = inputs["solved_altitude_deg"] - inputs["estimated_altitude_deg"]

        self.assertAlmostEqual(calculated, expected["local_altitude_delta_deg"])

    def test_low_altitude_case_records_no_refraction_approximation(self) -> None:
        cases = {
            case["id"]: case for case in load_fixture("alignment_math_cases.json")["cases"]
        }
        case = cases["low_altitude_no_refraction"]

        self.assertEqual(case["inputs"]["atmospheric_refraction"], "disabled")
        self.assertEqual(case["expected"]["refraction_model"], "none")
        self.assertEqual(case["expected"]["status"], "degraded")


if __name__ == "__main__":
    unittest.main()

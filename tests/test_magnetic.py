from __future__ import annotations

import json
import math
import os
import pathlib
import shutil
import stat
import tempfile
import unittest

from astro_true_north.magnetic import (
    GeographicLibMagneticFieldProvider,
    MagneticAnnualChange,
    MagneticFieldVector,
    MagneticModelProvider,
    MagneticModelRequest,
    MagneticModelResult,
    MagneticUncertainty,
    _parse_magneticfield_output,
    check_model_epoch,
)

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"
RUN_REAL_GEOGRAPHICLIB_TESTS = (
    os.environ.get("ASTRO_TRUE_NORTH_RUN_GEOGRAPHICLIB_TESTS", "").lower()
    in {"1", "true", "yes", "on"}
)


def load_sensor_fixture() -> dict:
    with (FIXTURE_DIR / "sensor_samples.json").open(encoding="utf-8") as handle:
        return json.load(handle)


class FixtureMagneticProvider:
    model_name = "WMM2025"

    def __init__(self, result: MagneticModelResult) -> None:
        self._result = result

    def calculate(self, request: MagneticModelRequest) -> MagneticModelResult:
        return self._result


def fixture_result() -> MagneticModelResult:
    data = load_sensor_fixture()["magnetic_corrections"][0]
    return MagneticModelResult(
        model_name=data["model_name"],
        model_version=data["model_version"],
        valid_from=data["valid_from"],
        valid_until=data["valid_until"],
        source="tests/fixtures/sensor_samples.json",
        declination_deg=data["declination_deg"],
        inclination_deg=data["inclination_deg"],
        field_vector_nt=MagneticFieldVector(
            north_nt=data["field_vector_nt"]["north"],
            east_nt=data["field_vector_nt"]["east"],
            down_nt=data["field_vector_nt"]["down"],
        ),
        annual_change=MagneticAnnualChange(
            declination_deg_per_year=data["annual_change"][
                "declination_deg_per_year"
            ],
        ),
        uncertainty=MagneticUncertainty(
            declination_deg_1sigma=data["uncertainty"]["declination_deg_1sigma"],
        ),
    )


class MagneticProviderContractTests(unittest.TestCase):
    def test_fixture_provider_satisfies_protocol_shape(self) -> None:
        provider: MagneticModelProvider = FixtureMagneticProvider(fixture_result())
        site = load_sensor_fixture()["observing_sites"][0]
        request = MagneticModelRequest(
            latitude_deg=site["latitude_deg"],
            longitude_deg=site["longitude_deg"],
            elevation_m=site["elevation_m"],
            timestamp_utc=site["timestamp_utc"],
        )

        result = provider.calculate(request)

        self.assertEqual(result.model_name, "WMM2025")
        self.assertEqual(result.source, "tests/fixtures/sensor_samples.json")

    def test_wmm2025_fixture_contract_has_required_metadata(self) -> None:
        result = fixture_result()

        self.assertTrue(result.model_name.startswith("WMM2025"))
        self.assertLessEqual(result.valid_from, "2025-01-01")
        self.assertEqual(result.valid_until, "2029-12-31")
        self.assertTrue(math.isfinite(result.declination_deg))
        self.assertTrue(math.isfinite(result.inclination_deg))
        self.assertTrue(math.isfinite(result.field_vector_nt.north_nt))
        self.assertTrue(math.isfinite(result.field_vector_nt.east_nt))
        self.assertTrue(math.isfinite(result.field_vector_nt.down_nt))
        self.assertIsNotNone(result.annual_change.declination_deg_per_year)
        self.assertIsNotNone(result.uncertainty.declination_deg_1sigma)

    def test_request_defaults_to_wgs84_ellipsoid_height(self) -> None:
        request = MagneticModelRequest(
            latitude_deg=43.0,
            longitude_deg=-79.0,
            elevation_m=100.0,
            timestamp_utc="2026-07-14T00:00:00Z",
        )

        self.assertEqual(request.elevation_reference, "WGS84_ELLIPSOID")


class GeographicLibMagneticFieldProviderTests(unittest.TestCase):
    def test_parse_magneticfield_output(self) -> None:
        result = _parse_magneticfield_output(
            "-1.04 12.00 34015.6 34010.0 -618.0 7232.0 34775.9\n"
            "0.11 0.01 4.2 5.4 63.7 5.4 5.3\n",
            model_name="WMM2025",
            model_version="wmm2025",
            source="MagneticField",
        )

        self.assertEqual(result.model_name, "WMM2025")
        self.assertEqual(result.valid_until, "2029-12-31")
        self.assertAlmostEqual(result.declination_deg, -1.04)
        self.assertAlmostEqual(result.inclination_deg, 12.0)
        self.assertAlmostEqual(result.field_vector_nt.north_nt, 34010.0)
        self.assertAlmostEqual(result.field_vector_nt.east_nt, -618.0)
        self.assertAlmostEqual(result.field_vector_nt.down_nt, 7232.0)
        self.assertAlmostEqual(result.annual_change.declination_deg_per_year, 0.11)
        self.assertAlmostEqual(result.annual_change.total_intensity_nt_per_year, 5.3)

    def test_provider_calls_magneticfield_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = pathlib.Path(temp_dir) / "MagneticField"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "_ = sys.stdin.read()\n"
                "print('-1.04 12.00 34015.6 34010.0 -618.0 7232.0 34775.9')\n"
                "print('0.11 0.01 4.2 5.4 63.7 5.4 5.3')\n",
                encoding="utf-8",
            )
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            provider = GeographicLibMagneticFieldProvider(executable=str(executable))

            result = provider.calculate(
                MagneticModelRequest(
                    latitude_deg=16.775833,
                    longitude_deg=-3.009444,
                    elevation_m=300.0,
                    timestamp_utc="2025-01-01T00:00:00Z",
                )
            )

        self.assertEqual(result.model_name, "WMM2025")
        self.assertEqual(result.source, str(executable))

    def test_provider_rejects_non_wgs84_height_reference(self) -> None:
        provider = GeographicLibMagneticFieldProvider(executable="unused")

        with self.assertRaises(ValueError):
            provider.calculate(
                MagneticModelRequest(
                    latitude_deg=43.0,
                    longitude_deg=-79.0,
                    elevation_m=100.0,
                    timestamp_utc="2026-07-14T00:00:00Z",
                    elevation_reference="MEAN_SEA_LEVEL",
                )
            )

    def test_provider_reports_missing_executable(self) -> None:
        provider = GeographicLibMagneticFieldProvider(
            executable="definitely-not-MagneticField",
            timeout_s=0.1,
        )

        with self.assertRaises(RuntimeError):
            provider.calculate(
                MagneticModelRequest(
                    latitude_deg=43.0,
                    longitude_deg=-79.0,
                    elevation_m=100.0,
                    timestamp_utc="2026-07-14T00:00:00Z",
                )
            )


@unittest.skipUnless(
    RUN_REAL_GEOGRAPHICLIB_TESTS,
    "set ASTRO_TRUE_NORTH_RUN_GEOGRAPHICLIB_TESTS=1 to run real GeographicLib tests",
)
class GeographicLibMagneticFieldIntegrationTests(unittest.TestCase):
    def test_real_magneticfield_wmm2025_installation(self) -> None:
        executable = os.environ.get(
            "ASTRO_TRUE_NORTH_MAGNETICFIELD_EXECUTABLE",
            "MagneticField",
        )
        resolved_executable = shutil.which(executable) if "/" not in executable else executable
        if resolved_executable is None:
            self.fail(
                "MagneticField was not found. Install GeographicLib's MagneticField "
                "tool and WMM2025 magnetic model data, or set "
                "ASTRO_TRUE_NORTH_MAGNETICFIELD_EXECUTABLE=/path/to/MagneticField."
            )

        model_directory = os.environ.get(
            "ASTRO_TRUE_NORTH_GEOGRAPHICLIB_MAGNETIC_MODEL_DIR"
        )
        provider = GeographicLibMagneticFieldProvider(
            executable=resolved_executable,
            model_directory=model_directory,
            timeout_s=10.0,
        )

        try:
            result = provider.calculate(
                MagneticModelRequest(
                    latitude_deg=0.0,
                    longitude_deg=0.0,
                    elevation_m=0.0,
                    timestamp_utc="2025-01-01T00:00:00Z",
                )
            )
        except RuntimeError as exc:
            self.fail(
                "Real GeographicLib MagneticField execution failed. Confirm the "
                "WMM2025 model data is installed and readable, or set "
                "ASTRO_TRUE_NORTH_GEOGRAPHICLIB_MAGNETIC_MODEL_DIR."
                f" Original error: {exc}"
            )

        self.assertEqual(result.model_name, "WMM2025")
        self.assertEqual(result.model_version, "wmm2025")
        self.assertEqual(result.valid_until, "2029-12-31")
        self.assertTrue(math.isfinite(result.declination_deg))
        self.assertTrue(math.isfinite(result.inclination_deg))
        self.assertTrue(math.isfinite(result.field_vector_nt.north_nt))
        self.assertTrue(math.isfinite(result.field_vector_nt.east_nt))
        self.assertTrue(math.isfinite(result.field_vector_nt.down_nt))
        self.assertIsNotNone(result.annual_change.declination_deg_per_year)


class ModelEpochStatusTests(unittest.TestCase):
    def test_epoch_check_is_current_before_warning_window(self) -> None:
        status = check_model_epoch(
            fixture_result(),
            checked_on="2028-01-01T00:00:00Z",
        )

        self.assertEqual(status.state, "current")
        self.assertGreater(status.days_until_expiry, 365)

    def test_epoch_check_warns_inside_update_window(self) -> None:
        status = check_model_epoch(
            fixture_result(),
            checked_on="2029-01-01T00:00:00Z",
        )

        self.assertEqual(status.state, "update_due")
        self.assertIn("expires on 2029-12-31", status.message)

    def test_epoch_check_fails_after_expiry(self) -> None:
        status = check_model_epoch(
            fixture_result(),
            checked_on="2030-01-01T00:00:00Z",
        )

        self.assertEqual(status.state, "expired")
        self.assertLess(status.days_until_expiry, 0)
        self.assertIn("expired", status.message)


if __name__ == "__main__":
    unittest.main()

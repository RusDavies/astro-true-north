from __future__ import annotations

import json
import math
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import unittest

from astro_true_north.plate_solving import (
    AstrometryNetSolveFieldProvider,
    AstapPlateSolverProvider,
    FixturePlateSolver,
    PlateSolution,
    PlateSolver,
    PlateSolverRequest,
    camera_frame_from_record,
    plate_solution_from_record,
    validate_plate_solution,
)

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"
RUN_REAL_SOLVE_FIELD_TESTS = (
    os.environ.get("ASTRO_TRUE_NORTH_RUN_SOLVE_FIELD_TESTS", "").lower()
    in {"1", "true", "yes", "on"}
)


def load_fixture() -> dict:
    with (FIXTURE_DIR / "sensor_samples.json").open(encoding="utf-8") as handle:
        return json.load(handle)


class PlateSolverContractTests(unittest.TestCase):
    def test_fixture_records_build_plate_solver_inputs(self) -> None:
        fixture = load_fixture()
        frame = camera_frame_from_record(fixture["camera_frames"][0])
        solution = plate_solution_from_record(fixture["plate_solutions"][0])

        self.assertEqual(frame.id, "synthetic_center_frame")
        self.assertEqual(frame.privacy_policy, "synthetic-no-image-data")
        self.assertEqual(solution.status, "solved")
        self.assertEqual(solution.frame, "ICRS")
        self.assertAlmostEqual(solution.field_of_view_deg, 1.25)
        self.assertAlmostEqual(solution.pixel_scale_arcsec, 2.34)

    def test_fixture_solver_satisfies_protocol_shape(self) -> None:
        fixture = load_fixture()
        frame = camera_frame_from_record(fixture["camera_frames"][0])
        solution = plate_solution_from_record(fixture["plate_solutions"][0])
        solver: PlateSolver = FixturePlateSolver({frame.id: solution})

        result = solver.solve(PlateSolverRequest(camera_frame=frame))

        self.assertEqual(result.status, "solved")
        self.assertEqual(result.solver_name, "synthetic-fixture")
        self.assertGreaterEqual(result.ra_deg, 0.0)
        self.assertLess(result.ra_deg, 360.0)
        self.assertIsNone(result.failure_reason)

    def test_missing_fixture_solution_returns_clear_failure(self) -> None:
        fixture = load_fixture()
        frame = camera_frame_from_record(fixture["camera_frames"][0])
        solver = FixturePlateSolver({})

        result = solver.solve(PlateSolverRequest(camera_frame=frame))

        self.assertEqual(result.status, "failed")
        self.assertIn(frame.id, result.failure_reason or "")

    def test_invalid_solved_solution_fails_contract(self) -> None:
        with self.assertRaises(ValueError):
            validate_plate_solution(
                PlateSolution(
                    ra_deg=400.0,
                    dec_deg=38.0,
                    frame="ICRS",
                    obstime="2026-07-14T02:30:05Z",
                    confidence="bad-fixture",
                    solver_name="synthetic-fixture",
                    solver_version="0",
                )
            )

    def test_failed_solution_requires_failure_reason(self) -> None:
        with self.assertRaises(ValueError):
            validate_plate_solution(
                PlateSolution(
                    ra_deg=float("nan"),
                    dec_deg=float("nan"),
                    frame="",
                    obstime="2026-07-14T02:30:05Z",
                    confidence="none",
                    solver_name="synthetic-fixture",
                    solver_version="0",
                    status="failed",
                )
            )


class AstrometryNetSolveFieldProviderTests(unittest.TestCase):
    def test_fake_solve_field_executable_returns_normalized_solution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            frame_path = temp_path / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            executable = _write_fake_solve_field(temp_path)
            provider = AstrometryNetSolveFieldProvider(executable=str(executable))
            frame = _camera_frame_for_path(frame_path)

            result = provider.solve(
                PlateSolverRequest(
                    camera_frame=frame,
                    field_of_view_hint_deg=1.25,
                    approximate_ra_deg=279.0,
                    approximate_dec_deg=38.0,
                    search_radius_hint_deg=5.0,
                    timeout_s=5.0,
                )
            )

        self.assertEqual(result.status, "solved")
        self.assertEqual(result.solver_name, "astrometry.net solve-field")
        self.assertEqual(result.solver_version, "fake solve-field 0")
        self.assertAlmostEqual(result.ra_deg, 279.234)
        self.assertAlmostEqual(result.dec_deg, 38.783)
        self.assertAlmostEqual(result.pixel_scale_arcsec, 2.34)
        self.assertAlmostEqual(result.field_of_view_deg, 1920 * 2.34 / 3600.0)
        self.assertEqual(result.index_source, "index-4208")
        self.assertIn("<frame>", result.command_summary or "")
        self.assertNotIn(str(frame_path), result.command_summary or "")

    def test_missing_solve_field_executable_returns_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            frame_path = pathlib.Path(temp_dir) / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            frame = _camera_frame_for_path(frame_path)
            provider = AstrometryNetSolveFieldProvider(executable="missing-solve-field")

            result = provider.solve(PlateSolverRequest(camera_frame=frame))

        self.assertEqual(result.status, "failed")
        self.assertIn("executable not found", result.failure_reason or "")

    def test_solve_field_rejects_non_executable_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            frame_path = temp_path / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            executable = temp_path / "solve-field"
            executable.write_text("", encoding="utf-8")
            provider = AstrometryNetSolveFieldProvider(executable=str(executable))

            result = provider.solve(
                PlateSolverRequest(camera_frame=_camera_frame_for_path(frame_path))
            )

        self.assertEqual(result.status, "failed")
        self.assertIn("executable not found", result.failure_reason or "")

    def test_solver_process_failure_returns_normalized_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            frame_path = temp_path / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            executable = _write_failing_solve_field(temp_path)
            provider = AstrometryNetSolveFieldProvider(executable=str(executable))

            result = provider.solve(
                PlateSolverRequest(camera_frame=_camera_frame_for_path(frame_path))
            )

        self.assertEqual(result.status, "failed")
        self.assertIn("no stars found", result.failure_reason or "")


class AstapPlateSolverProviderTests(unittest.TestCase):
    def test_fake_astap_executable_returns_normalized_solution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            frame_path = temp_path / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            executable = _write_fake_astap(temp_path)
            provider = AstapPlateSolverProvider(
                executable=str(executable),
                database_path=temp_path / "astap-db",
                database_name="d50",
            )
            frame = _camera_frame_for_path(frame_path)

            result = provider.solve(
                PlateSolverRequest(
                    camera_frame=frame,
                    field_of_view_hint_deg=1.25,
                    approximate_ra_deg=279.0,
                    approximate_dec_deg=38.0,
                    search_radius_hint_deg=5.0,
                    timeout_s=5.0,
                )
            )

        self.assertEqual(result.status, "solved")
        self.assertEqual(result.solver_name, "ASTAP")
        self.assertEqual(result.solver_version, "fake ASTAP 0")
        self.assertAlmostEqual(result.ra_deg, 279.234)
        self.assertAlmostEqual(result.dec_deg, 38.783)
        self.assertAlmostEqual(result.pixel_scale_arcsec, 2.34)
        self.assertAlmostEqual(result.field_of_view_deg, 1920 * 2.34 / 3600.0)
        self.assertEqual(result.index_source, "d50")
        self.assertIn("<frame>", result.command_summary or "")
        self.assertNotIn(str(frame_path), result.command_summary or "")

    def test_astap_receives_height_fov_and_coordinate_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            frame_path = temp_path / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            executable = _write_fake_astap(temp_path)
            provider = AstapPlateSolverProvider(executable=str(executable))

            result = provider.solve(
                PlateSolverRequest(
                    camera_frame=_camera_frame_for_path(frame_path),
                    field_of_view_hint_deg=1.25,
                    approximate_ra_deg=180.0,
                    approximate_dec_deg=-30.0,
                    search_radius_hint_deg=7.0,
                    timeout_s=5.0,
                )
            )

            command = result.command_summary or ""

        self.assertIn("-fov 0.703125", command)
        self.assertIn("-ra 12.00000000", command)
        self.assertIn("-spd 60.00000000", command)
        self.assertIn("-r 7.000000", command)

    def test_astap_process_failure_returns_normalized_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            frame_path = temp_path / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            executable = _write_failing_astap(temp_path)
            provider = AstapPlateSolverProvider(executable=str(executable))

            result = provider.solve(
                PlateSolverRequest(camera_frame=_camera_frame_for_path(frame_path))
            )

        self.assertEqual(result.status, "failed")
        self.assertIn("not enough stars", result.failure_reason or "")

    def test_missing_astap_executable_returns_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            frame_path = pathlib.Path(temp_dir) / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            frame = _camera_frame_for_path(frame_path)
            provider = AstapPlateSolverProvider(executable="missing-astap")

            result = provider.solve(PlateSolverRequest(camera_frame=frame))

        self.assertEqual(result.status, "failed")
        self.assertIn("executable not found", result.failure_reason or "")

    def test_astap_rejects_non_executable_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            frame_path = temp_path / "frame.fits"
            frame_path.write_bytes(b"fake image bytes")
            executable = temp_path / "astap"
            executable.write_text("", encoding="utf-8")
            provider = AstapPlateSolverProvider(executable=str(executable))

            result = provider.solve(
                PlateSolverRequest(camera_frame=_camera_frame_for_path(frame_path))
            )

        self.assertEqual(result.status, "failed")
        self.assertIn("executable not found", result.failure_reason or "")


@unittest.skipUnless(
    RUN_REAL_SOLVE_FIELD_TESTS,
    "set ASTRO_TRUE_NORTH_RUN_SOLVE_FIELD_TESTS=1 to run real solve-field tests",
)
class AstrometryNetSolveFieldIntegrationTests(unittest.TestCase):
    def test_real_solve_field_installation(self) -> None:
        executable = os.environ.get(
            "ASTRO_TRUE_NORTH_SOLVE_FIELD_EXECUTABLE",
            "solve-field",
        )
        resolved_executable = _resolve_test_executable(executable)
        if resolved_executable is None:
            self.fail(
                "solve-field was not found. Install local astrometry.net with "
                "index files, or set "
                "ASTRO_TRUE_NORTH_SOLVE_FIELD_EXECUTABLE=/path/to/solve-field."
            )

        image_path = os.environ.get("ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_IMAGE")
        if not image_path:
            self.fail(
                "Set ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_IMAGE to a public or "
                "synthetic local sky image. Do not use a private observing image."
            )
        frame_path = pathlib.Path(image_path)
        if not frame_path.exists():
            self.fail(f"solve-field test image does not exist: {frame_path}")

        provider = AstrometryNetSolveFieldProvider(executable=resolved_executable)
        result = provider.solve(
            PlateSolverRequest(
                camera_frame=_camera_frame_for_path(frame_path),
                field_of_view_hint_deg=_optional_env_float(
                    "ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_FOV_DEG"
                ),
                pixel_scale_hint_arcsec=_optional_env_float(
                    "ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_PIXEL_SCALE_ARCSEC"
                ),
                approximate_ra_deg=_optional_env_float(
                    "ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_RA_DEG"
                ),
                approximate_dec_deg=_optional_env_float(
                    "ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_DEC_DEG"
                ),
                search_radius_hint_deg=_optional_env_float(
                    "ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_RADIUS_DEG"
                ),
                timeout_s=_optional_env_float(
                    "ASTRO_TRUE_NORTH_SOLVE_FIELD_TEST_TIMEOUT_S"
                )
                or 120.0,
            )
        )

        self.assertEqual(result.status, "solved", result.failure_reason)
        self.assertEqual(result.solver_name, "astrometry.net solve-field")
        self.assertTrue(math.isfinite(result.ra_deg))
        self.assertTrue(math.isfinite(result.dec_deg))
        self.assertEqual(result.frame, "ICRS")
        self.assertIsNone(result.failure_reason)


def _camera_frame_for_path(path: pathlib.Path):
    return camera_frame_from_record(
        {
            "id": "local_test_frame",
            "timestamp_utc": "2026-07-14T02:30:05Z",
            "source_handle": str(path),
            "privacy_policy": "synthetic-no-image-data",
            "exposure_s": 2.0,
            "gain": 120,
            "pixel_width": 1920,
            "pixel_height": 1080,
        }
    )


def _write_fake_solve_field(directory: pathlib.Path) -> pathlib.Path:
    executable = directory / "solve-field"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from astropy.io import fits\n"
        "import pathlib\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        "    print('fake solve-field 0')\n"
        "    raise SystemExit(0)\n"
        "out_dir = pathlib.Path(sys.argv[sys.argv.index('--dir') + 1])\n"
        "header = fits.Header()\n"
        "header['CRVAL1'] = 279.234\n"
        "header['CRVAL2'] = 38.783\n"
        "header['RADESYS'] = 'ICRS'\n"
        "header['IMAGEW'] = 1920\n"
        "header['IMAGEH'] = 1080\n"
        "header['PIXSCALE'] = 2.34\n"
        "header['ANINDEX'] = 'index-4208'\n"
        "fits.PrimaryHDU(header=header).writeto(out_dir / 'solve.wcs')\n"
        "(out_dir / 'solve.solved').write_bytes(b'1')\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _write_failing_solve_field(directory: pathlib.Path) -> pathlib.Path:
    executable = directory / "solve-field-fail"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        "    print('fake solve-field 0')\n"
        "    raise SystemExit(0)\n"
        "print('no stars found', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _write_fake_astap(directory: pathlib.Path) -> pathlib.Path:
    executable = directory / "astap"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from astropy.io import fits\n"
        "import pathlib\n"
        "import sys\n"
        "if '-h' in sys.argv or '-help' in sys.argv:\n"
        "    print('fake ASTAP 0')\n"
        "    raise SystemExit(0)\n"
        "out_base = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "database = sys.argv[sys.argv.index('-D') + 1] if '-D' in sys.argv else ''\n"
        "header = fits.Header()\n"
        "header['CRVAL1'] = 279.234\n"
        "header['CRVAL2'] = 38.783\n"
        "header['RADESYS'] = 'ICRS'\n"
        "header['IMAGEW'] = 1920\n"
        "header['IMAGEH'] = 1080\n"
        "header['PIXSCALE'] = 2.34\n"
        "fits.PrimaryHDU(header=header).writeto(out_base.with_suffix('.wcs'))\n"
        "out_base.with_suffix('.ini').write_text(\n"
        "    'PLTSOLVD=T\\nDATABASE=' + database + '\\n', encoding='utf-8'\n"
        ")\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _write_failing_astap(directory: pathlib.Path) -> pathlib.Path:
    executable = directory / "astap-fail"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import pathlib\n"
        "import sys\n"
        "if '-h' in sys.argv or '-help' in sys.argv:\n"
        "    print('fake ASTAP 0')\n"
        "    raise SystemExit(0)\n"
        "out_base = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "out_base.with_suffix('.ini').write_text(\n"
        "    'PLTSOLVD=F\\nERROR=not enough stars\\n', encoding='utf-8'\n"
        ")\n"
        "print('not enough stars', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _resolve_test_executable(executable: str) -> str | None:
    if "/" in executable:
        return executable if pathlib.Path(executable).exists() else None
    return shutil.which(executable)


def _optional_env_float(name: str) -> float | None:
    value = os.environ.get(name)
    return None if value in {None, ""} else float(value)


if __name__ == "__main__":
    unittest.main()

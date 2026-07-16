from __future__ import annotations

import json
import pathlib
import unittest

from astro_true_north.pipeline import (
    fixture_pipeline_from_record,
    format_alignment_delta_report,
    load_fixture_pipeline,
    run_alignment_pipeline,
)
from astro_true_north.plate_solving import FixturePlateSolver

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def load_fixture() -> dict:
    with (FIXTURE_DIR / "sensor_samples.json").open(encoding="utf-8") as handle:
        return json.load(handle)


class AlignmentPipelineTests(unittest.TestCase):
    def test_fixture_pipeline_reports_estimated_vs_solved_delta(self) -> None:
        pipeline_input, solver = load_fixture_pipeline(
            FIXTURE_DIR / "sensor_samples.json"
        )

        result = run_alignment_pipeline(pipeline_input, solver)

        self.assertEqual(result.status, "solved")
        self.assertIsNotNone(result.alignment)
        assert result.alignment is not None
        self.assertIn("Sky check complete", result.operator_message)
        self.assertGreater(result.alignment.sky_separation_deg, 0.0)
        report = "\n".join(result.report_lines)
        self.assertIn("Estimated-vs-solved pointing delta", report)
        self.assertIn("Operator message:", report)
        self.assertIn("Local correction:", report)
        self.assertIn("Sky separation:", report)
        self.assertNotIn(str(pipeline_input.site.latitude_deg), report)
        self.assertNotIn(str(pipeline_input.site.longitude_deg), report)

    def test_fixture_pipeline_uses_plate_solution_fixture_as_hints(self) -> None:
        pipeline_input, _ = fixture_pipeline_from_record(load_fixture())

        self.assertAlmostEqual(pipeline_input.field_of_view_hint_deg or 0.0, 1.25)
        self.assertAlmostEqual(
            pipeline_input.pixel_scale_hint_arcsec or 0.0,
            2.34,
        )

    def test_plate_solver_failure_returns_pipeline_failure(self) -> None:
        pipeline_input, _ = fixture_pipeline_from_record(load_fixture())

        result = run_alignment_pipeline(pipeline_input, FixturePlateSolver({}))

        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.alignment)
        report = "\n".join(result.report_lines)
        self.assertIn("Operator message:", report)
        self.assertIn("Failure:", report)
        self.assertIn("camera image did not match", result.operator_message)

    def test_report_formatter_keeps_stable_report_title(self) -> None:
        pipeline_input, solver = fixture_pipeline_from_record(load_fixture())
        result = run_alignment_pipeline(pipeline_input, solver)
        assert result.alignment is not None

        report_lines = format_alignment_delta_report(
            result.alignment,
            result.plate_solution,
        )

        self.assertEqual(report_lines[0], "Estimated-vs-solved pointing delta")


if __name__ == "__main__":
    unittest.main()

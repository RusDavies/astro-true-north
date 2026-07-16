"""Command-line entrypoint for the first Astro True North prototype."""

from __future__ import annotations

import argparse

from astro_true_north import __version__
from astro_true_north.bn220 import capture_bn220
from astro_true_north.pipeline import load_fixture_pipeline, run_alignment_pipeline
from astro_true_north.wt901 import capture_wt901, capture_wt901_calibration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astro-true-north",
        description="Sensor-assisted telescope alignment prototype.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="show the prototype version and exit",
    )
    parser.add_argument(
        "--fixture-pipeline",
        metavar="PATH",
        help="run the prototype alignment pipeline with a fixture JSON file",
    )
    parser.add_argument(
        "--sample-wt901",
        metavar="PORT",
        help="sample a WT901 serial device and print a movement summary",
    )
    parser.add_argument(
        "--wt901-baud",
        type=int,
        default=9600,
        help="WT901 serial baud rate for --sample-wt901 (default: 9600)",
    )
    parser.add_argument(
        "--wt901-duration",
        type=float,
        default=10.0,
        help="WT901 capture duration in seconds for --sample-wt901 (default: 10)",
    )
    parser.add_argument(
        "--calibrate-wt901",
        metavar="PORT",
        help="capture a stationary WT901 sample and estimate first error budgets",
    )
    parser.add_argument(
        "--sample-bn220",
        metavar="PORT",
        help="sample a BN-220 GPS serial device and print a privacy-safe summary",
    )
    parser.add_argument(
        "--bn220-baud",
        type=int,
        default=9600,
        help="BN-220 serial baud rate for --sample-bn220 (default: 9600)",
    )
    parser.add_argument(
        "--gps-duration",
        type=float,
        default=10.0,
        help="GPS capture duration in seconds for --sample-bn220 (default: 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"astro-true-north {__version__}")
        return 0
    if args.fixture_pipeline:
        pipeline_input, solver = load_fixture_pipeline(args.fixture_pipeline)
        result = run_alignment_pipeline(pipeline_input, solver)
        print("\n".join(result.report_lines))
        return 0 if result.status == "solved" else 1
    if args.sample_wt901:
        summary = capture_wt901(
            args.sample_wt901,
            baud=args.wt901_baud,
            duration_seconds=args.wt901_duration,
            prompt=(
                "Sampling WT901. Move the unit through slow roll, pitch, and yaw "
                "changes until the capture finishes."
            ),
        )
        print("\n".join(summary.report_lines()))
        return 0 if summary.angle_samples else 1
    if args.calibrate_wt901:
        report = capture_wt901_calibration(
            args.calibrate_wt901,
            baud=args.wt901_baud,
            duration_seconds=args.wt901_duration,
            prompt="Sampling WT901 calibration. Keep the unit still until capture finishes.",
        )
        print("\n".join(report.report_lines()))
        return 0 if report.status != "insufficient-data" else 1
    if args.sample_bn220:
        summary = capture_bn220(
            args.sample_bn220,
            baud=args.bn220_baud,
            duration_seconds=args.gps_duration,
            prompt="Sampling BN-220 GPS. Keep the antenna where it has sky view.",
        )
        print("\n".join(summary.report_lines()))
        return 0 if summary.fix and summary.fix.has_fix else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

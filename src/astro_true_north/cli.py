"""Command-line entrypoint for the first Astro True North prototype."""

from __future__ import annotations

import argparse
import os
import sys

from astro_true_north import __version__
from astro_true_north.bn220 import capture_bn220
from astro_true_north.nexstar import (
    MountMotionLockedError,
    NexStarProtocolError,
    execute_slow_yaw,
    query_nexstar_status,
    validate_slow_yaw_plan,
)
from astro_true_north.pipeline import load_fixture_pipeline, run_alignment_pipeline
from astro_true_north.serial_discovery import discover_serial_ports, resolve_sensor_port
from astro_true_north.wt901 import (
    capture_wt901,
    capture_wt901_calibration,
    format_wt901_stream_header,
    stream_wt901_channel_lines,
)


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
        help="sample a WT901 serial device and print a movement summary; use 'auto' to probe",
    )
    parser.add_argument(
        "--stream-wt901",
        metavar="PORT",
        help="stream decoded WT901 channel rows as CSV; use 'auto' to probe",
    )
    parser.add_argument(
        "--wt901-overwrite",
        action="store_true",
        help="with --stream-wt901, update a four-row terminal dashboard instead of scrolling",
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
        help="capture a stationary WT901 sample and estimate first error budgets; use 'auto' to probe",
    )
    parser.add_argument(
        "--sample-bn220",
        metavar="PORT",
        help="sample a BN-220 GPS serial device and print a privacy-safe summary; use 'auto' to probe",
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
    parser.add_argument(
        "--discover-serial",
        action="store_true",
        help="probe local serial ports and identify supported sensor streams",
    )
    parser.add_argument(
        "--serial-probe-duration",
        type=float,
        default=2.0,
        help="seconds to spend probing each serial port for auto-discovery (default: 2)",
    )
    parser.add_argument(
        "--nexstar-status",
        metavar="PORT",
        help="read basic NexStar hand-controller status without moving the mount",
    )
    parser.add_argument(
        "--nexstar-baud",
        type=int,
        default=9600,
        help="NexStar hand-controller serial baud rate (default: 9600)",
    )
    parser.add_argument(
        "--plan-nexstar-slow-yaw",
        choices=("left", "right"),
        metavar="DIRECTION",
        help="validate a guarded NexStar slow-yaw plan without sending motor commands",
    )
    parser.add_argument(
        "--execute-nexstar-slow-yaw",
        metavar="PORT",
        help="execute a guarded NexStar slow-yaw plan after all approval gates pass",
    )
    parser.add_argument(
        "--nexstar-yaw-rate-deg-sec",
        type=float,
        default=0.25,
        help="planned NexStar yaw rate in degrees per second (default: 0.25)",
    )
    parser.add_argument(
        "--nexstar-yaw-duration",
        type=float,
        default=30.0,
        help="planned NexStar yaw duration in seconds (default: 30)",
    )
    parser.add_argument(
        "--approve-mount-motion",
        action="store_true",
        help="explicitly approve the planned mount motion",
    )
    parser.add_argument(
        "--mount-abort-ready",
        action="store_true",
        help="confirm a stop/abort path is ready for the planned mount motion",
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
    if args.discover_serial:
        results = discover_serial_ports(
            baud=args.wt901_baud,
            duration_seconds=args.serial_probe_duration,
        )
        print("Serial discovery summary")
        if not results:
            print("No candidate serial ports found.")
            return 1
        for result in results:
            print(result.report_line())
        return 0 if any(result.looks_like_wt901 or result.looks_like_bn220 for result in results) else 1
    if args.sample_wt901:
        port = resolve_cli_port(
            args.sample_wt901,
            target="wt901",
            baud=args.wt901_baud,
            duration_seconds=args.serial_probe_duration,
        )
        if port is None:
            return 1
        summary = capture_wt901(
            port,
            baud=args.wt901_baud,
            duration_seconds=args.wt901_duration,
            prompt=(
                "Sampling WT901. Move the unit through slow roll, pitch, and yaw "
                "changes until the capture finishes."
            ),
        )
        print("\n".join(summary.report_lines()))
        return 0 if summary.angle_samples else 1
    if args.stream_wt901:
        port = resolve_cli_port(
            args.stream_wt901,
            target="wt901",
            baud=args.wt901_baud,
            duration_seconds=args.serial_probe_duration,
        )
        if port is None:
            return 1
        lines_seen = 0
        overwrite_rows = ("accel", "gyro", "angle", "mag")
        latest_rows = {channel: f"{channel}: waiting for frame" for channel in overwrite_rows}
        if args.wt901_overwrite:
            for channel in overwrite_rows:
                print(latest_rows[channel], flush=True)
        else:
            print(format_wt901_stream_header(), flush=True)
        try:
            for line in stream_wt901_channel_lines(
                port,
                baud=args.wt901_baud,
                duration_seconds=args.wt901_duration,
            ):
                if args.wt901_overwrite:
                    channel = wt901_stream_channel(line)
                    if channel in latest_rows:
                        latest_rows[channel] = line
                    print(f"\x1b[{len(overwrite_rows)}F", end="")
                    for channel in overwrite_rows:
                        print(f"\x1b[K{latest_rows[channel]}", flush=True)
                else:
                    print(line, flush=True)
                lines_seen += 1
        except BrokenPipeError:
            sys.stdout = open(os.devnull, "w")
            return 0
        if args.wt901_overwrite and lines_seen:
            print()
        return 0 if lines_seen else 1
    if args.calibrate_wt901:
        port = resolve_cli_port(
            args.calibrate_wt901,
            target="wt901",
            baud=args.wt901_baud,
            duration_seconds=args.serial_probe_duration,
        )
        if port is None:
            return 1
        report = capture_wt901_calibration(
            port,
            baud=args.wt901_baud,
            duration_seconds=args.wt901_duration,
            prompt="Sampling WT901 calibration. Keep the unit still until capture finishes.",
        )
        print("\n".join(report.report_lines()))
        return 0 if report.status != "insufficient-data" else 1
    if args.sample_bn220:
        port = resolve_cli_port(
            args.sample_bn220,
            target="bn220",
            baud=args.bn220_baud,
            duration_seconds=args.serial_probe_duration,
        )
        if port is None:
            return 1
        summary = capture_bn220(
            port,
            baud=args.bn220_baud,
            duration_seconds=args.gps_duration,
            prompt="Sampling BN-220 GPS. Keep the antenna where it has sky view.",
        )
        print("\n".join(summary.report_lines()))
        return 0 if summary.fix and summary.fix.has_fix else 1
    if args.nexstar_status:
        try:
            status = query_nexstar_status(
                args.nexstar_status,
                baud=args.nexstar_baud,
            )
        except (NexStarProtocolError, OSError) as exc:
            print(f"NexStar status read failed: {exc}")
            return 1
        print("\n".join(status.report_lines()))
        return 0
    if args.plan_nexstar_slow_yaw:
        try:
            plan = validate_slow_yaw_plan(
                direction=args.plan_nexstar_slow_yaw,
                rate_deg_per_sec=args.nexstar_yaw_rate_deg_sec,
                duration_seconds=args.nexstar_yaw_duration,
                operator_approved=args.approve_mount_motion,
                abort_ready=args.mount_abort_ready,
            )
        except MountMotionLockedError as exc:
            print(f"NexStar slow-yaw plan locked: {exc}")
            return 1
        if args.execute_nexstar_slow_yaw:
            try:
                lines = execute_slow_yaw(
                    args.execute_nexstar_slow_yaw,
                    plan,
                    baud=args.nexstar_baud,
                )
            except (MountMotionLockedError, NexStarProtocolError, OSError) as exc:
                print(f"NexStar slow-yaw execution failed: {exc}")
                return 1
            print("\n".join(lines))
            return 0
        print("\n".join(plan.report_lines()))
        return 0
    if args.execute_nexstar_slow_yaw:
        print("--execute-nexstar-slow-yaw requires --plan-nexstar-slow-yaw")
        return 1

    parser.print_help()
    return 0


def resolve_cli_port(
    port: str,
    *,
    target: str,
    baud: int,
    duration_seconds: float,
) -> str | None:
    if port != "auto":
        return port

    resolved, results = resolve_sensor_port(
        target,
        baud=baud,
        duration_seconds=duration_seconds,
    )
    target_label = "BN-220" if target == "bn220" else target.upper()
    print(f"Auto-discovering {target_label} serial port.")
    for result in results:
        print(result.report_line())
    if resolved is None:
        print(f"No {target_label} serial stream found.")
        return None
    print(f"Using {resolved}.")
    return resolved


def wt901_stream_channel(line: str) -> str:
    parts = line.split(",", maxsplit=2)
    if len(parts) < 2:
        return ""
    return parts[1]


if __name__ == "__main__":
    raise SystemExit(main())

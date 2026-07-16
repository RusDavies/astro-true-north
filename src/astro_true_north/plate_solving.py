"""Plate-solving adapter boundary and fixture helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Mapping, Protocol

from astropy.io import fits

_ALLOWED_ASTAP_COMMANDS = frozenset({"astap", "astap_cli"})
_ALLOWED_SOLVE_FIELD_COMMANDS = frozenset({"solve-field"})


@dataclass(frozen=True)
class CameraFrame:
    id: str
    timestamp_utc: str
    source_handle: str
    privacy_policy: str
    exposure_s: float
    pixel_width: int
    pixel_height: int
    gain: float | int | None = None


@dataclass(frozen=True)
class PlateSolverRequest:
    camera_frame: CameraFrame
    field_of_view_hint_deg: float | None = None
    pixel_scale_hint_arcsec: float | None = None
    approximate_ra_deg: float | None = None
    approximate_dec_deg: float | None = None
    search_radius_hint_deg: float | None = None
    timeout_s: float = 60.0
    offline_only: bool = True


@dataclass(frozen=True)
class PlateSolution:
    ra_deg: float
    dec_deg: float
    frame: str
    obstime: str
    confidence: str
    solver_name: str
    solver_version: str
    status: str = "solved"
    field_of_view_deg: float | None = None
    pixel_scale_arcsec: float | None = None
    failure_reason: str | None = None
    index_source: str | None = None
    command_summary: str | None = None


class PlateSolver(Protocol):
    """Provider interface for offline plate-solving adapters."""

    solver_name: str

    def solve(self, request: PlateSolverRequest) -> PlateSolution:
        """Return normalized sky coordinates or a clear solver failure."""


class FixturePlateSolver:
    """Deterministic fixture-backed solver for adapter contract tests."""

    solver_name = "fixture-plate-solver"

    def __init__(self, solutions_by_frame_id: Mapping[str, PlateSolution]) -> None:
        self._solutions_by_frame_id = dict(solutions_by_frame_id)

    def solve(self, request: PlateSolverRequest) -> PlateSolution:
        try:
            solution = self._solutions_by_frame_id[request.camera_frame.id]
        except KeyError:
            return PlateSolution(
                ra_deg=float("nan"),
                dec_deg=float("nan"),
                frame="",
                obstime=request.camera_frame.timestamp_utc,
                confidence="none",
                solver_name=self.solver_name,
                solver_version="fixture",
                status="failed",
                failure_reason=(
                    f"no fixture plate solution for frame {request.camera_frame.id}"
                ),
            )

        validate_plate_solution(solution)
        return solution


class AstrometryNetSolveFieldProvider:
    """Subprocess adapter for a local astrometry.net solve-field executable."""

    solver_name = "astrometry.net solve-field"

    def __init__(
        self,
        executable: str = "solve-field",
        work_parent: str | Path | None = None,
        keep_workdir: bool = False,
    ) -> None:
        self.executable = executable
        self.work_parent = Path(work_parent) if work_parent else None
        self.keep_workdir = keep_workdir

    def solve(self, request: PlateSolverRequest) -> PlateSolution:
        frame_path = _local_frame_path(request.camera_frame.source_handle)
        if not frame_path.exists():
            return _failed_solution(
                request,
                self.solver_name,
                "unknown",
                "camera frame path does not exist",
            )

        resolved_executable = _resolve_executable(
            self.executable,
            allowed_command_names=_ALLOWED_SOLVE_FIELD_COMMANDS,
        )
        if resolved_executable is None:
            return _failed_solution(
                request,
                self.solver_name,
                "unknown",
                "solve-field executable not found",
            )

        with tempfile.TemporaryDirectory(
            prefix="astro-true-north-solve-",
            dir=self.work_parent,
        ) as temp_dir:
            workdir = Path(temp_dir)
            command = _solve_field_command(
                resolved_executable,
                frame_path,
                workdir,
                request,
            )
            try:
                # argv-only subprocess call after resolving an allowlisted command
                # name or an explicit executable file path; no shell is involved.
                completed = subprocess.run(  # nosemgrep
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=request.timeout_s,
                )
            except FileNotFoundError:
                return _failed_solution(
                    request,
                    self.solver_name,
                    "unknown",
                    "solve-field executable not found",
                )
            except subprocess.TimeoutExpired:
                return _failed_solution(
                    request,
                    self.solver_name,
                    "unknown",
                    f"solve-field timed out after {request.timeout_s:g}s",
                )

            if completed.returncode != 0:
                return _failed_solution(
                    request,
                    self.solver_name,
                    _solver_version(resolved_executable),
                    _summarize_solver_failure(completed.stderr, completed.stdout),
                )

            solution = _parse_solve_field_outputs(
                workdir,
                request,
                solver_version=_solver_version(resolved_executable),
                command_summary=_command_summary(command, frame_path=frame_path),
            )
            if self.keep_workdir:
                _copy_kept_workdir(workdir)
            return solution


class AstapPlateSolverProvider:
    """Subprocess adapter for a local ASTAP or astap_cli executable."""

    solver_name = "ASTAP"

    def __init__(
        self,
        executable: str = "astap",
        work_parent: str | Path | None = None,
        keep_workdir: bool = False,
        database_path: str | Path | None = None,
        database_name: str | None = None,
        downsample: int = 0,
        max_stars: int = 500,
    ) -> None:
        self.executable = executable
        self.work_parent = Path(work_parent) if work_parent else None
        self.keep_workdir = keep_workdir
        self.database_path = Path(database_path) if database_path else None
        self.database_name = database_name
        self.downsample = downsample
        self.max_stars = max_stars

    def solve(self, request: PlateSolverRequest) -> PlateSolution:
        frame_path = _local_frame_path(request.camera_frame.source_handle)
        if not frame_path.exists():
            return _failed_solution(
                request,
                self.solver_name,
                "unknown",
                "camera frame path does not exist",
            )

        resolved_executable = _resolve_executable(
            self.executable,
            allowed_command_names=_ALLOWED_ASTAP_COMMANDS,
        )
        if resolved_executable is None:
            return _failed_solution(
                request,
                self.solver_name,
                "unknown",
                "ASTAP executable not found",
            )

        with tempfile.TemporaryDirectory(
            prefix="astro-true-north-astap-",
            dir=self.work_parent,
        ) as temp_dir:
            workdir = Path(temp_dir)
            output_base = workdir / "astap"
            command = _astap_command(
                resolved_executable,
                frame_path,
                output_base,
                request,
                database_path=self.database_path,
                database_name=self.database_name,
                downsample=self.downsample,
                max_stars=self.max_stars,
            )
            try:
                # argv-only subprocess call after resolving an allowlisted command
                # name or an explicit executable file path; no shell is involved.
                completed = subprocess.run(  # nosemgrep
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=request.timeout_s,
                )
            except FileNotFoundError:
                return _failed_solution(
                    request,
                    self.solver_name,
                    "unknown",
                    "ASTAP executable not found",
                )
            except subprocess.TimeoutExpired:
                return _failed_solution(
                    request,
                    self.solver_name,
                    "unknown",
                    f"ASTAP timed out after {request.timeout_s:g}s",
                )

            solver_version = _astap_version(resolved_executable)
            solution = _parse_astap_outputs(
                output_base,
                request,
                solver_version=solver_version,
                command_summary=_command_summary(command, frame_path=frame_path),
                process_returncode=completed.returncode,
                stderr=completed.stderr,
                stdout=completed.stdout,
            )
            if self.keep_workdir:
                _copy_kept_workdir(workdir)
            return solution


def camera_frame_from_record(record: Mapping[str, object]) -> CameraFrame:
    return CameraFrame(
        id=str(record["id"]),
        timestamp_utc=str(record["timestamp_utc"]),
        source_handle=str(record["source_handle"]),
        privacy_policy=str(record["privacy_policy"]),
        exposure_s=float(record["exposure_s"]),
        gain=record.get("gain"),
        pixel_width=int(record["pixel_width"]),
        pixel_height=int(record["pixel_height"]),
    )


def plate_solution_from_record(record: Mapping[str, object]) -> PlateSolution:
    return PlateSolution(
        ra_deg=float(record["ra_deg"]),
        dec_deg=float(record["dec_deg"]),
        frame=str(record["frame"]),
        obstime=str(record["obstime"]),
        confidence=str(record["confidence"]),
        solver_name=str(record["solver_name"]),
        solver_version=str(record["solver_version"]),
        status=str(record["status"]),
        field_of_view_deg=_optional_float(record.get("field_of_view_deg")),
        pixel_scale_arcsec=_optional_float(record.get("pixel_scale_arcsec")),
        failure_reason=_optional_string(record.get("failure_reason")),
    )


def validate_plate_solution(solution: PlateSolution) -> None:
    if solution.status not in {"solved", "failed"}:
        raise ValueError(f"unsupported plate-solver status: {solution.status}")

    if solution.status == "failed":
        if not solution.failure_reason:
            raise ValueError("failed plate solution requires a failure reason")
        return

    if solution.frame.upper() != "ICRS":
        raise ValueError(f"unsupported plate solution frame: {solution.frame}")
    if not 0.0 <= solution.ra_deg < 360.0:
        raise ValueError(f"plate solution RA outside [0, 360): {solution.ra_deg}")
    if not -90.0 <= solution.dec_deg <= 90.0:
        raise ValueError(f"plate solution Dec outside [-90, 90]: {solution.dec_deg}")
    if not all(isfinite(value) for value in (solution.ra_deg, solution.dec_deg)):
        raise ValueError("plate solution coordinates must be finite")
    if solution.failure_reason is not None:
        raise ValueError("solved plate solution must not include a failure reason")
    if solution.field_of_view_deg is not None and solution.field_of_view_deg <= 0.0:
        raise ValueError("plate solution field_of_view_deg must be positive")
    if solution.pixel_scale_arcsec is not None and solution.pixel_scale_arcsec <= 0.0:
        raise ValueError("plate solution pixel_scale_arcsec must be positive")


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _local_frame_path(source_handle: str) -> Path:
    if source_handle.startswith("file://"):
        return Path(source_handle.removeprefix("file://"))
    if "://" in source_handle:
        raise ValueError(f"unsupported non-local frame handle: {source_handle}")
    return Path(source_handle)


def _resolve_executable(
    executable: str,
    *,
    allowed_command_names: frozenset[str],
) -> str | None:
    path = Path(executable)
    has_path_component = path.parent != Path(".")
    if path.name not in allowed_command_names and not has_path_component:
        return None
    if has_path_component:
        return str(path) if path.is_file() and _is_executable(path) else None
    return shutil.which(executable)


def _is_executable(path: Path) -> bool:
    return path.exists() and path.is_file() and os.access(path, os.X_OK)


def _solve_field_command(
    executable: str,
    frame_path: Path,
    workdir: Path,
    request: PlateSolverRequest,
) -> list[str]:
    command = [
        executable,
        "--overwrite",
        "--no-plots",
        "--dir",
        str(workdir),
        "--basename",
        "solve",
        "--cpulimit",
        str(max(1, int(request.timeout_s))),
    ]
    if request.field_of_view_hint_deg is not None:
        lower, upper = _hint_bounds(request.field_of_view_hint_deg)
        command.extend(
            [
                "--scale-units",
                "degwidth",
                "--scale-low",
                f"{lower:.6f}",
                "--scale-high",
                f"{upper:.6f}",
            ]
        )
    elif request.pixel_scale_hint_arcsec is not None:
        lower, upper = _hint_bounds(request.pixel_scale_hint_arcsec)
        command.extend(
            [
                "--scale-units",
                "arcsecperpix",
                "--scale-low",
                f"{lower:.6f}",
                "--scale-high",
                f"{upper:.6f}",
            ]
        )

    if (
        request.approximate_ra_deg is not None
        and request.approximate_dec_deg is not None
    ):
        radius = request.search_radius_hint_deg or 15.0
        command.extend(
            [
                "--ra",
                f"{request.approximate_ra_deg:.8f}",
                "--dec",
                f"{request.approximate_dec_deg:.8f}",
                "--radius",
                f"{radius:.6f}",
            ]
        )

    command.append(str(frame_path))
    return command


def _hint_bounds(value: float) -> tuple[float, float]:
    if value <= 0.0:
        raise ValueError("plate solver scale hints must be positive")
    return value * 0.8, value * 1.2


def _parse_solve_field_outputs(
    workdir: Path,
    request: PlateSolverRequest,
    *,
    solver_version: str,
    command_summary: str,
) -> PlateSolution:
    solved_marker = workdir / "solve.solved"
    wcs_path = workdir / "solve.wcs"
    if not solved_marker.exists() or not wcs_path.exists():
        return _failed_solution(
            request,
            AstrometryNetSolveFieldProvider.solver_name,
            solver_version,
            "solve-field finished without a solved marker and WCS output",
        )

    header = fits.getheader(wcs_path)
    solution = PlateSolution(
        ra_deg=float(header["CRVAL1"]),
        dec_deg=float(header["CRVAL2"]),
        frame=str(header.get("RADESYS", "ICRS")),
        obstime=request.camera_frame.timestamp_utc,
        confidence="solved",
        solver_name=AstrometryNetSolveFieldProvider.solver_name,
        solver_version=solver_version,
        field_of_view_deg=_field_of_view_from_header(header),
        pixel_scale_arcsec=_pixel_scale_from_header(header),
        index_source=_optional_string(header.get("ANINDEX")),
        command_summary=command_summary,
    )
    validate_plate_solution(solution)
    return solution


def _astap_command(
    executable: str,
    frame_path: Path,
    output_base: Path,
    request: PlateSolverRequest,
    *,
    database_path: Path | None,
    database_name: str | None,
    downsample: int,
    max_stars: int,
) -> list[str]:
    command = [
        executable,
        "-f",
        str(frame_path),
        "-r",
        f"{request.search_radius_hint_deg or 30.0:.6f}",
        "-z",
        str(downsample),
        "-s",
        str(max_stars),
        "-wcs",
        "-o",
        str(output_base),
    ]
    fov_height = _astap_fov_height_hint_deg(request)
    if fov_height is not None:
        command.extend(["-fov", f"{fov_height:.6f}"])
    if (
        request.approximate_ra_deg is not None
        and request.approximate_dec_deg is not None
    ):
        command.extend(
            [
                "-ra",
                f"{request.approximate_ra_deg / 15.0:.8f}",
                "-spd",
                f"{request.approximate_dec_deg + 90.0:.8f}",
            ]
        )
    if database_path is not None:
        command.extend(["-d", str(database_path)])
    if database_name is not None:
        command.extend(["-D", database_name])
    return command


def _astap_fov_height_hint_deg(request: PlateSolverRequest) -> float | None:
    if request.pixel_scale_hint_arcsec is not None:
        if request.pixel_scale_hint_arcsec <= 0.0:
            raise ValueError("plate solver scale hints must be positive")
        return request.pixel_scale_hint_arcsec * request.camera_frame.pixel_height / 3600.0
    if request.field_of_view_hint_deg is None:
        return None
    if request.field_of_view_hint_deg <= 0.0:
        raise ValueError("plate solver scale hints must be positive")
    longer_edge = max(request.camera_frame.pixel_width, request.camera_frame.pixel_height)
    return request.field_of_view_hint_deg * request.camera_frame.pixel_height / longer_edge


def _parse_astap_outputs(
    output_base: Path,
    request: PlateSolverRequest,
    *,
    solver_version: str,
    command_summary: str,
    process_returncode: int,
    stderr: str,
    stdout: str,
) -> PlateSolution:
    ini_values = _read_astap_ini(output_base.with_suffix(".ini"))
    if process_returncode != 0:
        return _failed_solution(
            request,
            AstapPlateSolverProvider.solver_name,
            solver_version,
            _astap_failure_reason(ini_values, stderr, stdout),
        )
    if ini_values.get("PLTSOLVD", "").upper() == "F":
        return _failed_solution(
            request,
            AstapPlateSolverProvider.solver_name,
            solver_version,
            ini_values.get("ERROR") or "ASTAP failed to solve image",
        )

    wcs_path = output_base.with_suffix(".wcs")
    if wcs_path.exists():
        header = fits.getheader(wcs_path)
    elif ini_values.get("PLTSOLVD", "").upper() == "T":
        header = fits.Header()
        for key in ("CRVAL1", "CRVAL2", "CD1_1", "CD1_2", "IMAGEW", "IMAGEH"):
            if key in ini_values:
                header[key] = _astap_ini_number(ini_values[key])
        header["RADESYS"] = ini_values.get("RADESYS", "ICRS")
    else:
        return _failed_solution(
            request,
            AstapPlateSolverProvider.solver_name,
            solver_version,
            "ASTAP finished without solved WCS output",
        )

    solution = PlateSolution(
        ra_deg=float(header["CRVAL1"]),
        dec_deg=float(header["CRVAL2"]),
        frame=str(header.get("RADESYS", "ICRS")),
        obstime=request.camera_frame.timestamp_utc,
        confidence="solved",
        solver_name=AstapPlateSolverProvider.solver_name,
        solver_version=solver_version,
        field_of_view_deg=_field_of_view_from_header(header),
        pixel_scale_arcsec=_pixel_scale_from_header(header),
        index_source=ini_values.get("DATABASE") or ini_values.get("INDEX"),
        command_summary=command_summary,
    )
    validate_plate_solution(solution)
    return solution


def _read_astap_ini(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("//", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _astap_ini_number(value: str) -> float:
    return float(value.strip().split()[0])


def _astap_failure_reason(
    ini_values: Mapping[str, str],
    stderr: str,
    stdout: str,
) -> str:
    if ini_values.get("ERROR"):
        return ini_values["ERROR"]
    detail = (stderr or stdout).strip().splitlines()
    return detail[-1] if detail else "ASTAP failed"


def _field_of_view_from_header(header: fits.Header) -> float | None:
    width = header.get("IMAGEW")
    height = header.get("IMAGEH")
    pixel_scale = _pixel_scale_from_header(header)
    if width is None or height is None or pixel_scale is None:
        return None
    return max(float(width), float(height)) * pixel_scale / 3600.0


def _pixel_scale_from_header(header: fits.Header) -> float | None:
    if "PIXSCALE" in header:
        return float(header["PIXSCALE"])
    cd11 = header.get("CD1_1")
    cd12 = header.get("CD1_2", 0.0)
    if cd11 is None:
        return None
    return ((float(cd11) ** 2 + float(cd12) ** 2) ** 0.5) * 3600.0


def _failed_solution(
    request: PlateSolverRequest,
    solver_name: str,
    solver_version: str,
    reason: str,
) -> PlateSolution:
    return PlateSolution(
        ra_deg=float("nan"),
        dec_deg=float("nan"),
        frame="",
        obstime=request.camera_frame.timestamp_utc,
        confidence="none",
        solver_name=solver_name,
        solver_version=solver_version,
        status="failed",
        failure_reason=reason,
    )


def _solver_version(executable: str) -> str:
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    version = (completed.stdout or completed.stderr).strip()
    return version or "unknown"


def _astap_version(executable: str) -> str:
    try:
        completed = subprocess.run(
            [executable, "-h"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    detail = (completed.stdout or completed.stderr).strip().splitlines()
    return detail[0].strip() if detail else "unknown"


def _summarize_solver_failure(stderr: str, stdout: str) -> str:
    detail = (stderr or stdout).strip().splitlines()
    return detail[-1] if detail else "solve-field failed"


def _command_summary(command: list[str], *, frame_path: Path | None = None) -> str:
    redacted = list(command)
    if frame_path is not None:
        redacted = [
            "<frame>" if argument == str(frame_path) else argument
            for argument in redacted
        ]
    elif redacted:
        redacted[-1] = "<frame>"
    return " ".join(redacted)


def _copy_kept_workdir(workdir: Path) -> None:
    target = workdir.with_name(f"{workdir.name}-kept")
    shutil.copytree(workdir, target, dirs_exist_ok=True)

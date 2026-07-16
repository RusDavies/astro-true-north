"""Magnetic model provider boundary for true-north correction."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class MagneticModelRequest:
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    timestamp_utc: str
    elevation_reference: str = "WGS84_ELLIPSOID"


@dataclass(frozen=True)
class MagneticFieldVector:
    north_nt: float
    east_nt: float
    down_nt: float


@dataclass(frozen=True)
class MagneticAnnualChange:
    declination_deg_per_year: float | None = None
    inclination_deg_per_year: float | None = None
    total_intensity_nt_per_year: float | None = None


@dataclass(frozen=True)
class MagneticUncertainty:
    declination_deg_1sigma: float | None = None
    inclination_deg_1sigma: float | None = None
    total_intensity_nt_1sigma: float | None = None


@dataclass(frozen=True)
class MagneticModelResult:
    model_name: str
    model_version: str
    valid_from: str
    valid_until: str
    source: str
    declination_deg: float
    inclination_deg: float
    field_vector_nt: MagneticFieldVector
    annual_change: MagneticAnnualChange
    uncertainty: MagneticUncertainty


@dataclass(frozen=True)
class ModelEpochStatus:
    model_name: str
    valid_until: str
    checked_on: str
    days_until_expiry: int
    state: str
    message: str


class MagneticModelProvider(Protocol):
    """Provider interface for offline magnetic model adapters."""

    model_name: str

    def calculate(self, request: MagneticModelRequest) -> MagneticModelResult:
        """Return magnetic correction data for an observing site and instant."""


class GeographicLibMagneticFieldProvider:
    """Subprocess adapter for GeographicLib's MagneticField executable."""

    model_name = "wmm2025"

    def __init__(
        self,
        executable: str = "MagneticField",
        model_name: str = "wmm2025",
        model_directory: str | Path | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.executable = executable
        self.model_name = model_name
        self.model_directory = Path(model_directory) if model_directory else None
        self.timeout_s = timeout_s

    def calculate(self, request: MagneticModelRequest) -> MagneticModelResult:
        if request.elevation_reference != "WGS84_ELLIPSOID":
            raise ValueError(
                "GeographicLib MagneticField expects height above the WGS84 ellipsoid"
            )

        command = [self.executable, "-n", self.model_name, "-r", "-p", "8"]
        if self.model_directory is not None:
            command.extend(["-d", str(self.model_directory)])

        input_line = (
            f"{_date_only(request.timestamp_utc)} "
            f"{request.latitude_deg:.10f} "
            f"{request.longitude_deg:.10f} "
            f"{request.elevation_m:.3f}\n"
        )
        try:
            completed = subprocess.run(
                command,
                input=input_line,
                capture_output=True,
                check=False,
                text=True,
                timeout=self.timeout_s,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"MagneticField executable not found: {self.executable}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"MagneticField timed out after {self.timeout_s:g}s"
            ) from exc

        if completed.returncode != 0 or completed.stdout.lstrip().startswith("ERROR:"):
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"MagneticField failed: {detail}")

        return _parse_magneticfield_output(
            completed.stdout,
            model_name=self.model_name.upper(),
            model_version=self.model_name,
            source=self.executable,
        )


def _parse_magneticfield_output(
    output: str,
    *,
    model_name: str,
    model_version: str,
    source: str,
) -> MagneticModelResult:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError("MagneticField output did not include field and rate lines")

    field_values = _parse_float_line(lines[0], expected=7)
    rate_values = _parse_float_line(lines[1], expected=7)
    return MagneticModelResult(
        model_name=model_name,
        model_version=model_version,
        valid_from="2025-01-01" if model_version.lower() == "wmm2025" else "",
        valid_until="2029-12-31" if model_version.lower() == "wmm2025" else "",
        source=source,
        declination_deg=field_values[0],
        inclination_deg=field_values[1],
        field_vector_nt=MagneticFieldVector(
            north_nt=field_values[3],
            east_nt=field_values[4],
            down_nt=field_values[5],
        ),
        annual_change=MagneticAnnualChange(
            declination_deg_per_year=rate_values[0],
            inclination_deg_per_year=rate_values[1],
            total_intensity_nt_per_year=rate_values[6],
        ),
        uncertainty=MagneticUncertainty(),
    )


def check_model_epoch(
    result: MagneticModelResult,
    *,
    checked_on: str,
    warning_days: int = 365,
) -> ModelEpochStatus:
    """Return update status for a magnetic model validity window."""

    checked_date = _parse_date(_date_only(checked_on))
    expiry_date = _parse_date(result.valid_until)
    days_until_expiry = (expiry_date.date() - checked_date.date()).days
    if days_until_expiry < 0:
        state = "expired"
        message = (
            f"{result.model_name} expired on {result.valid_until}; update model data "
            "before using magnetic correction."
        )
    elif days_until_expiry <= warning_days:
        state = "update_due"
        message = (
            f"{result.model_name} expires on {result.valid_until}; schedule a model "
            "data update before field use."
        )
    else:
        state = "current"
        message = f"{result.model_name} is current through {result.valid_until}."

    return ModelEpochStatus(
        model_name=result.model_name,
        valid_until=result.valid_until,
        checked_on=checked_date.date().isoformat(),
        days_until_expiry=days_until_expiry,
        state=state,
        message=message,
    )


def _parse_float_line(line: str, *, expected: int) -> list[float]:
    values = [float(part) for part in line.split()]
    if len(values) != expected:
        raise ValueError(f"expected {expected} MagneticField values, got {len(values)}")
    return values


def _date_only(timestamp_utc: str) -> str:
    timestamp = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    return timestamp.astimezone(timezone.utc).date().isoformat()


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)

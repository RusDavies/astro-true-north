"""First rough-vs-solved telescope alignment calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, ICRS, SkyCoord
from astropy.time import Time
from astropy.utils import iers

from astro_true_north.plate_solving import PlateSolution


iers.conf.auto_download = False


def normalize_360(angle_deg: float) -> float:
    """Normalize an angle into the [0, 360) degree range."""

    return angle_deg % 360.0


def signed_angle_delta(target_deg: float, reference_deg: float) -> float:
    """Return the shortest signed delta from reference to target in degrees."""

    return (target_deg - reference_deg + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class ObservingSite:
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    timestamp_utc: str
    location_precision: str = "unknown"
    privacy_policy: str = "do-not-log-precise-location"


@dataclass(frozen=True)
class CompassSample:
    magnetic_azimuth_deg: float
    calibration_state: str
    uncertainty_deg: float
    sensor_mount_offset_deg: float = 0.0
    calibration_offset_deg: float = 0.0


@dataclass(frozen=True)
class InclinometerSample:
    altitude_deg: float
    calibration_state: str
    uncertainty_deg: float
    sensor_mount_offset_deg: float = 0.0
    calibration_offset_deg: float = 0.0


@dataclass(frozen=True)
class MagneticCorrection:
    declination_deg: float
    model_name: str
    model_version: str
    valid_from: str
    valid_until: str
    uncertainty_deg: float | None = None


@dataclass(frozen=True)
class AlignmentResult:
    rough_true_azimuth_deg: float
    rough_altitude_deg: float
    estimated_ra_deg: float
    estimated_dec_deg: float
    solved_ra_deg: float
    solved_dec_deg: float
    solved_azimuth_deg: float
    solved_altitude_deg: float
    sky_separation_deg: float
    sky_position_angle_deg: float
    local_azimuth_delta_deg: float
    local_altitude_delta_deg: float
    status: str
    confidence: str
    uncertainty_summary: dict[str, Any]


def corrected_true_azimuth(
    compass: CompassSample,
    magnetic_correction: MagneticCorrection,
) -> float:
    return normalize_360(
        compass.magnetic_azimuth_deg
        + compass.sensor_mount_offset_deg
        + compass.calibration_offset_deg
        + magnetic_correction.declination_deg
    )


def corrected_altitude(inclinometer: InclinometerSample) -> float:
    altitude = (
        inclinometer.altitude_deg
        + inclinometer.sensor_mount_offset_deg
        + inclinometer.calibration_offset_deg
    )
    if not -90.0 <= altitude <= 90.0:
        raise ValueError(f"rough altitude outside physical range: {altitude}")
    return altitude


def calculate_alignment(
    site: ObservingSite,
    compass: CompassSample,
    inclinometer: InclinometerSample,
    magnetic_correction: MagneticCorrection,
    plate_solution: PlateSolution,
) -> AlignmentResult:
    """Compare rough sensor pointing with an authoritative plate solution."""

    _validate_model_date(site.timestamp_utc, magnetic_correction)
    if plate_solution.frame.upper() != "ICRS":
        raise ValueError(f"unsupported plate solution frame: {plate_solution.frame}")

    rough_azimuth = corrected_true_azimuth(compass, magnetic_correction)
    rough_altitude = corrected_altitude(inclinometer)
    location = EarthLocation(
        lat=site.latitude_deg * u.deg,
        lon=site.longitude_deg * u.deg,
        height=site.elevation_m * u.m,
    )
    observation_time = Time(site.timestamp_utc)
    altaz_frame = AltAz(
        obstime=observation_time,
        location=location,
        pressure=0 * u.hPa,
    )

    estimated_altaz = SkyCoord(
        az=rough_azimuth * u.deg,
        alt=rough_altitude * u.deg,
        frame=altaz_frame,
    )
    estimated_icrs = estimated_altaz.transform_to(ICRS())

    solved_icrs = SkyCoord(
        ra=plate_solution.ra_deg * u.deg,
        dec=plate_solution.dec_deg * u.deg,
        frame=ICRS(),
    )
    solved_altaz = solved_icrs.transform_to(altaz_frame)

    sky_separation = estimated_icrs.separation(solved_icrs).deg
    sky_position_angle = estimated_icrs.position_angle(solved_icrs).deg
    solved_azimuth = normalize_360(solved_altaz.az.deg)
    solved_altitude = solved_altaz.alt.deg
    local_azimuth_delta = signed_angle_delta(solved_azimuth, rough_azimuth)
    local_altitude_delta = solved_altitude - rough_altitude

    result_values = (
        estimated_icrs.ra.deg,
        estimated_icrs.dec.deg,
        solved_azimuth,
        solved_altitude,
        sky_separation,
        sky_position_angle,
        local_azimuth_delta,
        local_altitude_delta,
    )
    if not all(isfinite(value) for value in result_values):
        raise ValueError("alignment calculation produced a non-finite result")

    return AlignmentResult(
        rough_true_azimuth_deg=rough_azimuth,
        rough_altitude_deg=rough_altitude,
        estimated_ra_deg=estimated_icrs.ra.deg,
        estimated_dec_deg=estimated_icrs.dec.deg,
        solved_ra_deg=solved_icrs.ra.deg,
        solved_dec_deg=solved_icrs.dec.deg,
        solved_azimuth_deg=solved_azimuth,
        solved_altitude_deg=solved_altitude,
        sky_separation_deg=sky_separation,
        sky_position_angle_deg=sky_position_angle,
        local_azimuth_delta_deg=local_azimuth_delta,
        local_altitude_delta_deg=local_altitude_delta,
        status="solved",
        confidence=plate_solution.confidence,
        uncertainty_summary={
            "compass_uncertainty_deg": compass.uncertainty_deg,
            "inclinometer_uncertainty_deg": inclinometer.uncertainty_deg,
            "magnetic_model_uncertainty_deg": magnetic_correction.uncertainty_deg,
            "refraction_model": "none",
        },
    )


def _validate_model_date(
    timestamp_utc: str,
    magnetic_correction: MagneticCorrection,
) -> None:
    timestamp = _parse_utc(timestamp_utc)
    valid_from = _parse_date(magnetic_correction.valid_from)
    valid_until = _parse_date(magnetic_correction.valid_until)
    if not valid_from <= timestamp <= valid_until:
        raise ValueError(
            f"{magnetic_correction.model_name} correction is invalid for "
            f"{timestamp_utc}; valid range is "
            f"{magnetic_correction.valid_from} to {magnetic_correction.valid_until}"
        )


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)

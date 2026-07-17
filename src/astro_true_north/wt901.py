"""WT901 serial reader utilities."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import math
import struct
import termios
import time
from typing import BinaryIO
import tty


FRAME_LENGTH = 11
FRAME_START = 0x55
ACCELERATION_FRAME = 0x51
GYRO_FRAME = 0x52
ANGLE_FRAME = 0x53
MAGNETIC_FRAME = 0x54


@dataclass(frozen=True)
class Wt901Acceleration:
    """Acceleration in g."""

    x_g: float
    y_g: float
    z_g: float


@dataclass(frozen=True)
class Wt901Gyro:
    """Angular velocity in degrees per second."""

    x_deg_s: float
    y_deg_s: float
    z_deg_s: float


@dataclass(frozen=True)
class Wt901Angle:
    """Roll, pitch, and yaw in degrees."""

    roll_deg: float
    pitch_deg: float
    yaw_deg: float


@dataclass(frozen=True)
class Wt901MagneticField:
    """Raw WT901 magnetometer counts."""

    x: int
    y: int
    z: int

    @property
    def magnitude(self) -> float:
        return math.sqrt((self.x * self.x) + (self.y * self.y) + (self.z * self.z))


@dataclass(frozen=True)
class Wt901Sample:
    """Decoded WT901 sample values available at one point in the stream."""

    timestamp_monotonic: float
    acceleration: Wt901Acceleration | None = None
    gyro: Wt901Gyro | None = None
    angle: Wt901Angle | None = None
    magnetic_field: Wt901MagneticField | None = None


@dataclass(frozen=True)
class Wt901CaptureSummary:
    """Summary of a short WT901 capture."""

    samples_seen: int
    angle_samples: int
    magnetic_samples: int
    first_angle: Wt901Angle | None
    last_angle: Wt901Angle | None
    min_yaw_deg: float | None
    max_yaw_deg: float | None
    min_pitch_deg: float | None
    max_pitch_deg: float | None
    min_roll_deg: float | None
    max_roll_deg: float | None
    min_magnetic_magnitude: float | None
    max_magnetic_magnitude: float | None

    def report_lines(self) -> list[str]:
        lines = [
            "WT901 sample summary",
            f"Samples: {self.samples_seen}",
            f"Angle frames: {self.angle_samples}",
            f"Magnetometer frames: {self.magnetic_samples}",
        ]
        if self.first_angle and self.last_angle:
            lines.extend(
                [
                    (
                        "Start angle: "
                        f"roll={self.first_angle.roll_deg:.2f} deg, "
                        f"pitch={self.first_angle.pitch_deg:.2f} deg, "
                        f"yaw={self.first_angle.yaw_deg:.2f} deg"
                    ),
                    (
                        "End angle: "
                        f"roll={self.last_angle.roll_deg:.2f} deg, "
                        f"pitch={self.last_angle.pitch_deg:.2f} deg, "
                        f"yaw={self.last_angle.yaw_deg:.2f} deg"
                    ),
                    (
                        "Angle ranges: "
                        f"roll {format_range(self.min_roll_deg, self.max_roll_deg)} deg, "
                        f"pitch {format_range(self.min_pitch_deg, self.max_pitch_deg)} deg, "
                        f"yaw {format_range(self.min_yaw_deg, self.max_yaw_deg)} deg"
                    ),
                ]
            )
        if self.min_magnetic_magnitude is not None and self.max_magnetic_magnitude is not None:
            lines.append(
                "Magnetometer magnitude range: "
                f"{self.min_magnetic_magnitude:.0f} to {self.max_magnetic_magnitude:.0f} raw counts"
            )
        if not self.first_angle:
            lines.append("No angle frames decoded. Check baud rate and RX/TX wiring.")
        return lines


@dataclass(frozen=True)
class Wt901CalibrationReport:
    """First-pass WT901 stability and error-budget estimate."""

    samples_seen: int
    angle_samples: int
    magnetic_samples: int
    roll_stddev_deg: float | None
    pitch_stddev_deg: float | None
    yaw_stddev_deg: float | None
    roll_span_deg: float | None
    pitch_span_deg: float | None
    yaw_span_deg: float | None
    magnetic_variation_percent: float | None
    recommended_compass_uncertainty_deg: float | None
    recommended_inclinometer_uncertainty_deg: float | None
    status: str

    def report_lines(self) -> list[str]:
        lines = [
            "WT901 calibration/error-budget summary",
            f"Status: {self.status}",
            f"Samples: {self.samples_seen}",
            f"Angle frames: {self.angle_samples}",
            f"Magnetometer frames: {self.magnetic_samples}",
        ]
        if self.roll_stddev_deg is not None:
            lines.extend(
                [
                    (
                        "Stationary jitter: "
                        f"roll {self.roll_stddev_deg:.3f} deg, "
                        f"pitch {self.pitch_stddev_deg:.3f} deg, "
                        f"yaw {self.yaw_stddev_deg:.3f} deg"
                    ),
                    (
                        "Observed spans: "
                        f"roll {self.roll_span_deg:.2f} deg, "
                        f"pitch {self.pitch_span_deg:.2f} deg, "
                        f"yaw {self.yaw_span_deg:.2f} deg"
                    ),
                ]
            )
        if self.magnetic_variation_percent is not None:
            lines.append(
                "Magnetometer magnitude variation: "
                f"{self.magnetic_variation_percent:.1f}%"
            )
        if self.recommended_compass_uncertainty_deg is not None:
            lines.append(
                "Recommended compass uncertainty: "
                f"{self.recommended_compass_uncertainty_deg:.1f} deg"
            )
        if self.recommended_inclinometer_uncertainty_deg is not None:
            lines.append(
                "Recommended inclinometer uncertainty: "
                f"{self.recommended_inclinometer_uncertainty_deg:.1f} deg"
            )
        return lines


@dataclass(frozen=True)
class Wt901MagnetometerYawPoint:
    """One known relative-yaw point with a corresponding raw magnetic vector."""

    relative_yaw_deg: float
    magnetic_field: Wt901MagneticField


@dataclass(frozen=True)
class Wt901MagnetometerYawFit:
    """Linear relative-yaw fit from raw 3-axis magnetometer vectors."""

    status: str
    samples: int
    relative_yaw_start_deg: float | None
    relative_yaw_end_deg: float | None
    coefficients: tuple[float, float, float]
    intercept: float
    rmse_deg: float | None
    mae_deg: float | None
    max_error_deg: float | None
    r_squared: float | None

    def estimate_relative_yaw_deg(self, magnetic_field: Wt901MagneticField) -> float:
        return (
            self.intercept
            + self.coefficients[0] * magnetic_field.x
            + self.coefficients[1] * magnetic_field.y
            + self.coefficients[2] * magnetic_field.z
        )

    def report_lines(self) -> list[str]:
        lines = [
            "WT901 magnetometer relative-yaw fit",
            f"Status: {self.status}",
            f"Samples: {self.samples}",
        ]
        if self.relative_yaw_start_deg is not None and self.relative_yaw_end_deg is not None:
            lines.append(
                "Relative yaw range: "
                f"{self.relative_yaw_start_deg:.3f} to {self.relative_yaw_end_deg:.3f} deg"
            )
        if self.rmse_deg is not None:
            lines.extend(
                [
                    f"RMSE: {self.rmse_deg:.3f} deg",
                    f"MAE: {self.mae_deg:.3f} deg",
                    f"Max error: {self.max_error_deg:.3f} deg",
                    f"R^2: {self.r_squared:.4f}" if self.r_squared is not None else "R^2: n/a",
                    (
                        "Fit: relative_yaw_deg = "
                        f"{self.intercept:.9f} "
                        f"+ {self.coefficients[0]:.9f}*mag_x "
                        f"+ {self.coefficients[1]:.9f}*mag_y "
                        f"+ {self.coefficients[2]:.9f}*mag_z"
                    ),
                ]
            )
        else:
            lines.append("Insufficient magnetometer variation for a fit.")
        return lines


def format_range(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "n/a"
    return f"{low:.2f} to {high:.2f}"


def configure_serial_port(device: BinaryIO, baud: int) -> None:
    """Configure a POSIX serial device for raw 8N1 reads."""

    baud_attr = getattr(termios, f"B{baud}", None)
    if baud_attr is None:
        raise ValueError(f"unsupported baud rate: {baud}")

    fd = device.fileno()
    attrs = termios.tcgetattr(fd)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    attrs[4] = baud_attr
    attrs[5] = baud_attr
    attrs[2] |= termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[2] &= ~(termios.PARENB | termios.CSTOPB)
    attrs[3] &= ~termios.ECHO
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def iter_wt901_samples(device: BinaryIO) -> Iterator[Wt901Sample]:
    """Yield decoded angle and magnetometer samples from a WT901 byte stream."""

    buffer = bytearray()
    while True:
        chunk = device.read(64)
        if not chunk:
            return
        buffer.extend(chunk)
        while len(buffer) >= FRAME_LENGTH:
            if buffer[0] != FRAME_START:
                del buffer[0]
                continue
            frame = bytes(buffer[:FRAME_LENGTH])
            del buffer[:FRAME_LENGTH]
            sample = decode_wt901_frame(frame)
            if sample is not None:
                yield sample


def decode_wt901_frame(frame: bytes, now: float | None = None) -> Wt901Sample | None:
    """Decode one 11-byte WT901 frame, ignoring bad checksums or unknown frames."""

    if len(frame) != FRAME_LENGTH or frame[0] != FRAME_START:
        return None
    if (sum(frame[:10]) & 0xFF) != frame[10]:
        return None

    kind = frame[1]
    values = struct.unpack("<hhhh", frame[2:10])
    timestamp = time.monotonic() if now is None else now
    if kind == ACCELERATION_FRAME:
        return Wt901Sample(
            timestamp_monotonic=timestamp,
            acceleration=Wt901Acceleration(
                x_g=values[0] / 32768 * 16,
                y_g=values[1] / 32768 * 16,
                z_g=values[2] / 32768 * 16,
            ),
        )
    if kind == GYRO_FRAME:
        return Wt901Sample(
            timestamp_monotonic=timestamp,
            gyro=Wt901Gyro(
                x_deg_s=values[0] / 32768 * 2000,
                y_deg_s=values[1] / 32768 * 2000,
                z_deg_s=values[2] / 32768 * 2000,
            ),
        )
    if kind == ANGLE_FRAME:
        return Wt901Sample(
            timestamp_monotonic=timestamp,
            angle=Wt901Angle(
                roll_deg=values[0] / 32768 * 180,
                pitch_deg=values[1] / 32768 * 180,
                yaw_deg=values[2] / 32768 * 180,
            ),
        )
    if kind == MAGNETIC_FRAME:
        return Wt901Sample(
            timestamp_monotonic=timestamp,
            magnetic_field=Wt901MagneticField(values[0], values[1], values[2]),
        )
    return None


def format_wt901_stream_header() -> str:
    return (
        "elapsed_s,channel,accel_x_g,accel_y_g,accel_z_g,"
        "gyro_x_deg_s,gyro_y_deg_s,gyro_z_deg_s,"
        "roll_deg,pitch_deg,yaw_deg,mag_x,mag_y,mag_z,mag_magnitude"
    )


def format_wt901_stream_sample(
    sample: Wt901Sample,
    *,
    start_time_monotonic: float,
) -> str:
    elapsed = sample.timestamp_monotonic - start_time_monotonic
    fields = [""] * 13
    channel = "unknown"
    if sample.acceleration is not None:
        channel = "accel"
        fields[0:3] = [
            f"{sample.acceleration.x_g:.6f}",
            f"{sample.acceleration.y_g:.6f}",
            f"{sample.acceleration.z_g:.6f}",
        ]
    elif sample.gyro is not None:
        channel = "gyro"
        fields[3:6] = [
            f"{sample.gyro.x_deg_s:.6f}",
            f"{sample.gyro.y_deg_s:.6f}",
            f"{sample.gyro.z_deg_s:.6f}",
        ]
    elif sample.angle is not None:
        channel = "angle"
        fields[6:9] = [
            f"{sample.angle.roll_deg:.6f}",
            f"{sample.angle.pitch_deg:.6f}",
            f"{sample.angle.yaw_deg:.6f}",
        ]
    elif sample.magnetic_field is not None:
        channel = "mag"
        fields[9:13] = [
            str(sample.magnetic_field.x),
            str(sample.magnetic_field.y),
            str(sample.magnetic_field.z),
            f"{sample.magnetic_field.magnitude:.6f}",
        ]
    return ",".join([f"{elapsed:.6f}", channel, *fields])


def stream_wt901_channel_lines(
    port: str,
    *,
    baud: int = 9600,
    duration_seconds: float = 10.0,
) -> Iterator[str]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    with open(port, "rb", buffering=0) as device:
        configure_serial_port(device, baud)
        deadline = time.monotonic() + duration_seconds
        start = time.monotonic()
        iterator = iter_wt901_samples(device)
        while time.monotonic() < deadline:
            for sample in iterator:
                yield format_wt901_stream_sample(
                    sample,
                    start_time_monotonic=start,
                )
                if time.monotonic() >= deadline:
                    break
            else:
                break


def capture_wt901(
    port: str,
    *,
    baud: int = 9600,
    duration_seconds: float = 10.0,
    prompt: str | None = None,
) -> Wt901CaptureSummary:
    """Read a WT901 serial stream for a short period and summarize movement."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    samples = read_wt901_samples(
        port,
        baud=baud,
        duration_seconds=duration_seconds,
        prompt=prompt,
    )
    return summarize_wt901_samples(samples)


def capture_wt901_calibration(
    port: str,
    *,
    baud: int = 9600,
    duration_seconds: float = 10.0,
    prompt: str | None = None,
) -> Wt901CalibrationReport:
    """Capture a stationary WT901 sample and estimate conservative uncertainties."""

    samples = read_wt901_samples(
        port,
        baud=baud,
        duration_seconds=duration_seconds,
        prompt=prompt,
    )
    return estimate_wt901_error_budget(samples)


def read_wt901_samples(
    port: str,
    *,
    baud: int = 9600,
    duration_seconds: float = 10.0,
    prompt: str | None = None,
) -> list[Wt901Sample]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    with open(port, "rb", buffering=0) as device:
        configure_serial_port(device, baud)
        if prompt:
            print(prompt, flush=True)
        deadline = time.monotonic() + duration_seconds
        samples: list[Wt901Sample] = []
        iterator = iter_wt901_samples(device)
        while time.monotonic() < deadline:
            for sample in iterator:
                samples.append(sample)
                if time.monotonic() >= deadline:
                    break
            else:
                break
    return samples


def summarize_wt901_samples(samples: list[Wt901Sample]) -> Wt901CaptureSummary:
    angles = [sample.angle for sample in samples if sample.angle is not None]
    magnetics = [
        sample.magnetic_field for sample in samples if sample.magnetic_field is not None
    ]
    rolls = [angle.roll_deg for angle in angles]
    pitches = [angle.pitch_deg for angle in angles]
    yaws = [angle.yaw_deg for angle in angles]
    magnitudes = [magnetic.magnitude for magnetic in magnetics]
    return Wt901CaptureSummary(
        samples_seen=len(samples),
        angle_samples=len(angles),
        magnetic_samples=len(magnetics),
        first_angle=angles[0] if angles else None,
        last_angle=angles[-1] if angles else None,
        min_yaw_deg=min(yaws) if yaws else None,
        max_yaw_deg=max(yaws) if yaws else None,
        min_pitch_deg=min(pitches) if pitches else None,
        max_pitch_deg=max(pitches) if pitches else None,
        min_roll_deg=min(rolls) if rolls else None,
        max_roll_deg=max(rolls) if rolls else None,
        min_magnetic_magnitude=min(magnitudes) if magnitudes else None,
        max_magnetic_magnitude=max(magnitudes) if magnitudes else None,
    )


def estimate_wt901_error_budget(samples: list[Wt901Sample]) -> Wt901CalibrationReport:
    angles = [sample.angle for sample in samples if sample.angle is not None]
    magnetics = [
        sample.magnetic_field for sample in samples if sample.magnetic_field is not None
    ]
    rolls = [angle.roll_deg for angle in angles]
    pitches = [angle.pitch_deg for angle in angles]
    yaws = [angle.yaw_deg for angle in angles]
    magnitudes = [magnetic.magnitude for magnetic in magnetics]

    roll_stddev = sample_stddev(rolls)
    pitch_stddev = sample_stddev(pitches)
    yaw_stddev = circular_stddev_deg(yaws) if yaws else None
    magnetic_variation = percent_span(magnitudes)

    compass_uncertainty = None
    inclinometer_uncertainty = None
    status = "insufficient-data"
    if roll_stddev is not None and pitch_stddev is not None and yaw_stddev is not None:
        inclinometer_uncertainty = max(0.5, 3 * max(roll_stddev, pitch_stddev))
        magnetic_penalty = (magnetic_variation or 0.0) / 5
        compass_uncertainty = max(2.0, 3 * yaw_stddev, magnetic_penalty)
        status = "stationary-estimate"
        if max(
            span(rolls) or 0.0,
            span(pitches) or 0.0,
            circular_span_deg(yaws) or 0.0,
        ) > 5.0:
            status = "moving-during-capture"

    return Wt901CalibrationReport(
        samples_seen=len(samples),
        angle_samples=len(angles),
        magnetic_samples=len(magnetics),
        roll_stddev_deg=roll_stddev,
        pitch_stddev_deg=pitch_stddev,
        yaw_stddev_deg=yaw_stddev,
        roll_span_deg=span(rolls),
        pitch_span_deg=span(pitches),
        yaw_span_deg=circular_span_deg(yaws),
        magnetic_variation_percent=magnetic_variation,
        recommended_compass_uncertainty_deg=compass_uncertainty,
        recommended_inclinometer_uncertainty_deg=inclinometer_uncertainty,
        status=status,
    )


def sample_stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def span(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values) - min(values)


def percent_span(values: list[float]) -> float | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    if mean == 0:
        return None
    return (span(values) or 0.0) / mean * 100


def fit_magnetometer_relative_yaw(
    points: list[Wt901MagnetometerYawPoint],
) -> Wt901MagnetometerYawFit:
    if len(points) < 4:
        return Wt901MagnetometerYawFit(
            status="insufficient-data",
            samples=len(points),
            relative_yaw_start_deg=None,
            relative_yaw_end_deg=None,
            coefficients=(0.0, 0.0, 0.0),
            intercept=0.0,
            rmse_deg=None,
            mae_deg=None,
            max_error_deg=None,
            r_squared=None,
        )

    targets = [point.relative_yaw_deg for point in points]
    vectors = [
        (
            float(point.magnetic_field.x),
            float(point.magnetic_field.y),
            float(point.magnetic_field.z),
        )
        for point in points
    ]
    target_mean = sum(targets) / len(targets)
    vector_means = tuple(sum(vector[index] for vector in vectors) / len(vectors) for index in range(3))

    centered_vectors = [
        tuple(vector[index] - vector_means[index] for index in range(3))
        for vector in vectors
    ]
    centered_targets = [target - target_mean for target in targets]

    principal_component = first_principal_component(centered_vectors)
    if principal_component is None:
        return Wt901MagnetometerYawFit(
            status="singular-fit",
            samples=len(points),
            relative_yaw_start_deg=min(targets),
            relative_yaw_end_deg=max(targets),
            coefficients=(0.0, 0.0, 0.0),
            intercept=target_mean,
            rmse_deg=None,
            mae_deg=None,
            max_error_deg=None,
            r_squared=None,
        )

    projections = [
        sum(vector[index] * principal_component[index] for index in range(3))
        for vector in centered_vectors
    ]
    projection_variance = sum(projection * projection for projection in projections)
    if projection_variance == 0:
        return Wt901MagnetometerYawFit(
            status="singular-fit",
            samples=len(points),
            relative_yaw_start_deg=min(targets),
            relative_yaw_end_deg=max(targets),
            coefficients=(0.0, 0.0, 0.0),
            intercept=target_mean,
            rmse_deg=None,
            mae_deg=None,
            max_error_deg=None,
            r_squared=None,
        )

    slope = sum(
        projection * target
        for projection, target in zip(projections, centered_targets)
    ) / projection_variance
    coefficients = tuple(slope * value for value in principal_component)
    intercept = target_mean - sum(coefficients[index] * vector_means[index] for index in range(3))
    estimates = [
        intercept + sum(coefficients[index] * vector[index] for index in range(3))
        for vector in vectors
    ]
    errors = [estimate - target for estimate, target in zip(estimates, targets)]
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    mae = sum(abs(error) for error in errors) / len(errors)
    max_error = max(abs(error) for error in errors)
    total_variance = sum((target - target_mean) ** 2 for target in targets)
    residual_variance = sum(error * error for error in errors)
    r_squared = None if total_variance == 0 else 1 - (residual_variance / total_variance)

    return Wt901MagnetometerYawFit(
        status="fit",
        samples=len(points),
        relative_yaw_start_deg=min(targets),
        relative_yaw_end_deg=max(targets),
        coefficients=(coefficients[0], coefficients[1], coefficients[2]),
        intercept=intercept,
        rmse_deg=rmse,
        mae_deg=mae,
        max_error_deg=max_error,
        r_squared=r_squared,
    )


def first_principal_component(
    centered_vectors: list[tuple[float, float, float]],
    *,
    iterations: int = 32,
    epsilon: float = 1e-12,
) -> tuple[float, float, float] | None:
    covariance = [
        [
            sum(vector[row] * vector[col] for vector in centered_vectors)
            for col in range(3)
        ]
        for row in range(3)
    ]
    vector = (1.0, 1.0, 1.0)
    for _ in range(iterations):
        next_vector = tuple(
            sum(covariance[row][col] * vector[col] for col in range(3))
            for row in range(3)
        )
        norm = math.sqrt(sum(value * value for value in next_vector))
        if norm < epsilon:
            return None
        vector = tuple(value / norm for value in next_vector)
    return vector


def circular_span_deg(values: list[float]) -> float | None:
    if not values:
        return None
    normalized = sorted(value % 360 for value in values)
    if len(normalized) == 1:
        return 0.0
    gaps = [
        normalized[index + 1] - normalized[index]
        for index in range(len(normalized) - 1)
    ]
    gaps.append((normalized[0] + 360) - normalized[-1])
    return 360 - max(gaps)


def circular_stddev_deg(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    radians = [math.radians(value) for value in values]
    mean_sin = sum(math.sin(value) for value in radians) / len(radians)
    mean_cos = sum(math.cos(value) for value in radians) / len(radians)
    mean_angle = math.atan2(mean_sin, mean_cos)
    deltas = [
        math.degrees(math.atan2(math.sin(value - mean_angle), math.cos(value - mean_angle)))
        for value in radians
    ]
    return sample_stddev(deltas)

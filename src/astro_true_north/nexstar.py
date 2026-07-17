"""Celestron NexStar hand-controller read-only utilities and motion guards."""

from __future__ import annotations

import os
import select
import termios
import time
from dataclasses import dataclass
from typing import BinaryIO


NEXSTAR_MODEL_NAMES: dict[int, str] = {
    1: "GPS Series",
    3: "i-Series",
    4: "i-Series SE",
    5: "CGE",
    6: "Advanced GT",
    7: "SLT",
    9: "CPC",
    10: "GT",
    11: "4/5 SE",
    12: "6/8 SE",
    14: "CGE Pro",
    15: "CGEM DX",
    16: "LCM",
    17: "SkyProdigy",
    18: "CPC Deluxe",
    19: "AVX",
    20: "CGX",
}

MAX_SLOW_YAW_RATE_DEG_PER_SEC = 0.5
MAX_SLOW_YAW_DURATION_SECONDS = 120.0


class NexStarProtocolError(RuntimeError):
    """Raised when the hand controller does not return a valid response."""


class MountMotionLockedError(ValueError):
    """Raised when a planned motion violates the safety guardrails."""


@dataclass(frozen=True)
class NexStarStatus:
    port: str
    version_major: int
    version_minor: int
    model_code: int
    model_name: str
    alignment_complete: bool
    goto_in_progress: bool
    tracking_mode: int
    azimuth_deg: float
    altitude_deg: float

    def report_lines(self) -> list[str]:
        return [
            f"NexStar on {self.port}",
            f"Version: {self.version_major}.{self.version_minor:02d}",
            f"Model: {self.model_name} ({self.model_code})",
            f"Alignment complete: {self.alignment_complete}",
            f"GOTO in progress: {self.goto_in_progress}",
            f"Tracking mode: {self.tracking_mode}",
            f"Azimuth: {self.azimuth_deg:.3f} deg",
            f"Altitude: {self.altitude_deg:.3f} deg",
        ]


@dataclass(frozen=True)
class SlowYawPlan:
    direction: str
    rate_deg_per_sec: float
    duration_seconds: float
    operator_approved: bool
    abort_ready: bool

    @property
    def sweep_degrees(self) -> float:
        return self.rate_deg_per_sec * self.duration_seconds

    def report_lines(self) -> list[str]:
        return [
            "NexStar slow-yaw plan validated.",
            f"Direction: {self.direction}",
            f"Rate: {self.rate_deg_per_sec:.3f} deg/s",
            f"Duration: {self.duration_seconds:.1f} s",
            f"Sweep: {self.sweep_degrees:.3f} deg",
            "Motor command emission: disabled in this prototype step.",
        ]


def query_nexstar_status(
    port: str,
    *,
    baud: int = 9600,
    timeout_seconds: float = 2.0,
) -> NexStarStatus:
    """Read basic NexStar hand-controller status without issuing movement commands."""
    with NexStarSerial(port, baud=baud, timeout_seconds=timeout_seconds) as serial:
        echo = serial.transact(b"Kx")
        if echo != b"x":
            raise NexStarProtocolError(f"unexpected NexStar echo response: {echo!r}")

        version = serial.transact(b"V")
        if len(version) != 2:
            raise NexStarProtocolError(f"unexpected NexStar version response: {version!r}")

        model = serial.transact(b"m")
        if len(model) != 1:
            raise NexStarProtocolError(f"unexpected NexStar model response: {model!r}")

        alignment = serial.transact(b"J")
        goto = serial.transact(b"L")
        tracking = serial.transact(b"t")
        az_alt = serial.transact(b"Z")

    model_code = model[0]
    return NexStarStatus(
        port=port,
        version_major=version[0],
        version_minor=version[1],
        model_code=model_code,
        model_name=NEXSTAR_MODEL_NAMES.get(model_code, "Unknown"),
        alignment_complete=parse_flag_response(alignment),
        goto_in_progress=parse_ascii_digit_flag(goto),
        tracking_mode=parse_single_byte_value(tracking),
        azimuth_deg=parse_nexstar_angle_pair(az_alt)[0],
        altitude_deg=parse_nexstar_angle_pair(az_alt)[1],
    )


def validate_slow_yaw_plan(
    *,
    direction: str,
    rate_deg_per_sec: float,
    duration_seconds: float,
    operator_approved: bool,
    abort_ready: bool,
) -> SlowYawPlan:
    normalized_direction = direction.lower()
    if normalized_direction not in {"left", "right"}:
        raise MountMotionLockedError("direction must be 'left' or 'right'")
    if rate_deg_per_sec <= 0:
        raise MountMotionLockedError("yaw rate must be greater than zero")
    if rate_deg_per_sec > MAX_SLOW_YAW_RATE_DEG_PER_SEC:
        raise MountMotionLockedError(
            f"yaw rate exceeds {MAX_SLOW_YAW_RATE_DEG_PER_SEC:.2f} deg/s limit"
        )
    if duration_seconds <= 0:
        raise MountMotionLockedError("yaw duration must be greater than zero")
    if duration_seconds > MAX_SLOW_YAW_DURATION_SECONDS:
        raise MountMotionLockedError(
            f"yaw duration exceeds {MAX_SLOW_YAW_DURATION_SECONDS:.0f} s limit"
        )
    if not operator_approved:
        raise MountMotionLockedError("operator approval is required before mount motion")
    if not abort_ready:
        raise MountMotionLockedError("stop/abort path must be ready before mount motion")
    return SlowYawPlan(
        direction=normalized_direction,
        rate_deg_per_sec=rate_deg_per_sec,
        duration_seconds=duration_seconds,
        operator_approved=operator_approved,
        abort_ready=abort_ready,
    )


class NexStarSerial:
    """Minimal POSIX serial transport for NexStar hand-control commands."""

    def __init__(self, port: str, *, baud: int, timeout_seconds: float) -> None:
        self.port = port
        self.baud = baud
        self.timeout_seconds = timeout_seconds
        self.fd: int | None = None

    def __enter__(self) -> "NexStarSerial":
        self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        configure_nexstar_serial(self.fd, self.baud)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def transact(self, payload: bytes) -> bytes:
        if self.fd is None:
            raise NexStarProtocolError("serial port is not open")
        os.write(self.fd, payload)
        response = read_until_hash(self.fd, timeout_seconds=self.timeout_seconds)
        return strip_terminator(response)


def configure_nexstar_serial(fd: int, baud: int) -> None:
    baud_constant = baud_to_termios(baud)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = baud_constant
    attrs[5] = baud_constant
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def baud_to_termios(baud: int) -> int:
    if baud == 9600:
        return termios.B9600
    raise ValueError("NexStar hand-controller serial currently supports 9600 baud")


def read_until_hash(fd: int, *, timeout_seconds: float) -> bytes:
    deadline = time.monotonic() + timeout_seconds
    data = bytearray()
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.1)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 128)
        except BlockingIOError:
            continue
        if not chunk:
            continue
        data.extend(chunk)
        if b"#" in data:
            return bytes(data)
    raise NexStarProtocolError("timed out waiting for NexStar response")


def strip_terminator(response: bytes) -> bytes:
    if not response.endswith(b"#"):
        raise NexStarProtocolError(f"NexStar response missing terminator: {response!r}")
    return response[:-1]


def parse_flag_response(response: bytes) -> bool:
    value = parse_single_byte_value(response)
    if value not in {0, 1}:
        raise NexStarProtocolError(f"expected 0/1 flag response, got {response!r}")
    return bool(value)


def parse_ascii_digit_flag(response: bytes) -> bool:
    if response not in {b"0", b"1"}:
        raise NexStarProtocolError(f"expected ASCII 0/1 flag response, got {response!r}")
    return response == b"1"


def parse_single_byte_value(response: bytes) -> int:
    if len(response) != 1:
        raise NexStarProtocolError(f"expected one-byte response, got {response!r}")
    return response[0]


def parse_nexstar_angle_pair(response: bytes) -> tuple[float, float]:
    try:
        first, second = response.decode("ascii").split(",", maxsplit=1)
    except (UnicodeDecodeError, ValueError) as exc:
        raise NexStarProtocolError(f"invalid NexStar angle pair: {response!r}") from exc
    return hex_angle_to_degrees(first), hex_angle_to_degrees(second)


def hex_angle_to_degrees(value: str) -> float:
    bits = len(value) * 4
    if bits not in {16, 32}:
        raise NexStarProtocolError(f"invalid NexStar angle width: {value!r}")
    try:
        raw = int(value, 16)
    except ValueError as exc:
        raise NexStarProtocolError(f"invalid NexStar angle value: {value!r}") from exc
    return raw / float(1 << bits) * 360.0

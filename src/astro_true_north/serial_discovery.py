"""Runtime serial-port discovery for supported telescope sensors."""

from __future__ import annotations

from dataclasses import dataclass
import glob
import time

from astro_true_north.bn220 import is_valid_nmea, sentence_type
from astro_true_north.wt901 import (
    FRAME_LENGTH,
    FRAME_START,
    configure_serial_port,
    decode_wt901_frame,
)


DEFAULT_SERIAL_PATTERNS = ("/dev/ttyUSB*", "/dev/ttyACM*")
SUPPORTED_TARGETS = ("wt901", "bn220")


@dataclass(frozen=True)
class SerialProbeResult:
    """Summary of one candidate serial-port probe."""

    port: str
    bytes_read: int
    wt901_frames: int
    nmea_sentences: int
    nmea_types: tuple[str, ...]
    error: str | None = None

    @property
    def looks_like_wt901(self) -> bool:
        return self.wt901_frames > 0

    @property
    def looks_like_bn220(self) -> bool:
        return self.nmea_sentences > 0

    def report_line(self) -> str:
        if self.error:
            return f"{self.port}: error: {self.error}"
        labels: list[str] = []
        if self.looks_like_wt901:
            labels.append("WT901")
        if self.looks_like_bn220:
            labels.append("BN-220")
        label_text = ", ".join(labels) if labels else "unknown"
        nmea_text = ",".join(self.nmea_types) if self.nmea_types else "none"
        return (
            f"{self.port}: {label_text}; bytes={self.bytes_read}; "
            f"wt901_frames={self.wt901_frames}; nmea_sentences={self.nmea_sentences}; "
            f"nmea_types={nmea_text}"
        )


def candidate_serial_ports(patterns: tuple[str, ...] = DEFAULT_SERIAL_PATTERNS) -> list[str]:
    """Return sorted candidate serial devices for local USB-attached sensors."""

    ports: set[str] = set()
    for pattern in patterns:
        ports.update(glob.glob(pattern))
    return sorted(ports)


def probe_serial_port(
    port: str,
    *,
    baud: int = 9600,
    duration_seconds: float = 2.0,
) -> SerialProbeResult:
    """Read a short byte sample from one serial port and classify known sensors."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    data = bytearray()
    try:
        with open(port, "rb", buffering=0) as device:
            configure_serial_port(device, baud)
            deadline = time.monotonic() + duration_seconds
            while time.monotonic() < deadline:
                chunk = device.read(256)
                if chunk:
                    data.extend(chunk)
    except OSError as exc:
        return SerialProbeResult(
            port=port,
            bytes_read=0,
            wt901_frames=0,
            nmea_sentences=0,
            nmea_types=(),
            error=str(exc),
        )

    wt901_frames = count_wt901_frames(bytes(data))
    nmea_sentences, nmea_types = count_nmea_sentences(bytes(data))
    return SerialProbeResult(
        port=port,
        bytes_read=len(data),
        wt901_frames=wt901_frames,
        nmea_sentences=nmea_sentences,
        nmea_types=nmea_types,
    )


def discover_serial_ports(
    *,
    baud: int = 9600,
    duration_seconds: float = 2.0,
    ports: list[str] | None = None,
) -> list[SerialProbeResult]:
    """Probe candidate serial ports and return one result per candidate."""

    candidates = ports if ports is not None else candidate_serial_ports()
    return [
        probe_serial_port(port, baud=baud, duration_seconds=duration_seconds)
        for port in candidates
    ]


def resolve_sensor_port(
    target: str,
    *,
    baud: int = 9600,
    duration_seconds: float = 2.0,
    ports: list[str] | None = None,
) -> tuple[str | None, list[SerialProbeResult]]:
    """Find the first port that looks like the requested sensor target."""

    if target not in SUPPORTED_TARGETS:
        raise ValueError(f"unsupported serial target: {target}")
    results = discover_serial_ports(
        baud=baud,
        duration_seconds=duration_seconds,
        ports=ports,
    )
    for result in results:
        if target == "wt901" and result.looks_like_wt901:
            return result.port, results
        if target == "bn220" and result.looks_like_bn220:
            return result.port, results
    return None, results


def count_wt901_frames(data: bytes) -> int:
    """Count valid WT901 angle or magnetometer frames in sampled bytes."""

    frames = 0
    buffer = bytearray(data)
    while len(buffer) >= FRAME_LENGTH:
        if buffer[0] != FRAME_START:
            del buffer[0]
            continue
        frame = bytes(buffer[:FRAME_LENGTH])
        del buffer[:FRAME_LENGTH]
        if decode_wt901_frame(frame) is not None:
            frames += 1
    return frames


def count_nmea_sentences(data: bytes) -> tuple[int, tuple[str, ...]]:
    """Count valid NMEA sentences and return observed sentence types."""

    text = data.decode("ascii", errors="ignore")
    valid_types: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("$") or not is_valid_nmea(line):
            continue
        sentence = sentence_type(line)
        if sentence:
            valid_types.append(sentence)
    return len(valid_types), tuple(dict.fromkeys(valid_types))

"""BN-220 GPS NMEA reader utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import BinaryIO

from astro_true_north.wt901 import configure_serial_port


@dataclass(frozen=True)
class Bn220GpsFix:
    """Best GPS fix details decoded from a BN-220 NMEA stream."""

    has_fix: bool
    timestamp_utc: datetime | None
    latitude_deg: float | None
    longitude_deg: float | None
    satellites: int | None
    hdop: float | None
    altitude_m: float | None
    source_sentences: tuple[str, ...]


@dataclass(frozen=True)
class Bn220CaptureSummary:
    """Summary of a short BN-220 capture."""

    sentences_seen: int
    valid_sentences: int
    rmc_sentences: int
    gga_sentences: int
    fix: Bn220GpsFix | None

    def report_lines(self) -> list[str]:
        lines = [
            "BN-220 GPS sample summary",
            f"Sentences: {self.sentences_seen}",
            f"Valid NMEA sentences: {self.valid_sentences}",
            f"RMC sentences: {self.rmc_sentences}",
            f"GGA sentences: {self.gga_sentences}",
        ]
        if self.fix is None:
            lines.append("No GPS fix sentence decoded. Check baud rate, wiring, and sky view.")
            return lines

        lines.append(f"Fix status: {'fixed' if self.fix.has_fix else 'not fixed'}")
        if self.fix.timestamp_utc:
            lines.append(f"GPS time: {self.fix.timestamp_utc.isoformat()}")
        if self.fix.latitude_deg is not None and self.fix.longitude_deg is not None:
            lines.append(
                "Coarse location: "
                f"{self.fix.latitude_deg:.1f}, {self.fix.longitude_deg:.1f} "
                "(rounded to 0.1 deg)"
            )
        if self.fix.satellites is not None:
            lines.append(f"Satellites: {self.fix.satellites}")
        if self.fix.hdop is not None:
            lines.append(f"HDOP: {self.fix.hdop:.1f}")
        if self.fix.altitude_m is not None:
            lines.append(f"Altitude: {self.fix.altitude_m:.0f} m")
        return lines


def capture_bn220(
    port: str,
    *,
    baud: int = 9600,
    duration_seconds: float = 10.0,
    prompt: str | None = None,
) -> Bn220CaptureSummary:
    """Read a BN-220 serial stream for a short period and summarize NMEA data."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    with open(port, "rb", buffering=0) as device:
        configure_serial_port(device, baud)
        if prompt:
            print(prompt, flush=True)
        deadline = time.monotonic() + duration_seconds
        sentences: list[str] = []
        buffer = bytearray()
        while time.monotonic() < deadline:
            chunk = device.read(128)
            if not chunk:
                continue
            buffer.extend(chunk)
            while b"\n" in buffer:
                line, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                sentence = line.decode("ascii", errors="ignore").strip()
                if sentence:
                    sentences.append(sentence)
    return summarize_bn220_sentences(sentences)


def summarize_bn220_sentences(sentences: list[str]) -> Bn220CaptureSummary:
    valid_sentences = [sentence for sentence in sentences if is_valid_nmea(sentence)]
    rmc_sentences = [
        sentence for sentence in valid_sentences if sentence_type(sentence).endswith("RMC")
    ]
    gga_sentences = [
        sentence for sentence in valid_sentences if sentence_type(sentence).endswith("GGA")
    ]
    fix = build_fix(rmc_sentences, gga_sentences)
    return Bn220CaptureSummary(
        sentences_seen=len(sentences),
        valid_sentences=len(valid_sentences),
        rmc_sentences=len(rmc_sentences),
        gga_sentences=len(gga_sentences),
        fix=fix,
    )


def build_fix(
    rmc_sentences: list[str],
    gga_sentences: list[str],
) -> Bn220GpsFix | None:
    rmc = parse_rmc(rmc_sentences[-1]) if rmc_sentences else {}
    gga = parse_gga(gga_sentences[-1]) if gga_sentences else {}
    if not rmc and not gga:
        return None

    latitude = rmc.get("latitude_deg", gga.get("latitude_deg"))
    longitude = rmc.get("longitude_deg", gga.get("longitude_deg"))
    has_fix = bool(rmc.get("has_fix") or gga.get("has_fix"))
    sources = tuple(sentence_type(sentence) for sentence in [*rmc_sentences[-1:], *gga_sentences[-1:]])
    return Bn220GpsFix(
        has_fix=has_fix,
        timestamp_utc=rmc.get("timestamp_utc"),
        latitude_deg=latitude,
        longitude_deg=longitude,
        satellites=gga.get("satellites"),
        hdop=gga.get("hdop"),
        altitude_m=gga.get("altitude_m"),
        source_sentences=sources,
    )


def is_valid_nmea(sentence: str) -> bool:
    if not sentence.startswith("$"):
        return False
    if "*" not in sentence:
        return True
    body, checksum_text = sentence[1:].split("*", 1)
    try:
        expected = int(checksum_text[:2], 16)
    except ValueError:
        return False
    actual = 0
    for char in body:
        actual ^= ord(char)
    return actual == expected


def sentence_type(sentence: str) -> str:
    return sentence[1:].split(",", 1)[0] if sentence.startswith("$") else ""


def parse_rmc(sentence: str) -> dict[str, object]:
    fields = sentence_body(sentence).split(",")
    if len(fields) < 10:
        return {}
    status = fields[2]
    latitude = parse_nmea_coordinate(fields[3], fields[4])
    longitude = parse_nmea_coordinate(fields[5], fields[6])
    timestamp = parse_rmc_timestamp(fields[1], fields[9])
    return {
        "has_fix": status == "A" and latitude is not None and longitude is not None,
        "timestamp_utc": timestamp,
        "latitude_deg": latitude,
        "longitude_deg": longitude,
    }


def parse_gga(sentence: str) -> dict[str, object]:
    fields = sentence_body(sentence).split(",")
    if len(fields) < 10:
        return {}
    fix_quality = parse_int(fields[6])
    latitude = parse_nmea_coordinate(fields[2], fields[3])
    longitude = parse_nmea_coordinate(fields[4], fields[5])
    return {
        "has_fix": bool(fix_quality),
        "latitude_deg": latitude,
        "longitude_deg": longitude,
        "satellites": parse_int(fields[7]),
        "hdop": parse_float(fields[8]),
        "altitude_m": parse_float(fields[9]),
    }


def sentence_body(sentence: str) -> str:
    body = sentence[1:] if sentence.startswith("$") else sentence
    return body.split("*", 1)[0]


def parse_nmea_coordinate(value: str, hemisphere: str) -> float | None:
    if not value or not hemisphere:
        return None
    try:
        raw = float(value)
    except ValueError:
        return None
    degrees = int(raw // 100)
    minutes = raw - (degrees * 100)
    coordinate = degrees + (minutes / 60)
    if hemisphere in {"S", "W"}:
        coordinate = -coordinate
    if hemisphere not in {"N", "S", "E", "W"}:
        return None
    return coordinate


def parse_rmc_timestamp(time_text: str, date_text: str) -> datetime | None:
    if len(time_text) < 6 or len(date_text) != 6:
        return None
    try:
        hour = int(time_text[0:2])
        minute = int(time_text[2:4])
        second = int(time_text[4:6])
        day = int(date_text[0:2])
        month = int(date_text[2:4])
        year = 2000 + int(date_text[4:6])
    except ValueError:
        return None
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None

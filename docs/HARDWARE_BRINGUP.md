# Hardware Bring-Up

## First Target

The first live hardware target is a WitMotion WT901 connected over TTL UART
through a USB serial adapter. This gives the prototype live roll, pitch, yaw,
and magnetometer samples before any mount-control work is attempted.

## WT901 Wiring

For the tested WT901 module, use the right-side UART pins:

- USB adapter `3V3` to WT901 `VCC`.
- USB adapter `GND` to WT901 `GND`.
- USB adapter `RXD` to WT901 `TX`.
- USB adapter `TXD` to WT901 `RX`.

The first confirmed adapter path was `/dev/ttyUSB0`, exposed as
`/dev/serial/by-id/usb-1a86_USB_UART-LPT-if00-port0`. The first working baud
rate was `9600`.

Do not use the RS485/RS422 adapter for this TTL UART wiring.

## BN-220 GPS Wiring

The tested Beitian BN-220 GPS lead colours connect to the USB UART adapter as:

- Red: `VCC`.
- Black: `GND`.
- Green: `TX`.
- White: `RX`.

For a first listen-only GPS test:

- USB adapter power to GPS red `VCC`.
- USB adapter `GND` to GPS black `GND`.
- USB adapter `RXD` to GPS green `TX`.
- Leave GPS white `RX` disconnected unless configuration commands are needed.

The first confirmed GPS adapter path was `/dev/ttyUSB1`. The first observed
behavior was readable GPS chatter at the serial console.

## Manual Smoke Test

Without Python dependencies, raw packets can be checked with:

```bash
PORT=/dev/ttyUSB0
stty -F "$PORT" 9600 cs8 -cstopb -parenb raw -echo
xxd -g 1 "$PORT"
```

WT901 packets start with `0x55`. Useful frame kinds are:

- `55 51`: acceleration.
- `55 52`: gyro.
- `55 53`: roll, pitch, and yaw angle.
- `55 54`: magnetic field.

The BN-220 should emit readable NMEA sentences instead of binary frames:

```bash
PORT=/dev/ttyUSB1
stty -F "$PORT" 9600 cs8 -cstopb -parenb raw -echo
cat "$PORT"
```

Expected sentence prefixes include `$GNGGA` and `$GNRMC`.

## Prototype Sampler

The project CLI can read and summarize a short live WT901 capture:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --sample-wt901 /dev/ttyUSB0 \
  --wt901-duration 20
```

It can also read and summarize a short live BN-220 GPS capture:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --sample-bn220 /dev/ttyUSB1 \
  --gps-duration 20
```

The GPS report intentionally rounds any decoded location to 0.1 degrees.

The first stationary WT901 error-budget capture uses:

```bash
PYTHONPATH=src python -m astro_true_north.cli \
  --calibrate-wt901 /dev/ttyUSB0 \
  --wt901-duration 15
```

If the device is not readable, add the operator user to the serial device group
or temporarily adjust the device permissions for the session.

## First Live Capture

On 2026-07-15, the prototype decoded a live WT901 stream over `/dev/ttyUSB0` at
9600 baud. A 20-second movement capture produced 401 decoded samples:

- 201 angle frames.
- 200 magnetometer frames.
- Roll range: -24.88 to 131.25 degrees.
- Pitch range: -12.97 to 45.75 degrees.
- Yaw range: -179.48 to 177.46 degrees.
- Magnetometer magnitude range: 3284 to 8832 raw counts.

This confirms the UART reader and frame parser are good enough for the first
calibration and error-budget work.

## First GPS Capture

On 2026-07-15, the prototype decoded live BN-220 NMEA over `/dev/ttyUSB1` at
9600 baud. A 20-second indoor/no-sky-view sample produced 160 valid sentences,
including 20 RMC sentences and 20 GGA sentences, but no fix:

- Fix status: not fixed.
- Satellites: 0.
- HDOP: 100.0.

A 60-second follow-up produced the same no-fix status. A short no-fix NMEA
fixture is stored in `tests/fixtures/bn220_no_fix_nmea.txt`. A fixed outdoor or
window-sky capture remains a hardware follow-up.

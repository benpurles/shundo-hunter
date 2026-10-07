#!/usr/bin/env python3
"""Run an auditable 1 Hz iOS DVT location simulation probe.

Apple's DVT LocationSimulation service accepts latitude and longitude only.
This utility records the values sent plus route-derived speed and course. Fields
that DVT cannot control are marked explicitly rather than fabricated.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


EARTH_RADIUS_M = 6_371_000.0
SET_RE = re.compile(
    r"^(?P<actual>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) .* "
    r"set location to (?P<lat>-?\d+(?:\.\d+)?) (?P<lon>-?\d+(?:\.\d+)?)$"
)


def destination(latitude: float, longitude: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)
    angular_distance = distance_m / EARTH_RADIUS_M
    bearing = math.radians(bearing_deg)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def build_points(args: argparse.Namespace) -> list[dict[str, object]]:
    if args.mode == "stationary":
        duration_s = args.duration
        speed_mps = 0.0
        course_deg: float | None = None
    else:
        speed_mps = args.speed_kmh / 3.6
        duration_s = round(args.distance / speed_mps)
        course_deg = args.bearing

    started = datetime.now(timezone.utc).replace(microsecond=0)
    points: list[dict[str, object]] = []
    for second in range(duration_s + 1):
        distance_m = 0.0 if args.mode == "stationary" else min(args.distance, speed_mps * second)
        lat, lon = destination(args.latitude, args.longitude, distance_m, args.bearing)
        points.append(
            {
                "sequence": second,
                "scheduled_at_utc": started + timedelta(seconds=second),
                "latitude": lat,
                "longitude": lon,
                "derived_speed_mps": speed_mps,
                "derived_course_deg": course_deg,
            }
        )
    return points


def write_gpx(path: Path, points: list[dict[str, object]]) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Codex iPogo probe" xmlns="http://www.topografix.com/GPX/1/1">',
        "  <trk><name>iPogo 1 Hz diagnostic probe</name><trkseg>",
    ]
    for point in points:
        timestamp = point["scheduled_at_utc"].isoformat().replace("+00:00", "Z")
        lines.append(
            f'    <trkpt lat="{point["latitude"]:.8f}" lon="{point["longitude"]:.8f}"><time>{timestamp}</time></trkpt>'
        )
    lines.extend(["  </trkseg></trk>", "</gpx>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_probe(args: argparse.Namespace, points: list[dict[str, object]], gpx_path: Path, log_path: Path) -> int:
    executable = shutil.which("pymobiledevice3")
    if executable is None:
        raise RuntimeError("pymobiledevice3 is not available on PATH")

    command = [
        executable,
        "developer",
        "dvt",
        "simulate-location",
        "play",
        "--userspace",
        "--udid",
        args.udid,
        str(gpx_path),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    fieldnames = [
        "sequence",
        "actual_sent_at_local",
        "scheduled_at_utc",
        "latitude",
        "longitude",
        "horizontal_accuracy",
        "vertical_accuracy",
        "altitude",
        "derived_speed_mps",
        "derived_course_deg",
        "source_is_simulated_by_software",
        "delivery_method",
    ]
    sent = 0
    with log_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            print(line, flush=True)
            match = SET_RE.search(line)
            if match is None or sent >= len(points):
                continue

            point = points[sent]
            writer.writerow(
                {
                    "sequence": sent,
                    "actual_sent_at_local": match.group("actual"),
                    "scheduled_at_utc": point["scheduled_at_utc"].isoformat(),
                    "latitude": match.group("lat"),
                    "longitude": match.group("lon"),
                    "horizontal_accuracy": "not controllable by DVT selector",
                    "vertical_accuracy": "not controllable by DVT selector",
                    "altitude": "not controllable by DVT selector",
                    "derived_speed_mps": f'{point["derived_speed_mps"]:.6f}',
                    "derived_course_deg": "" if point["derived_course_deg"] is None else point["derived_course_deg"],
                    "source_is_simulated_by_software": "expected true (Apple DVT simulation)",
                    "delivery_method": "com.apple.instruments.server.services.LocationSimulation",
                }
            )
            output.flush()
            sent += 1
            if sent == len(points) and process.stdin is not None:
                process.stdin.write("\n")
                process.stdin.flush()

    return_code = process.wait()
    if return_code == 0 and sent != len(points):
        print(f"Expected {len(points)} updates but observed {sent}", file=sys.stderr)
        return 2
    return return_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("stationary", "walk"))
    parser.add_argument("--latitude", type=float, default=40.7608)
    parser.add_argument("--longitude", type=float, default=-111.8910)
    parser.add_argument("--duration", type=int, default=30, help="Stationary duration in seconds")
    parser.add_argument("--distance", type=float, default=100.0, help="Walking distance in meters")
    parser.add_argument("--speed-kmh", type=float, default=5.0)
    parser.add_argument("--bearing", type=float, default=90.0, help="Degrees clockwise from true north")
    parser.add_argument("--udid", default="00008110-000A5CA93EBB801E")
    parser.add_argument("--output-dir", type=Path, default=Path("location-probe-output"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    points = build_points(args)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    gpx_path = args.output_dir / f"{args.mode}-{stamp}.gpx"
    log_path = args.output_dir / f"{args.mode}-{stamp}.csv"
    write_gpx(gpx_path, points)
    print(f"GPX: {gpx_path}")
    print(f"Log: {log_path}")
    return run_probe(args, points, gpx_path, log_path)


if __name__ == "__main__":
    raise SystemExit(main())

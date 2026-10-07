from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import select
import signal
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any


class DeviceError(RuntimeError):
    pass


class DeviceController:
    """Small, auditable wrapper around pymobiledevice3's DVT location service."""

    HUNT_WALK_RADIUS_METERS = 20.0
    HUNT_WALK_SPEED_KMH = 10.0
    ROUTE_DURATION_SECONDS = 24 * 60 * 60
    IPOGO_BUNDLE_ID = "com.nianticlabs.pokemongo"
    IPOGO_CLEAN_RESTART_DELAY_SECONDS = 8.0
    SPAWN_RUNTIME_MARKER_KEY = "ShundoSpawnRuntimeVersion"
    SUPPORTED_SPAWN_RUNTIME_VERSION = "8"
    SUPPORTED_SPAWN_RUNTIME_BUILD = "worldscan-v3-ipogo439-20260925b"
    SUPPORTED_IPOGO_BUNDLE_VERSION = "0"
    # Exact signed iPogo 4.3.9 artifact: external-location compatibility,
    # notification logging, and the read-only v3 world observer. Do not
    # substitute a rebuild merely because its runtime bytes match.
    SUPPORTED_SPAWN_RUNTIME_IPA_SHA256 = "a728aaca83f64bdb972902f4f1f7ea51446c68539d21d9c00d2c61ec9af9341b"

    def __init__(self, poll_interval: float = 10.0):
        self.executable = self._find_pymobiledevice3()
        self.xcrun_executable = shutil.which("xcrun")
        self.ipogo_restart_delay_seconds = self.IPOGO_CLEAN_RESTART_DELAY_SECONDS
        self.poll_interval = poll_interval
        self.lock = threading.Lock()
        self.location_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.location_process: subprocess.Popen[str] | None = None
        self.location_route_path: Path | None = None
        self.location_output_thread: threading.Thread | None = None
        # Pin to the verified phone across USB/Wi-Fi transitions. Never silently
        # redirect a hunt to another paired device when this one disappears.
        self._selected_udid: str | None = None
        receipt_path = Path.home() / "Library/Application Support/Shundo Hunter/spawn-runtime-receipt.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if isinstance(receipt, dict) and isinstance(receipt.get("deviceUdid"), str):
                self._selected_udid = receipt["deviceUdid"] or None
        except (OSError, ValueError):
            pass
        self._status: dict[str, Any] = {
            "phoneConnected": False,
            "phoneName": None,
            "phoneUdid": None,
            "phoneProductVersion": None,
            "phoneConnectionType": None,
            "phoneLastCheckedAt": None,
            "phoneLastError": None,
            "phoneSimulatedLocation": None,
            "phoneTunnelMode": None,
            "phoneLocationDelivery": None,
            "phoneMovementMode": None,
            "phoneMovementRadiusMeters": None,
            "phoneMovementSpeedKmh": None,
            "ipogoSpawnRuntimeVerified": False,
            "ipogoSpawnRuntimeVersion": None,
            "ipogoSpawnRuntimeError": "Not checked",
            "ipogoLastRestartAt": None,
            "ipogoLastRestartPid": None,
            "ipogoRestartCount": 0,
            "ipogoRestartLastError": None,
            "ipogoRestartMethod": None,
        }
        self.thread = threading.Thread(target=self._monitor, name="iphone-monitor", daemon=True)
        self.thread.start()

    @staticmethod
    def _find_pymobiledevice3(home: Path | None = None) -> str | None:
        """Find shell and pipx installs even when Finder supplies a minimal PATH."""
        discovered = shutil.which("pymobiledevice3")
        if discovered:
            return discovered
        user_home = home or Path.home()
        candidates = (
            user_home / ".local/bin/pymobiledevice3",
            Path("/opt/homebrew/bin/pymobiledevice3"),
            Path("/usr/local/bin/pymobiledevice3"),
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _run(self, command: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
        command = self.transport_command(command)
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as error:
            raise DeviceError("pymobiledevice3 is not installed") from error
        except subprocess.TimeoutExpired as error:
            raise DeviceError("The iPhone command timed out") from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or "iPhone command failed").strip()
            raise DeviceError(detail[-800:]) from error

    def transport_command(self, command):
        if (command and command[0] == self.executable and "--udid" in command
                and self.status().get("phoneNativeWifi")):
            from .native_wifi import route
            return route(self.executable, command[1:])
        if (command and command[0] == self.executable and "--tunnel" in command
                and self.status().get("phoneNativeWifi")):
            from .native_wifi import route
            return route(self.executable, command[1:])
        return command

    def _native_discover(self, udid):
        from .native_wifi import command
        try:
            result = self._run(command(self.executable, ["discover", udid]), timeout=14)
            device = json.loads(result.stdout)
            return device if isinstance(device, dict) and device.get("UniqueDeviceID") == udid else None
        except (DeviceError, RuntimeError, ValueError):
            return None

    @staticmethod
    def _refresh_runtime_receipt_sequence(
        receipt_path: Path,
        receipt: dict[str, Any],
        sequence_number: int,
    ) -> None:
        """Refresh volatile InstallationProxy metadata without changing trust data."""
        updated = dict(receipt)
        updated["sequenceNumber"] = sequence_number
        updated["lastVerifiedAt"] = datetime.now(timezone.utc).isoformat()
        temporary = receipt_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(updated, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, receipt_path)

    def refresh(self) -> dict[str, Any]:
        checked_at = self._now()
        if not self.executable:
            with self.lock:
                self._status.update({
                    "phoneConnected": False,
                    "phoneLastCheckedAt": checked_at,
                    "phoneLastError": "pymobiledevice3 is not installed",
                })
                return dict(self._status)
        try:
            result = self._run([self.executable, "usbmux", "list"], timeout=12)
            devices = json.loads(result.stdout)
            if not isinstance(devices, list):
                raise DeviceError("The iPhone discovery service returned an invalid device list")
            candidates = [
                item for item in devices
                if isinstance(item, dict)
                and item.get("ConnectionType") in ("USB", "Network")
                and item.get("DeviceClass") in (None, "iPhone")
                and isinstance(item.get("UniqueDeviceID"), str)
                and item.get("UniqueDeviceID")
            ]
            selected = getattr(self, "_selected_udid", None) or self._status.get("phoneUdid")
            if selected and not any(item["UniqueDeviceID"] == selected for item in candidates):
                native = self._native_discover(selected)
                if native:
                    candidates.append(native)
            with self.lock:
                selected = getattr(self, "_selected_udid", None) or self._status.get("phoneUdid")
                if selected:
                    candidates = [item for item in candidates if item["UniqueDeviceID"] == selected]
                elif len({item["UniqueDeviceID"] for item in candidates}) > 1:
                    raise DeviceError("Multiple paired iPhones detected. Connect only the intended phone for initial setup.")
                candidates.sort(key=lambda item: item["ConnectionType"] != "USB")
                device = candidates[0] if candidates else None
                if device:
                    self._selected_udid = device["UniqueDeviceID"]
                self._status.update({
                    "phoneConnected": device is not None,
                    "phoneName": device.get("DeviceName") if device else None,
                    "phoneUdid": device.get("UniqueDeviceID") if device else None,
                    "phoneProductVersion": device.get("ProductVersion") if device else None,
                    "phoneConnectionType": device.get("ConnectionType") if device else None,
                    "phoneNativeWifi": bool(device and device.get("HunterNativeWifi")),
                    "phoneLastCheckedAt": checked_at,
                    "phoneLastError": None if device else (
                        "The selected iPhone is offline. Reconnect USB or join the same Wi-Fi network."
                        if selected else "No paired iPhone detected. Connect USB once to pair, or join the same Wi-Fi network."
                    ),
                })
        except (DeviceError, json.JSONDecodeError) as error:
            with self.lock:
                self._status.update({
                    "phoneConnected": False,
                    "phoneLastCheckedAt": checked_at,
                    "phoneLastError": str(error),
                })
        return self.status()

    def status(self) -> dict[str, Any]:
        with self.lock:
            return dict(self._status)

    def enable_wifi(self) -> dict[str, Any]:
        """Enable Apple's paired network transport without clearing location."""
        udid = self._connected_udid()
        self._run([
            self.executable, "lockdown", "wifi-connections", "--udid", udid,
            "--state", "on",
        ], timeout=20)
        result = self._run([
            self.executable, "lockdown", "wifi-connections", "--udid", udid,
        ], timeout=20)
        try:
            enabled = json.loads(result.stdout).get("EnableWifiConnections") is True
        except (ValueError, AttributeError):
            enabled = False
        if not enabled:
            raise DeviceError("Wi-Fi pairing could not be verified. Connect USB, unlock the phone and trust this Mac.")
        return self.refresh()

    def _connected_udid(self) -> str:
        status = self.status()
        if not status.get("phoneConnected") or not status.get("phoneUdid"):
            status = self.refresh()
        udid = status.get("phoneUdid")
        if not status.get("phoneConnected") or not isinstance(udid, str):
            raise DeviceError(str(status.get("phoneLastError") or "No paired iPhone detected over USB or Wi-Fi"))
        return udid

    def verify_ipogo_runtime(self) -> dict[str, Any]:
        """Require the versioned, spawn-compatible iPogo build before hunting."""
        udid = self._connected_udid()
        try:
            result = self._run(
                [self.executable, "apps", "list", "--type", "User", "--udid", udid],
                timeout=45,
            )
            applications = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise DeviceError("Could not read the installed iPhone applications") from error
        if not isinstance(applications, dict):
            raise DeviceError("The iPhone returned an invalid application list")
        app = applications.get(self.IPOGO_BUNDLE_ID)
        if not isinstance(app, dict):
            message = "The supported iPogo/Pokémon GO build is not installed"
            with self.lock:
                self._status.update({
                    "ipogoSpawnRuntimeVerified": False,
                    "ipogoSpawnRuntimeVersion": None,
                    "ipogoSpawnRuntimeError": message,
                })
            raise DeviceError(message)
        marker_version = str(app.get(self.SPAWN_RUNTIME_MARKER_KEY) or "")
        installed_build = str(app.get("CFBundleVersion") or "")
        receipt_path = Path.home() / "Library/Application Support/Shundo Hunter/spawn-runtime-receipt.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            receipt = None
        verified = bool(
            isinstance(receipt, dict)
            and receipt.get("bundleId") == self.IPOGO_BUNDLE_ID
            and receipt.get("deviceUdid") == udid
            and receipt.get("bundlePath") == app.get("Path")
            and receipt.get("ipaSha256") == self.SUPPORTED_SPAWN_RUNTIME_IPA_SHA256
            and str(receipt.get("runtimeVersion") or "") == self.SUPPORTED_SPAWN_RUNTIME_VERSION
            and str(receipt.get("runtimeBuild") or "") == self.SUPPORTED_SPAWN_RUNTIME_BUILD
        )
        # These fields are useful corroboration when InstallationProxy exposes
        # them, but the exact-hash install receipt is authoritative. iOS has
        # been observed returning the original build number for a dev update.
        metadata_consistent = (
            (not marker_version or marker_version == self.SUPPORTED_SPAWN_RUNTIME_VERSION)
            and (
                installed_build
                in (
                    "",
                    self.SUPPORTED_IPOGO_BUNDLE_VERSION,
                    self.SUPPORTED_SPAWN_RUNTIME_BUILD,
                )
            )
        )
        verified = verified and metadata_consistent
        # InstallationProxy's SequenceNumber is an inventory cursor, not an
        # app identity. iOS can renumber it after a reboot or inventory rebuild
        # while the installed bundle path and bytes remain unchanged. Keep it
        # in the receipt for diagnostics, but never reject an otherwise exact
        # runtime because this volatile value moved.
        installed_sequence = app.get("SequenceNumber")
        if (
            verified
            and isinstance(receipt, dict)
            and isinstance(installed_sequence, int)
            and receipt.get("sequenceNumber") != installed_sequence
        ):
            try:
                self._refresh_runtime_receipt_sequence(
                    receipt_path,
                    receipt,
                    installed_sequence,
                )
            except OSError:
                # Failure to update diagnostic metadata cannot invalidate the
                # already verified stable receipt fields.
                pass
        version = self.SUPPORTED_SPAWN_RUNTIME_VERSION if verified else marker_version
        error = None if verified else (
            "The installed iPogo does not match the verified Hunter Runtime receipt. "
            "Reinstall the empirically verified Hunter Runtime before starting."
        )
        with self.lock:
            self._status.update({
                "ipogoSpawnRuntimeVerified": verified,
                "ipogoSpawnRuntimeVersion": version or None,
                "ipogoSpawnRuntimeError": error,
            })
        if error:
            raise DeviceError(error)
        return self.status()

    def set_location(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Keep a coordinate active for manual location tests."""
        self._validate_location_request(latitude, longitude)
        route_path = self._write_stationary_route(latitude, longitude)
        return self._activate_route(
            latitude,
            longitude,
            route_path,
            delivery="continuous-1hz",
            movement_mode="stationary",
        )

    def set_hunt_location(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Teleport to a sighting, then continuously walk around its center."""
        self._validate_location_request(latitude, longitude)
        route_path = self._write_walking_route(
            latitude,
            longitude,
            radius_meters=self.HUNT_WALK_RADIUS_METERS,
            speed_kmh=self.HUNT_WALK_SPEED_KMH,
        )
        return self._activate_route(
            latitude,
            longitude,
            route_path,
            delivery="walking-loop-1hz",
            movement_mode="walking-circle",
            radius_meters=self.HUNT_WALK_RADIUS_METERS,
            speed_kmh=self.HUNT_WALK_SPEED_KMH,
        )

    def restart_ipogo(self) -> dict[str, Any]:
        """Cleanly terminate, wait, and foreground iPogo while preserving location."""
        if not self.executable:
            raise DeviceError("pymobiledevice3 is not installed")
        xcrun = getattr(self, "xcrun_executable", None) or shutil.which("xcrun")
        if not xcrun:
            raise DeviceError("Apple CoreDevice tools are unavailable because xcrun was not found")
        udid = self._connected_udid()
        with self.location_lock:
            route_process = self.location_process
            location = self.status().get("phoneSimulatedLocation")
            tunnel_mode = self.status().get("phoneTunnelMode")
            if route_process is None or route_process.poll() is not None or not location:
                raise DeviceError("Cannot refresh iPogo unless the simulated location is actively streaming")
            route_pid = route_process.pid
            tunnel_arguments = (
                ["--tunnel", udid]
                if tunnel_mode == "shared"
                else ["--userspace", "--udid", udid]
            )
            try:
                pid_result = self._run(
                    [
                        self.executable,
                        "developer", "dvt", "process-id-for-bundle-id",
                        *tunnel_arguments,
                        self.IPOGO_BUNDLE_ID,
                    ],
                    timeout=20,
                )
                pid_match = re.search(r"\b(\d+)\b", pid_result.stdout or "")
                if pid_match is None or int(pid_match.group(1)) <= 0:
                    raise DeviceError("Could not identify the running iPogo process")
                previous_pid = int(pid_match.group(1))
                self._run(
                    [
                        xcrun,
                        "devicectl", "device", "process", "terminate",
                        "--device", udid,
                        "--pid", str(previous_pid),
                        "--kill",
                    ],
                    timeout=45,
                )
                time.sleep(max(0.0, float(getattr(
                    self,
                    "ipogo_restart_delay_seconds",
                    self.IPOGO_CLEAN_RESTART_DELAY_SECONDS,
                ))))
                self._run(
                    [
                        xcrun,
                        "devicectl", "device", "process", "launch",
                        "--device", udid,
                        "--activate",
                        self.IPOGO_BUNDLE_ID,
                    ],
                    timeout=60,
                )
                launched_result = self._run(
                    [
                        self.executable,
                        "developer", "dvt", "process-id-for-bundle-id",
                        *tunnel_arguments,
                        self.IPOGO_BUNDLE_ID,
                    ],
                    timeout=20,
                )
                if self.location_process is not route_process or route_process.poll() is not None:
                    raise DeviceError("The location stream ended while iPogo was refreshing")
                launched_match = re.search(r"\b(\d+)\b", launched_result.stdout or "")
                launched_pid = int(launched_match.group(1)) if launched_match else None
                if launched_pid is None or launched_pid <= 0 or launched_pid == previous_pid:
                    raise DeviceError("iPogo did not return with a fresh process after the clean restart")
            except DeviceError as error:
                with self.lock:
                    self._status["ipogoRestartLastError"] = str(error)
                raise
        with self.lock:
            self._status.update({
                "ipogoLastRestartAt": self._now(),
                "ipogoLastRestartPid": launched_pid,
                "ipogoRestartCount": int(self._status.get("ipogoRestartCount") or 0) + 1,
                "ipogoRestartLastError": None,
                "ipogoRestartMethod": "coredevice-clean-launch",
                "phoneLastError": None,
            })
        result_status = self.status()
        result_status["preservedLocationProcessPid"] = route_pid
        return result_status

    def _validate_location_request(self, latitude: float, longitude: float) -> None:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise DeviceError("Target coordinates are outside the valid GPS range")
        if not self.executable:
            raise DeviceError("pymobiledevice3 is not installed")

    def _activate_route(
        self,
        latitude: float,
        longitude: float,
        route_path: Path,
        *,
        delivery: str,
        movement_mode: str,
        radius_meters: float | None = None,
        speed_kmh: float | None = None,
    ) -> dict[str, Any]:
        try:
            udid = self._connected_udid()
        except DeviceError:
            route_path.unlink(missing_ok=True)
            raise
        with self.location_lock:
            self._stop_location_process()
            self._stop_orphaned_location_processes(udid)
            failures: list[str] = []
            process: subprocess.Popen[str] | None = None
            tunnel_mode: str | None = None
            for candidate_mode in (("native",) if self.status().get("phoneNativeWifi") else ("shared", "userspace")):
                tunnel_arguments = (
                    ["--tunnel", udid]
                    if candidate_mode == "shared"
                    else ["--userspace", "--udid", udid]
                )
                command = [
                    self.executable, "developer", "dvt", "simulate-location", "play",
                    *tunnel_arguments, str(route_path),
                ]
                command = self.transport_command(command)
                try:
                    candidate = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                except FileNotFoundError as error:
                    raise DeviceError("pymobiledevice3 is not installed") from error

                # A playing GPX only reaches this line after the first DVT
                # update succeeds. This also gives iPogo a fresh event every
                # second instead of relying on one cached static coordinate.
                output: list[str] = []
                ready = False
                deadline = time.monotonic() + 15
                while candidate.poll() is None and time.monotonic() < deadline:
                    if candidate.stdout is None:
                        break
                    readable, _, _ = select.select([candidate.stdout], [], [], 0.2)
                    if not readable:
                        continue
                    line = candidate.stdout.readline()
                    if not line:
                        continue
                    output.append(line.strip())
                    if "set location to" in line:
                        ready = True
                        break
                if ready:
                    process = candidate
                    tunnel_mode = candidate_mode
                    break

                candidate.terminate()
                try:
                    candidate.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    candidate.kill()
                    candidate.wait(timeout=2)
                if candidate.stdout:
                    output.extend(line.strip() for line in candidate.stdout.readlines())
                    candidate.stdout.close()
                failures.append(f"{candidate_mode}: {' '.join(output[-4:]) or 'timed out'}")

            if process is None or tunnel_mode is None:
                route_path.unlink(missing_ok=True)
                raise DeviceError("The iPhone rejected the simulated location (" + "; ".join(failures) + ")")
            self.location_process = process
            self.location_route_path = route_path
            self.location_output_thread = threading.Thread(
                target=self._drain_location_output,
                args=(process,),
                name="iphone-location-output",
                daemon=True,
            )
            self.location_output_thread.start()
        location = {
            "latitude": latitude,
            "longitude": longitude,
            "setAt": self._now(),
        }
        with self.lock:
            self._status.update({
                "phoneConnected": True,
                "phoneLastError": None,
                "phoneSimulatedLocation": location,
                "phoneTunnelMode": tunnel_mode,
                "phoneLocationDelivery": delivery,
                "phoneMovementMode": movement_mode,
                "phoneMovementRadiusMeters": radius_meters,
                "phoneMovementSpeedKmh": speed_kmh,
            })
        return {**self.status(), "location": location}

    @staticmethod
    def _write_stationary_route(latitude: float, longitude: float) -> Path:
        descriptor, raw_path = tempfile.mkstemp(prefix="shundo-hunter-location-", suffix=".gpx")
        os.close(descriptor)
        path = Path(raw_path)
        started = datetime.now(timezone.utc).replace(microsecond=0)
        with path.open("w", encoding="utf-8") as output:
            output.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            output.write('<gpx version="1.1" creator="Shundo Hunter" xmlns="http://www.topografix.com/GPX/1/1">\n')
            output.write('  <trk><name>Continuous stationary location</name><trkseg>\n')
            for second in range(DeviceController.ROUTE_DURATION_SECONDS + 1):
                timestamp = (started + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")
                output.write(
                    f'    <trkpt lat="{latitude:.8f}" lon="{longitude:.8f}"><time>{timestamp}</time></trkpt>\n'
                )
            output.write('  </trkseg></trk>\n</gpx>\n')
        return path

    @staticmethod
    def _destination(
        latitude: float,
        longitude: float,
        distance_meters: float,
        bearing_radians: float,
    ) -> tuple[float, float]:
        """Return a point at a distance and bearing on a spherical Earth."""
        earth_radius_meters = 6_371_008.8
        angular_distance = distance_meters / earth_radius_meters
        latitude_1 = math.radians(latitude)
        longitude_1 = math.radians(longitude)
        latitude_2 = math.asin(
            math.sin(latitude_1) * math.cos(angular_distance)
            + math.cos(latitude_1) * math.sin(angular_distance) * math.cos(bearing_radians)
        )
        longitude_2 = longitude_1 + math.atan2(
            math.sin(bearing_radians) * math.sin(angular_distance) * math.cos(latitude_1),
            math.cos(angular_distance) - math.sin(latitude_1) * math.sin(latitude_2),
        )
        normalized_longitude = (math.degrees(longitude_2) + 540) % 360 - 180
        return math.degrees(latitude_2), normalized_longitude

    @staticmethod
    def _write_walking_route(
        latitude: float,
        longitude: float,
        *,
        radius_meters: float = 20.0,
        speed_kmh: float = 5.0,
        duration_seconds: int | None = None,
    ) -> Path:
        """Create a 1 Hz route that eases from the target into a tight circle."""
        if radius_meters <= 0 or speed_kmh <= 0:
            raise DeviceError("Walking radius and speed must be positive")
        duration = (
            DeviceController.ROUTE_DURATION_SECONDS
            if duration_seconds is None
            else max(1, int(duration_seconds))
        )
        speed_meters_per_second = speed_kmh / 3.6
        ramp_seconds = max(1, math.ceil(radius_meters / speed_meters_per_second))
        angular_step = speed_meters_per_second / radius_meters
        descriptor, raw_path = tempfile.mkstemp(prefix="shundo-hunter-walk-", suffix=".gpx")
        os.close(descriptor)
        path = Path(raw_path)
        started = datetime.now(timezone.utc).replace(microsecond=0)
        with path.open("w", encoding="utf-8") as output:
            output.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            output.write('<gpx version="1.1" creator="Shundo Hunter" xmlns="http://www.topografix.com/GPX/1/1">\n')
            output.write('  <trk><name>Hunt walking circle</name><trkseg>\n')
            for second in range(duration + 1):
                if second == 0:
                    point_latitude, point_longitude = latitude, longitude
                elif second <= ramp_seconds:
                    distance = min(radius_meters, second * speed_meters_per_second)
                    point_latitude, point_longitude = DeviceController._destination(
                        latitude, longitude, distance, 0.0
                    )
                else:
                    bearing = (second - ramp_seconds) * angular_step
                    point_latitude, point_longitude = DeviceController._destination(
                        latitude, longitude, radius_meters, bearing
                    )
                timestamp = (started + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")
                output.write(
                    f'    <trkpt lat="{point_latitude:.8f}" lon="{point_longitude:.8f}"><time>{timestamp}</time></trkpt>\n'
                )
            output.write('  </trkseg></trk>\n</gpx>\n')
        return path

    @staticmethod
    def _drain_location_output(process: subprocess.Popen[str]) -> None:
        try:
            if process.stdout is not None:
                for _ in process.stdout:
                    pass
        except (OSError, ValueError):
            pass

    def _stop_location_process(self) -> None:
        process = self.location_process
        self.location_process = None
        route_path = self.location_route_path
        self.location_route_path = None
        try:
            if process is not None and process.poll() is None:
                # pymobiledevice3 waits for SIGINT/SIGTERM, not stdin. SIGTERM
                # lets its context managers close the DVT session cleanly.
                process.terminate()
                process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            if process is not None:
                process.kill()
                process.wait(timeout=2)
        finally:
            if process is not None and process.stdout:
                process.stdout.close()
            if route_path is not None:
                route_path.unlink(missing_ok=True)

    @staticmethod
    def _orphan_location_worker_pids(
        process_table: str,
        udid: str,
        excluded_pid: int | None = None,
    ) -> list[int]:
        """Find only this app's stale GPX players for the selected iPhone."""
        matches: list[int] = []
        for raw_line in process_table.splitlines():
            fields = raw_line.strip().split(maxsplit=1)
            if len(fields) != 2:
                continue
            try:
                pid = int(fields[0])
            except ValueError:
                continue
            command = fields[1]
            if pid == excluded_pid:
                continue
            if not any(prefix in command for prefix in (
                "pymobiledevice3 developer dvt simulate-location play",
                "shundo_hunter.native_wifi developer dvt simulate-location play",
            )):
                continue
            if "/shundo-hunter-walk-" not in command and "/shundo-hunter-location-" not in command:
                continue
            if f"--tunnel {udid}" not in command and f"--udid {udid}" not in command:
                continue
            matches.append(pid)
        return matches

    def _stop_orphaned_location_processes(self, udid: str) -> None:
        """Terminate location players left behind by an interrupted app exit."""
        excluded_pid = self.location_process.pid if self.location_process else None
        try:
            result = subprocess.run(
                ["/bin/ps", "-axo", "pid=,command="],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return
        pids = self._orphan_location_worker_pids(result.stdout, udid, excluded_pid)
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.monotonic() + 3
        remaining = set(pids)
        while remaining and time.monotonic() < deadline:
            for pid in tuple(remaining):
                try:
                    os.kill(pid, 0)
                except (ProcessLookupError, PermissionError):
                    remaining.discard(pid)
            if remaining:
                time.sleep(0.05)
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def clear_location(self) -> dict[str, Any]:
        if not self.executable:
            raise DeviceError("pymobiledevice3 is not installed")
        udid = self._connected_udid()
        with self.location_lock:
            self._stop_location_process()
            self._stop_orphaned_location_processes(udid)
            current_mode = self.status().get("phoneTunnelMode")
            modes = [current_mode] if current_mode in ("shared", "userspace") else []
            modes.extend(mode for mode in ("shared", "userspace") if mode not in modes)
            last_error: DeviceError | None = None
            for mode in modes:
                tunnel_arguments = ["--tunnel", udid] if mode == "shared" else ["--userspace", "--udid", udid]
                command = [
                    self.executable,
                    "developer", "dvt", "simulate-location", "clear",
                    *tunnel_arguments,
                ]
                try:
                    self._run(command, timeout=45)
                    last_error = None
                    break
                except DeviceError as error:
                    last_error = error
            if last_error is not None:
                raise last_error
        with self.lock:
            self._status.update({
                "phoneConnected": True,
                "phoneLastError": None,
                "phoneSimulatedLocation": None,
                "phoneTunnelMode": None,
                "phoneLocationDelivery": None,
                "phoneMovementMode": None,
                "phoneMovementRadiusMeters": None,
                "phoneMovementSpeedKmh": None,
            })
        return self.status()

    def _monitor(self) -> None:
        while not self.stop_event.is_set():
            self.refresh()
            with self.location_lock:
                process = self.location_process
                if process is not None and process.poll() is not None:
                    self._stop_location_process()
                    with self.lock:
                        self._status.update({
                            "phoneLastError": "The simulated-location session ended unexpectedly",
                            "phoneSimulatedLocation": None,
                            "phoneTunnelMode": None,
                            "phoneLocationDelivery": None,
                            "phoneMovementMode": None,
                            "phoneMovementRadiusMeters": None,
                            "phoneMovementSpeedKmh": None,
                        })
            self.stop_event.wait(self.poll_interval)

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1.5)
        try:
            self.clear_location()
        except DeviceError:
            with self.location_lock:
                self._stop_location_process()

import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ElementTree

from shundo_hunter.device_service import DeviceController, DeviceError


def distance_meters(first: tuple[float, float], second: tuple[float, float]) -> float:
    earth_radius = 6_371_008.8
    first_latitude, first_longitude = map(math.radians, first)
    second_latitude, second_longitude = map(math.radians, second)
    latitude_delta = second_latitude - first_latitude
    longitude_delta = second_longitude - first_longitude
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_latitude)
        * math.cos(second_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * earth_radius * math.asin(math.sqrt(haversine))


class WalkingRouteTests(unittest.TestCase):
    def test_finds_user_pipx_tool_when_finder_path_is_minimal(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            executable = home / ".local/bin/pymobiledevice3"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with patch("shundo_hunter.device_service.shutil.which", return_value=None):
                self.assertEqual(
                    DeviceController._find_pymobiledevice3(home),
                    str(executable),
                )

    def test_restart_ipogo_preserves_the_active_location_process(self):
        controller = object.__new__(DeviceController)
        controller.executable = "/opt/pymobiledevice3"
        controller.xcrun_executable = "/usr/bin/xcrun"
        controller.ipogo_restart_delay_seconds = 0
        controller.lock = __import__("threading").Lock()
        controller.location_lock = __import__("threading").Lock()
        controller._status = {
            "phoneConnected": True,
            "phoneUdid": "phone-a",
            "phoneSimulatedLocation": {"latitude": 40.7, "longitude": -111.9},
            "phoneTunnelMode": "shared",
            "ipogoRestartCount": 0,
        }
        controller._connected_udid = Mock(return_value="phone-a")
        route_process = Mock(pid=4321)
        route_process.poll.return_value = None
        controller.location_process = route_process
        controller._run = Mock(side_effect=[
            Mock(stdout="3456\n"),
            Mock(stdout="Sent signal to terminate process sent to pid 3456"),
            Mock(stdout="Launched application with com.nianticlabs.pokemongo bundle identifier."),
            Mock(stdout="9876\n"),
        ])

        status = controller.restart_ipogo()

        self.assertEqual(controller._run.call_args_list[0].args[0], [
            "/opt/pymobiledevice3", "developer", "dvt", "process-id-for-bundle-id",
            "--tunnel", "phone-a", "com.nianticlabs.pokemongo",
        ])
        self.assertEqual(controller._run.call_args_list[1].args[0], [
            "/usr/bin/xcrun", "devicectl", "device", "process", "terminate",
            "--device", "phone-a", "--pid", "3456", "--kill",
        ])
        self.assertEqual(controller._run.call_args_list[2].args[0], [
            "/usr/bin/xcrun", "devicectl", "device", "process", "launch",
            "--device", "phone-a", "--activate", "com.nianticlabs.pokemongo",
        ])
        self.assertIs(controller.location_process, route_process)
        self.assertEqual(status["preservedLocationProcessPid"], 4321)
        self.assertEqual(status["ipogoLastRestartPid"], 9876)
        self.assertEqual(status["ipogoRestartCount"], 1)
        self.assertEqual(status["ipogoRestartMethod"], "coredevice-clean-launch")

    def test_restart_ipogo_refuses_to_expose_real_location(self):
        controller = object.__new__(DeviceController)
        controller.executable = "/opt/pymobiledevice3"
        controller.xcrun_executable = "/usr/bin/xcrun"
        controller.lock = __import__("threading").Lock()
        controller.location_lock = __import__("threading").Lock()
        controller._status = {"phoneConnected": True, "phoneUdid": "phone-a"}
        controller._connected_udid = Mock(return_value="phone-a")
        controller.location_process = None

        with self.assertRaisesRegex(DeviceError, "actively streaming"):
            controller.restart_ipogo()

    def test_runtime_verifier_accepts_exact_install_receipt(self):
        controller = object.__new__(DeviceController)
        controller.executable = "/opt/pymobiledevice3"
        controller.lock = __import__("threading").Lock()
        controller._status = {
            "phoneConnected": True,
            "phoneUdid": "phone-a",
        }
        controller._connected_udid = Mock(return_value="phone-a")
        controller._run = Mock(return_value=Mock(stdout='{"com.nianticlabs.pokemongo":{"CFBundleVersion":"0","ShundoSpawnRuntimeVersion":"8","Path":"/app/a","SequenceNumber":9}}'))
        receipt = {
            "bundleId": "com.nianticlabs.pokemongo",
            "bundlePath": "/app/a",
            "deviceUdid": "phone-a",
            "ipaSha256": DeviceController.SUPPORTED_SPAWN_RUNTIME_IPA_SHA256,
            "runtimeBuild": DeviceController.SUPPORTED_SPAWN_RUNTIME_BUILD,
            "runtimeVersion": DeviceController.SUPPORTED_SPAWN_RUNTIME_VERSION,
            "sequenceNumber": 9,
        }
        from unittest.mock import patch
        with patch("pathlib.Path.read_text", return_value=__import__("json").dumps(receipt)):
            status = controller.verify_ipogo_runtime()

        self.assertTrue(status["ipogoSpawnRuntimeVerified"])
        self.assertEqual(
            status["ipogoSpawnRuntimeVersion"],
            DeviceController.SUPPORTED_SPAWN_RUNTIME_VERSION,
        )

    def test_runtime_verifier_rejects_an_unmarked_ipogo(self):
        controller = object.__new__(DeviceController)
        controller.executable = "/opt/pymobiledevice3"
        controller.lock = __import__("threading").Lock()
        controller._status = {
            "phoneConnected": True,
            "phoneUdid": "phone-a",
        }
        controller._connected_udid = Mock(return_value="phone-a")
        controller._run = Mock(return_value=Mock(stdout='{"com.nianticlabs.pokemongo":{}}'))

        with self.assertRaisesRegex(DeviceError, "receipt"):
            controller.verify_ipogo_runtime()

        self.assertFalse(controller.status()["ipogoSpawnRuntimeVerified"])

    def test_runtime_verifier_accepts_and_refreshes_volatile_receipt_sequence(self):
        controller = object.__new__(DeviceController)
        controller.executable = "/opt/pymobiledevice3"
        controller.lock = __import__("threading").Lock()
        controller._status = {"phoneConnected": True, "phoneUdid": "phone-a"}
        controller._connected_udid = Mock(return_value="phone-a")
        controller._run = Mock(return_value=Mock(stdout='{"com.nianticlabs.pokemongo":{"CFBundleVersion":"0","ShundoSpawnRuntimeVersion":"8","Path":"/app/a","SequenceNumber":10}}'))
        receipt = {
            "bundleId": "com.nianticlabs.pokemongo",
            "bundlePath": "/app/a",
            "deviceUdid": "phone-a",
            "ipaSha256": DeviceController.SUPPORTED_SPAWN_RUNTIME_IPA_SHA256,
            "runtimeBuild": DeviceController.SUPPORTED_SPAWN_RUNTIME_BUILD,
            "runtimeVersion": DeviceController.SUPPORTED_SPAWN_RUNTIME_VERSION,
            "sequenceNumber": 9,
        }
        from unittest.mock import patch
        with patch("pathlib.Path.read_text", return_value=__import__("json").dumps(receipt)), patch.object(
            DeviceController,
            "_refresh_runtime_receipt_sequence",
        ) as refresh_sequence:
            status = controller.verify_ipogo_runtime()

        self.assertTrue(status["ipogoSpawnRuntimeVerified"])
        refresh_sequence.assert_called_once()
        self.assertEqual(refresh_sequence.call_args.args[2], 10)

    def test_only_finds_stale_hunter_routes_for_the_same_phone(self):
        process_table = """
        101 /opt/python pymobiledevice3 developer dvt simulate-location play --tunnel phone-a /tmp/shundo-hunter-walk-one.gpx
        102 /opt/python pymobiledevice3 developer dvt simulate-location play --userspace --udid phone-a /tmp/shundo-hunter-location-two.gpx
        103 /opt/python pymobiledevice3 developer dvt simulate-location play --tunnel phone-b /tmp/shundo-hunter-walk-other.gpx
        104 /opt/python pymobiledevice3 developer dvt simulate-location play --tunnel phone-a /tmp/unrelated.gpx
        105 /usr/bin/something-else
        """

        self.assertEqual(
            DeviceController._orphan_location_worker_pids(process_table, "phone-a"),
            [101, 102],
        )
        self.assertEqual(
            DeviceController._orphan_location_worker_pids(process_table, "phone-a", 101),
            [102],
        )

    def test_hunt_location_activates_the_walking_route(self):
        controller = object.__new__(DeviceController)
        controller._validate_location_request = Mock()
        controller._write_walking_route = Mock(return_value=Path("/tmp/test-walk.gpx"))
        controller._activate_route = Mock(return_value={"phoneLocationDelivery": "walking-loop-1hz"})

        result = controller.set_hunt_location(40.7608, -111.8910)

        self.assertEqual(result["phoneLocationDelivery"], "walking-loop-1hz")
        controller._activate_route.assert_called_once_with(
            40.7608,
            -111.8910,
            Path("/tmp/test-walk.gpx"),
            delivery="walking-loop-1hz",
            movement_mode="walking-circle",
            radius_meters=20.0,
            speed_kmh=10.0,
        )

    def test_route_starts_on_target_then_walks_a_twenty_meter_circle(self):
        center = (40.7608, -111.8910)
        route_path = DeviceController._write_walking_route(
            *center,
            radius_meters=20,
            speed_kmh=5,
            duration_seconds=110,
        )
        self.addCleanup(Path(route_path).unlink, missing_ok=True)

        root = ElementTree.parse(route_path).getroot()
        namespace = {"gpx": "http://www.topografix.com/GPX/1/1"}
        trackpoints = root.findall(".//gpx:trkpt", namespace)
        points = [
            (float(point.attrib["lat"]), float(point.attrib["lon"]))
            for point in trackpoints
        ]
        timestamps = [point.findtext("gpx:time", namespaces=namespace) for point in trackpoints]

        self.assertEqual(len(points), 111)
        self.assertLess(distance_meters(center, points[0]), 0.01)
        radii = [distance_meters(center, point) for point in points]
        self.assertTrue(all(radius <= 20.02 for radius in radii))
        self.assertTrue(all(19.97 <= radius <= 20.02 for radius in radii[15:]))
        walking_steps = [
            distance_meters(points[index - 1], points[index])
            for index in range(16, len(points))
        ]
        self.assertTrue(all(1.35 <= step <= 1.42 for step in walking_steps))
        self.assertEqual(len(timestamps), len(set(timestamps)))

    def test_route_rejects_non_positive_movement(self):
        with self.assertRaisesRegex(DeviceError, "positive"):
            DeviceController._write_walking_route(0, 0, radius_meters=0, duration_seconds=1)


if __name__ == "__main__":
    unittest.main()

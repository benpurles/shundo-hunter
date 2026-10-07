import json
import threading
import unittest
from unittest.mock import Mock, patch

from shundo_hunter.device_service import DeviceController
from shundo_hunter.native_wifi import route


class NativeWifiTests(unittest.TestCase):
    def test_only_transport_arguments_change(self):
        with patch("shundo_hunter.native_wifi.command", side_effect=lambda exe, args: args):
            self.assertEqual(route("pmd", ["developer", "dvt", "simulate-location", "play", "--tunnel", "phone", "/tmp/route.gpx"]),
                             ["developer", "dvt", "simulate-location", "play", "--native", "--udid", "phone", "/tmp/route.gpx"])

    def test_usb_command_unchanged(self):
        device = object.__new__(DeviceController)
        device.executable = "pmd"
        device.lock = threading.Lock()
        device._status = {"phoneNativeWifi": False}
        command = ["pmd", "apps", "list", "--udid", "phone"]
        self.assertEqual(device.transport_command(command), command)

    def test_pinned_native_discovery_when_usbmux_empty(self):
        device = object.__new__(DeviceController)
        device.executable = "pmd"
        device.lock = threading.Lock()
        device._status = {}
        device._selected_udid = "phone"
        device._run = Mock(return_value=Mock(stdout="[]"))
        device._native_discover = Mock(return_value={"UniqueDeviceID": "phone", "ConnectionType": "Network", "HunterNativeWifi": True})
        status = device.refresh()
        self.assertTrue(status["phoneConnected"])
        self.assertTrue(status["phoneNativeWifi"])
        device._native_discover.assert_called_once_with("phone")

    def test_native_orphan_match_stays_device_and_route_scoped(self):
        rows = "1 python -m shundo_hunter.native_wifi developer dvt simulate-location play --native --udid phone /tmp/shundo-hunter-walk-test.gpx\n2 python -m shundo_hunter.native_wifi developer dvt simulate-location play --native --udid other /tmp/shundo-hunter-walk-test.gpx\n3 python -m shundo_hunter.native_wifi developer dvt simulate-location play --native --udid phone /tmp/other.gpx"
        self.assertEqual(DeviceController._orphan_location_worker_pids(rows, "phone"), [1])

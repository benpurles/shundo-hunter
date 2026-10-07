import json
import threading
import unittest
from unittest.mock import Mock

from shundo_hunter.device_service import DeviceController, DeviceError


def phone(udid="phone-a", transport="Network"):
    return {"UniqueDeviceID": udid, "ConnectionType": transport,
            "DeviceClass": "iPhone", "DeviceName": "Test phone"}


class WirelessDeviceTests(unittest.TestCase):
    def controller(self, devices, selected=None):
        controller = object.__new__(DeviceController)
        controller.executable = "/pymobiledevice3"
        controller.lock = threading.Lock()
        controller._status = {}
        controller._selected_udid = selected
        controller._run = Mock(return_value=Mock(stdout=json.dumps(devices)))
        return controller

    def test_network_only_phone_is_connected(self):
        result = self.controller([phone()]).refresh()
        self.assertTrue(result["phoneConnected"])
        self.assertEqual(result["phoneConnectionType"], "Network")

    def test_same_phone_prefers_usb_when_both_transports_exist(self):
        result = self.controller([phone(), phone(transport="USB")]).refresh()
        self.assertEqual(result["phoneConnectionType"], "USB")

    def test_selected_network_phone_wins_over_other_usb_phone(self):
        result = self.controller([phone("other", "USB"), phone()], "phone-a").refresh()
        self.assertEqual(result["phoneUdid"], "phone-a")

    def test_disconnect_does_not_switch_to_other_phone(self):
        controller = self.controller([phone()])
        controller.refresh()
        controller._run.return_value.stdout = json.dumps([phone("other", "USB")])
        self.assertFalse(controller.refresh()["phoneConnected"])
        self.assertFalse(controller.refresh()["phoneConnected"])
        controller._run.return_value.stdout = json.dumps([phone()])
        self.assertTrue(controller.refresh()["phoneConnected"])

    def test_unbound_multiple_phones_require_disambiguation(self):
        result = self.controller([phone(), phone("other")]).refresh()
        self.assertFalse(result["phoneConnected"])
        self.assertIn("Multiple", result["phoneLastError"])

    def test_unknown_transport_or_tablet_is_not_selected(self):
        tablet = dict(phone(), DeviceClass="iPad")
        result = self.controller([phone(transport="Other"), tablet]).refresh()
        self.assertFalse(result["phoneConnected"])

    def test_invalid_device_list_is_clear_failure(self):
        result = self.controller({"unexpected": True}).refresh()
        self.assertFalse(result["phoneConnected"])
        self.assertIn("invalid device list", result["phoneLastError"])

    def test_enable_wifi_is_verified_and_scoped_to_selected_phone(self):
        controller = self.controller([phone()])
        controller._connected_udid = Mock(return_value="phone-a")
        controller._run.side_effect = [Mock(stdout="{}"),
                                      Mock(stdout='{"EnableWifiConnections": true}'),
                                      Mock(stdout=json.dumps([phone()]))]
        self.assertTrue(controller.enable_wifi()["phoneConnected"])
        self.assertEqual(controller._run.call_args_list[0].args[0], [
            "/pymobiledevice3", "lockdown", "wifi-connections", "--udid", "phone-a", "--state", "on"])

    def test_enable_wifi_does_not_claim_success_without_readback(self):
        controller = self.controller([])
        controller._connected_udid = Mock(return_value="phone-a")
        controller._run.side_effect = [Mock(stdout="{}"), Mock(stdout="{}")]
        with self.assertRaisesRegex(DeviceError, "could not be verified"):
            controller.enable_wifi()

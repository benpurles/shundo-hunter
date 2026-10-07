import socket

from pymobiledevice3.usbmux import PlistMuxConnection


def test_plist_mux_ignores_paired_message() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        mux = PlistMuxConnection(sock)
        mux._process_device_state({"DeviceID": 28, "MessageType": "Paired"})
        assert mux.devices == []
    finally:
        sock.close()

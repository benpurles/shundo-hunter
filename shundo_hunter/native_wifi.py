"""Isolated native Apple Wi-Fi transport; never replaces the USB dependency."""
import asyncio
import json
from pathlib import Path
import sys


def runtime_root():
    root = Path(__file__).resolve().parent.parent
    for candidate in (root / "wifi-runtime", root / "build/wifi-runtime"):
        if (candidate / "pymobiledevice3-master/pymobiledevice3").is_dir():
            return candidate
    raise RuntimeError("Wireless runtime is not bundled. Reconnect USB.")


def command(executable, arguments):
    python = Path(executable).resolve().parent / "python"
    if not python.is_file():
        raise RuntimeError("Wireless transport needs pymobiledevice3's Python environment")
    return [str(python), "-m", "shundo_hunter.native_wifi", *arguments]


def route(executable, arguments):
    args = list(arguments)
    if "--userspace" in args:
        args.remove("--userspace")
    if "--tunnel" in args:
        args[args.index("--tunnel")] = "--udid"
    # Options belong to the leaf CLI command, before the already-present UDID.
    if "--native" not in args:
        args.insert(args.index("--udid"), "--native")
    return command(executable, args)


async def discover(udid):
    from pymobiledevice3.remote.native_tunnel import NativeRemotedTunnel
    async with NativeRemotedTunnel(serial=udid) as rsd:
        if rsd.udid != udid:
            raise RuntimeError("Native tunnel returned a different iPhone")
        props = rsd.peer_info.get("Properties", {})
        # Explicit allowlist: never serialize pairing metadata or host keys.
        return {"UniqueDeviceID": udid, "DeviceName": props.get("DeviceName", "Paired iPhone"),
                "ProductVersion": props.get("OSVersion"), "DeviceClass": "iPhone",
                "ConnectionType": "Network", "HunterNativeWifi": True}


def main():
    root = runtime_root()
    sys.path[:0] = [str(root / "pymobiledevice3-master"), str(root / "dependencies")]
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "discover":
        try:
            result = asyncio.run(asyncio.wait_for(discover(args[1]), 10))
            print(json.dumps(result))
        except Exception:
            print("null")
        return
    from pymobiledevice3.__main__ import app
    sys.argv = ["pymobiledevice3", *args]
    app(standalone_mode=False)


if __name__ == "__main__":
    main()

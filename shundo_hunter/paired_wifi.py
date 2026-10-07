"""Paired Wi-Fi fallback for macOS hosts whose usbmux list omits network phones.

Run with pymobiledevice3's own Python. Existing pairing credentials stay in
memory, never in app logs or a second on-disk credential store.
"""
import argparse
import asyncio
import ipaddress
import json
import sys


async def connect(address, udid):
    from pymobiledevice3.lockdown import create_using_tcp
    from pymobiledevice3.pair_records import get_usbmux_pairing_record
    record = await get_usbmux_pairing_record(udid)
    if not record:
        raise RuntimeError("No existing pairing record for the selected iPhone. Pair over USB first.")
    device = await asyncio.wait_for(create_using_tcp(address, identifier=udid, pair_record=record, autopair=False), 8)
    if not device.paired or device.udid != udid:
        await device.close()
        raise RuntimeError("Wi-Fi peer did not authenticate as the selected iPhone")
    return device


async def discover(udid):
    from pymobiledevice3.bonjour import browse_mobdev2
    from pymobiledevice3.pair_records import get_usbmux_pairing_record
    record = await get_usbmux_pairing_record(udid)
    if not record:
        return None
    visited = set()
    for answer in await browse_mobdev2(timeout=4):
        # New iOS advertises an opaque supportsRP name, not a Wi-Fi MAC.
        # The existing pair record + UDID check, not Bonjour text, is authority.
        for address in answer.addresses:
            # Prefer the local IPv4 address; do not connect to advertised global addresses.
            try:
                ip = ipaddress.ip_address(address.full_ip)
                if ip.version != 4 or not ip.is_private or ip.is_loopback:
                    continue
                if str(ip) in visited or len(visited) >= 8:
                    continue
                visited.add(str(ip))
                device = await connect(str(ip), udid)
                result = dict(device.short_info, ConnectionType="Network", HunterWifiAddress=str(ip))
                await device.close()
                return result
            except (OSError, RuntimeError, asyncio.TimeoutError):
                continue
    return None


async def forward(address, udid):
    # Authenticate before listening and for each new connection. Never proxy to
    # a stale DHCP address without first proving the expected device identity.
    device = await connect(address, udid)
    await device.close()
    async def client(reader, writer):
        remote_writer = None
        try:
            device = await connect(address, udid)
            await device.close()
            remote_reader, remote_writer = await asyncio.wait_for(asyncio.open_connection(address, 8100), 5)
            async def pump(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()
            tasks = [asyncio.create_task(pump(reader, remote_writer)), asyncio.create_task(pump(remote_reader, writer))]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, RuntimeError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            if remote_writer:
                remote_writer.close()
    server = await asyncio.start_server(client, "127.0.0.1", 18100)
    async with server:
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--udid", required=True)
    parser.add_argument("--address")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--forward", action="store_true")
    args = parser.parse_args()
    if args.discover:
        print(json.dumps(asyncio.run(discover(args.udid))))
        return
    if not args.address:
        async def retry_discovery():
            for _ in range(3):
                result = await discover(args.udid)
                if result:
                    return result
            return None
        device = asyncio.run(retry_discovery())
        if not device:
            parser.error("Selected paired iPhone is not reachable over local Wi-Fi")
        args.address = device["HunterWifiAddress"]
    ip = ipaddress.ip_address(args.address)
    if not ip.is_private or ip.is_loopback:
        parser.error("A private local iPhone address is required")
    if args.forward:
        asyncio.run(forward(args.address, args.udid))
        return
    parser.error("Choose --discover or --forward")


if __name__ == "__main__":
    main()

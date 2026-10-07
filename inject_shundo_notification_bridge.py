#!/usr/bin/env python3
"""Add the local Shundo notification logger to the spawn-compatible iPogo IPA.

The notification build must retain the patch that makes
CLLocationSourceInformation.isSimulatedBySoftware return false. Refuse older
experiments (including the sourceInformation=nil build) so a notification
change cannot silently reintroduce the external-location/no-spawns failure.
"""

from __future__ import annotations

import argparse
import plistlib
import struct
import subprocess
import tempfile
from pathlib import Path

from patch_ipogo_simulated_flag import (
    BINARY_RELATIVE_PATH as SPAWN_PATCH_BINARY,
    verify_patched_binary as verify_spawn_patch,
)


APP = Path("Payload/PokmonGO.app")
FRAMEWORK = APP / "Frameworks/ShundoBridge.framework"
LOAD_PATH = "@rpath/ShundoBridge.framework/ShundoBridge"
LC_SEGMENT_64 = 0x19
LC_LOAD_DYLIB = 0xC
MH_MAGIC_64 = 0xFEEDFACF


def run(*arguments: str) -> None:
    subprocess.run(arguments, check=True)


def add_load_command(path: Path) -> None:
    data = bytearray(path.read_bytes())
    if len(data) < 32:
        raise RuntimeError("The app executable is not a valid 64-bit Mach-O")
    magic, = struct.unpack_from("<I", data, 0)
    if magic != MH_MAGIC_64:
        raise RuntimeError(f"Unsupported Mach-O magic: 0x{magic:08x}")
    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    command_offset = 32
    first_section_offset = len(data)
    existing_paths: list[str] = []

    for _ in range(ncmds):
        command, command_size = struct.unpack_from("<II", data, command_offset)
        if command_size < 8 or command_offset + command_size > len(data):
            raise RuntimeError("Malformed Mach-O load command")
        if command == LC_SEGMENT_64:
            section_count, = struct.unpack_from("<I", data, command_offset + 64)
            section_offset = command_offset + 72
            for index in range(section_count):
                file_offset, = struct.unpack_from("<I", data, section_offset + index * 80 + 48)
                if file_offset:
                    first_section_offset = min(first_section_offset, file_offset)
        if command == LC_LOAD_DYLIB:
            name_offset, = struct.unpack_from("<I", data, command_offset + 8)
            start = command_offset + name_offset
            end = data.find(0, start, command_offset + command_size)
            if end != -1:
                existing_paths.append(bytes(data[start:end]).decode("utf-8", "replace"))
        command_offset += command_size

    if LOAD_PATH in existing_paths:
        raise RuntimeError("The Shundo notification bridge is already injected")
    commands_end = 32 + sizeofcmds
    name = LOAD_PATH.encode() + b"\0"
    command_size = (24 + len(name) + 7) & ~7
    if commands_end + command_size > first_section_offset:
        raise RuntimeError("The app executable has insufficient Mach-O header padding")

    command = bytearray(command_size)
    struct.pack_into("<IIIIII", command, 0, LC_LOAD_DYLIB, command_size, 24, 0, 0x10000, 0x10000)
    command[24:24 + len(name)] = name
    data[commands_end:commands_end + command_size] = command
    struct.pack_into("<II", data, 16, ncmds + 1, sizeofcmds + command_size)
    path.write_bytes(data)


def build_framework(root: Path, source: Path) -> None:
    framework = root / FRAMEWORK
    framework.mkdir(parents=True)
    executable = framework / "ShundoBridge"
    sdk = subprocess.run(
        ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    run(
        "xcrun", "clang",
        "-isysroot", sdk,
        "-arch", "arm64",
        "-miphoneos-version-min=15.0",
        "-fobjc-arc",
        "-dynamiclib",
        "-framework", "Foundation",
        "-framework", "CoreLocation",
        "-framework", "UserNotifications",
        "-install_name", LOAD_PATH,
        str(source),
        "-o", str(executable),
    )
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": "ShundoBridge",
        "CFBundleIdentifier": "local.shundohunter.notificationbridge",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "ShundoBridge",
        "CFBundlePackageType": "FMWK",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "MinimumOSVersion": "15.0",
    }
    (framework / "Info.plist").write_bytes(plistlib.dumps(info))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).with_name("ShundoNotificationBridge.m"),
    )
    args = parser.parse_args()
    if args.output_ipa.exists():
        raise RuntimeError(f"Output already exists: {args.output_ipa}")
    if not args.source.is_file():
        raise RuntimeError(f"Bridge source does not exist: {args.source}")

    with tempfile.TemporaryDirectory(prefix="shundo-notification-bridge-") as temporary:
        root = Path(temporary)
        run("ditto", "-x", "-k", str(args.source_ipa), str(root))
        app = root / APP
        if not app.is_dir():
            raise RuntimeError("The IPA does not contain the expected iPogo app")
        try:
            verify_spawn_patch(root / SPAWN_PATCH_BINARY)
        except (OSError, RuntimeError) as error:
            raise RuntimeError(
                "Refusing notification build: the IPA does not contain the "
                "verified spawn-compatible simulated-source patch"
            ) from error
        build_framework(root, args.source)
        # Keep the game's main executable untouched. iPogo already uses the
        # FBLPromises framework as its injected-code host, so load the bridge
        # from that verified framework instead.
        add_load_command(root / SPAWN_PATCH_BINARY)
        args.output_ipa.parent.mkdir(parents=True, exist_ok=True)
        run(
            "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
            str(root / "Payload"), str(args.output_ipa),
        )

    print(f"Created unsigned notification-bridge IPA: {args.output_ipa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

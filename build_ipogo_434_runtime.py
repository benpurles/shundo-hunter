#!/usr/bin/env python3
"""Build and verify the Shundo Hunter runtime for pristine iPogo 4.3.4.

This is intentionally version locked. It ports only the three production
layers from the accepted 4.3.3 runtime: the external-location compatibility
mask, notification logging, and the read-only world-scan observer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

from build_ipogo_worldscan_runtime import (
    BRIDGE_RELEASE_MARKER,
    CLASS_ADD_MARKER,
    CLASS_ADRP_MARKER,
    CLASS_STRING,
    END_ACCESS_MARKER,
    FORMAT_ADD_MARKER,
    FORMAT_ADRP_MARKER,
    GYM_GETTER_MARKER,
    LOG_PREFIX,
    MH_MAGIC_64,
    NEARBY_GETTER_MARKER,
    NSLOG_MARKER,
    OBJC_GET_CLASS_MARKER,
    STOP_GETTER_MARKER,
    UTF8_MARKER,
    WILD_GETTER_MARKER,
    _compile_payload,
    _direct_target,
    _encode_add_immediate,
    _encode_adrp,
    _encode_branch,
    _find_unique_instruction,
    _put_instruction,
)
from patch_ipogo_shundo_runtime import NOTIFICATION_WRAPPER


SOURCE_IPA_SHA256 = "a5574b34848205fd6c16cde0fde39937f5ea696cd672a3e24134065d71710e29"
SOURCE_FBL_SHA256 = "22de7f64c519aca9548a8dc80008f8cc0c6904a89e25767d9f55d155e26ea92c"
BASE_IPOGO_LABEL = "4.3.4"
BASE_SHORT_VERSION = "0.421.1"

APP = Path("Payload/PokmonGO.app")
INFO_PLIST = APP / "Info.plist"
FBL = APP / "Frameworks/FBLPromises.framework/FBLPromises"

RUNTIME_VERSION = "4"
RUNTIME_BUILD = "worldscan-v3-ipogo434-20260806b"
WORLD_VERSION = "3"
# Preserve iPogo's base metadata exactly. The app's own update gate consumes
# this value; using an internal Hunter release number here produced the
# contradictory "Update to Continue" screen on the otherwise-current base.
BUNDLE_VERSION = "1"
SUPPORTED_DEVICE_ADDITIONS: tuple[str, ...] = ()

HOOK_OFFSET = 0x130224
EXPECTED_HOOK = bytes.fromhex(
    "8860009001c946f9a8600090156140f9e00313aaa9581b94200100b4f40300aa"
    "e00313aae10315aaa4581b94800000b4e10300aae00314aa90591b94"
)
PATCHED_HOOK = bytes.fromhex(
    "f40313aa603700f000002191cb591b94a8600090016140f9a8581b94e1ffffd0"
    "2100009198591b94f30314aa1f2003d51f2003d51f2003d51f2003d5"
)
CLASS_STRING_OFFSET = 0x81F840
EXPECTED_CLASS_STORAGE = b"Coordinates imported successfully.\0"
PATCHED_CLASS_STRING = b"CLLocationSourceInformation\0"
SELECTOR_STRING_OFFSET = 0x8213B0
EXPECTED_SELECTOR_STORAGE = b"Enter Speed in km/h (ex. 9)\0"
PATCHED_SELECTOR_STRING = b"isSimulatedBySoftware\0"
SELECTOR_REFERENCE_OFFSET = 0xD440C0
EXPECTED_SELECTOR_REFERENCE = struct.pack("<Q", 0xACB256)
PATCHED_SELECTOR_REFERENCE = struct.pack("<Q", SELECTOR_STRING_OFFSET)
FALSE_IMPLEMENTATION_OFFSET = 0x12E000
EXPECTED_FALSE_IMPLEMENTATION = bytes.fromhex("00008052c0035fd6")
SOURCE_INFORMATION_OFFSET = 0x132C3C
EXPECTED_SOURCE_INFORMATION_PROLOGUE = bytes.fromhex("fd7bbfa9fd030091")

STARTUP_CAVE_OFFSET = 0x139E74
STARTUP_CAVE_SIZE = 68
STARTUP_CAVE_EXPECTED = bytes.fromhex("200020d4" * 17)
STARTUP_WRAPPER = bytes.fromhex(
    "fd7bbfa9fd030091203700d000002191b6321b94000100b4486000f0016140f9"
    "92311b94800000b4a1ffffb02100009181321b94fd7bc1a8577d1714"
)
MOD_INIT_POINTER_OFFSET = 0xB9ECD8
EXPECTED_MOD_INIT_POINTER = struct.pack("<Q", 0x719408)
PATCHED_MOD_INIT_POINTER = struct.pack("<Q", STARTUP_CAVE_OFFSET)

NOTIFICATION_CALL_OFFSET = 0x2574F8
EXPECTED_NOTIFICATION_CALL = bytes.fromhex("28bd1694")
NOTIFICATION_CAVE_OFFSET = 0x674730
NOTIFICATION_CAVE_SIZE = 188
NOTIFICATION_CAVE_EXPECTED = bytes.fromhex("200020d4" * 47)
PATCHED_NOTIFICATION_CALL = struct.pack(
    "<I", _encode_branch(NOTIFICATION_CALL_OFFSET, NOTIFICATION_CAVE_OFFSET, link=True)
)

WORLD_CAVE = 0xB9A000
WORLD_CAVE_SIZE = 0x400
WORLD_CAVE_EXPECTED = b"\0" * WORLD_CAVE_SIZE
TEXT_INSTRUCTION_START = 0x4000
TEXT_INSTRUCTION_END = 0x804730
WORLD_HOOKS = (
    (0x25FF54, bytes.fromhex("7999ff17"), "nearby mutation completion"),
    (0x25FF58, bytes.fromhex("7899ff17"), "wild mutation completion"),
    (0x25FF5C, bytes.fromhex("7799ff17"), "gym mutation completion"),
    (0x25FF60, bytes.fromhex("7699ff17"), "PokeStop mutation completion"),
)

END_ACCESS = 0x806E60
WILD_GETTER = 0x2463CC
NEARBY_GETTER = 0x24630C
GYM_GETTER = 0x246550
STOP_GETTER = 0x246610
BRIDGE_RELEASE = 0x806DB8
OBJC_GET_CLASS = 0x80695C
MSG_SEND_STRING_WITH_UTF8 = 0x813728
NSLOG = 0x8060A4

FORMAT_STRING = b"SHUNDO_WORLD_SCAN_V3 wild=%llu nearby=%llu gyms=%llu stops=%llu\0"
FORBIDDEN_LOAD_PATH = b"@rpath/ShundoBridge.framework/ShundoBridge"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*arguments: str) -> None:
    subprocess.run(arguments, check=True)


def replace_exact(blob: bytearray, offset: int, expected: bytes, replacement: bytes) -> None:
    actual = bytes(blob[offset:offset + len(expected)])
    if actual != expected:
        raise RuntimeError(
            f"Refusing patch at 0x{offset:x}: expected {expected.hex()}, got {actual.hex()}"
        )
    if len(replacement) > len(expected):
        raise RuntimeError("Replacement is larger than its verified storage")
    blob[offset:offset + len(replacement)] = replacement


def verify_pristine_world_cave(binary: bytes) -> None:
    if binary[WORLD_CAVE:WORLD_CAVE + WORLD_CAVE_SIZE] != WORLD_CAVE_EXPECTED:
        raise RuntimeError("World-scan cave is not pristine")
    for address in range(TEXT_INSTRUCTION_START, TEXT_INSTRUCTION_END, 4):
        target = _direct_target(struct.unpack_from("<I", binary, address)[0], address)
        if target is not None and WORLD_CAVE <= target < WORLD_CAVE + WORLD_CAVE_SIZE:
            raise RuntimeError(
                f"World-scan cave is referenced by 0x{address:x} -> 0x{target:x}"
            )


def build_world_payload(temporary: Path) -> bytes:
    payload = _compile_payload(temporary)
    if len(payload) > WORLD_CAVE_SIZE:
        raise RuntimeError(f"World payload is {len(payload)} bytes; cave holds {WORLD_CAVE_SIZE}")
    class_offset = payload.find(CLASS_STRING)
    format_offset = payload.find(FORMAT_STRING)
    if class_offset < 0 or format_offset < 0:
        raise RuntimeError("World payload strings are missing")

    calls = (
        (END_ACCESS_MARKER, END_ACCESS, "swift_endAccess"),
        (WILD_GETTER_MARKER, WILD_GETTER, "wild getter"),
        (NEARBY_GETTER_MARKER, NEARBY_GETTER, "nearby getter"),
        (GYM_GETTER_MARKER, GYM_GETTER, "gym getter"),
        (STOP_GETTER_MARKER, STOP_GETTER, "PokeStop getter"),
        (BRIDGE_RELEASE_MARKER, BRIDGE_RELEASE, "bridge release"),
        (OBJC_GET_CLASS_MARKER, OBJC_GET_CLASS, "objc_getClass"),
        (UTF8_MARKER, MSG_SEND_STRING_WITH_UTF8, "UTF8 bridge"),
        (NSLOG_MARKER, NSLOG, "NSLog"),
    )
    for marker, target, label in calls:
        offset = _find_unique_instruction(payload, marker, label)
        _put_instruction(payload, offset, _encode_branch(WORLD_CAVE + offset, target, link=True))

    class_adrp = _find_unique_instruction(payload, CLASS_ADRP_MARKER, "class ADRP")
    class_add = _find_unique_instruction(payload, CLASS_ADD_MARKER, "class ADD")
    format_adrp = _find_unique_instruction(payload, FORMAT_ADRP_MARKER, "format ADRP")
    format_add = _find_unique_instruction(payload, FORMAT_ADD_MARKER, "format ADD")
    class_address = WORLD_CAVE + class_offset
    format_address = WORLD_CAVE + format_offset
    _put_instruction(payload, class_adrp, _encode_adrp(0, WORLD_CAVE + class_adrp, class_address))
    _put_instruction(payload, class_add, _encode_add_immediate(0, 0, class_address & 0xFFF))
    _put_instruction(payload, format_adrp, _encode_adrp(2, WORLD_CAVE + format_adrp, format_address))
    _put_instruction(payload, format_add, _encode_add_immediate(2, 2, format_address & 0xFFF))
    return bytes(payload) + b"\0" * (WORLD_CAVE_SIZE - len(payload))


def verify_source(binary: bytes) -> None:
    if sha256_bytes(binary) != SOURCE_FBL_SHA256:
        raise RuntimeError("FBLPromises hash does not match pristine iPogo 4.3.4")
    if FORBIDDEN_LOAD_PATH in binary:
        raise RuntimeError("Rejected legacy ShundoBridge load command")
    checks = (
        (HOOK_OFFSET, EXPECTED_HOOK, "simulated-source hook"),
        (CLASS_STRING_OFFSET, EXPECTED_CLASS_STORAGE, "class string storage"),
        (SELECTOR_STRING_OFFSET, EXPECTED_SELECTOR_STORAGE, "selector string storage"),
        (SELECTOR_REFERENCE_OFFSET, EXPECTED_SELECTOR_REFERENCE, "selector reference"),
        (FALSE_IMPLEMENTATION_OFFSET, EXPECTED_FALSE_IMPLEMENTATION, "false getter"),
        (SOURCE_INFORMATION_OFFSET, EXPECTED_SOURCE_INFORMATION_PROLOGUE, "sourceInformation prologue"),
        (STARTUP_CAVE_OFFSET, STARTUP_CAVE_EXPECTED, "startup cave"),
        (MOD_INIT_POINTER_OFFSET, EXPECTED_MOD_INIT_POINTER, "initializer pointer"),
        (NOTIFICATION_CALL_OFFSET, EXPECTED_NOTIFICATION_CALL, "notification call"),
        (NOTIFICATION_CAVE_OFFSET, NOTIFICATION_CAVE_EXPECTED, "notification cave"),
    )
    for offset, expected, label in checks:
        if binary[offset:offset + len(expected)] != expected:
            raise RuntimeError(f"Pristine {label} differs at 0x{offset:x}")
    for offset, expected, label in WORLD_HOOKS:
        if binary[offset:offset + 4] != expected:
            raise RuntimeError(f"Pristine {label} differs at 0x{offset:x}")
    verify_pristine_world_cave(binary)


def patch_binary(binary_path: Path, temporary: Path) -> dict[str, object]:
    original = binary_path.read_bytes()
    verify_source(original)
    payload = build_world_payload(temporary)
    patched = bytearray(original)
    replace_exact(patched, HOOK_OFFSET, EXPECTED_HOOK, PATCHED_HOOK)
    replace_exact(patched, CLASS_STRING_OFFSET, EXPECTED_CLASS_STORAGE, PATCHED_CLASS_STRING)
    replace_exact(patched, SELECTOR_STRING_OFFSET, EXPECTED_SELECTOR_STORAGE, PATCHED_SELECTOR_STRING)
    replace_exact(patched, SELECTOR_REFERENCE_OFFSET, EXPECTED_SELECTOR_REFERENCE, PATCHED_SELECTOR_REFERENCE)
    replace_exact(patched, STARTUP_CAVE_OFFSET, STARTUP_CAVE_EXPECTED, STARTUP_WRAPPER)
    replace_exact(patched, MOD_INIT_POINTER_OFFSET, EXPECTED_MOD_INIT_POINTER, PATCHED_MOD_INIT_POINTER)
    replace_exact(patched, NOTIFICATION_CALL_OFFSET, EXPECTED_NOTIFICATION_CALL, PATCHED_NOTIFICATION_CALL)
    replace_exact(patched, NOTIFICATION_CAVE_OFFSET, NOTIFICATION_CAVE_EXPECTED, NOTIFICATION_WRAPPER)
    replace_exact(patched, WORLD_CAVE, WORLD_CAVE_EXPECTED, payload)

    hooks: list[dict[str, str]] = []
    for offset, expected, label in WORLD_HOOKS:
        replacement = struct.pack("<I", _encode_branch(offset, WORLD_CAVE, link=False))
        replace_exact(patched, offset, expected, replacement)
        hooks.append({"label": label, "offset": hex(offset), "replacement": replacement.hex()})

    binary_path.write_bytes(patched)
    verify_patched_binary(bytes(patched), payload)
    return {
        "sourceFblSha256": sha256_bytes(original),
        "patchedFblSha256": sha256_bytes(patched),
        "worldPayloadSha256": sha256_bytes(payload),
        "worldHooks": hooks,
    }


def verify_patched_binary(binary: bytes, expected_payload: bytes | None = None) -> dict[str, object]:
    checks = (
        (HOOK_OFFSET, PATCHED_HOOK, "simulated-source mask"),
        (CLASS_STRING_OFFSET, PATCHED_CLASS_STRING, "class string"),
        (SELECTOR_STRING_OFFSET, PATCHED_SELECTOR_STRING, "selector string"),
        (SELECTOR_REFERENCE_OFFSET, PATCHED_SELECTOR_REFERENCE, "selector reference"),
        (FALSE_IMPLEMENTATION_OFFSET, EXPECTED_FALSE_IMPLEMENTATION, "false getter"),
        (SOURCE_INFORMATION_OFFSET, EXPECTED_SOURCE_INFORMATION_PROLOGUE, "sourceInformation prologue"),
        (STARTUP_CAVE_OFFSET, STARTUP_WRAPPER, "startup wrapper"),
        (MOD_INIT_POINTER_OFFSET, PATCHED_MOD_INIT_POINTER, "initializer redirect"),
        (NOTIFICATION_CALL_OFFSET, PATCHED_NOTIFICATION_CALL, "notification branch"),
        (NOTIFICATION_CAVE_OFFSET, NOTIFICATION_WRAPPER, "notification logger"),
    )
    verified: list[str] = []
    for offset, expected, label in checks:
        if binary[offset:offset + len(expected)] != expected:
            raise RuntimeError(f"Patched {label} differs at 0x{offset:x}")
        verified.append(label)
    if binary[STARTUP_CAVE_OFFSET + len(STARTUP_WRAPPER):STARTUP_CAVE_OFFSET + STARTUP_CAVE_SIZE] != STARTUP_CAVE_EXPECTED[len(STARTUP_WRAPPER):]:
        raise RuntimeError("Startup cave boundary was not preserved")
    if binary[NOTIFICATION_CAVE_OFFSET + len(NOTIFICATION_WRAPPER):NOTIFICATION_CAVE_OFFSET + NOTIFICATION_CAVE_SIZE] != NOTIFICATION_CAVE_EXPECTED[len(NOTIFICATION_WRAPPER):]:
        raise RuntimeError("Notification cave boundary was not preserved")
    world = binary[WORLD_CAVE:WORLD_CAVE + WORLD_CAVE_SIZE]
    if expected_payload is not None and world != expected_payload:
        raise RuntimeError("World payload differs from freshly generated payload")
    if LOG_PREFIX not in world or FORMAT_STRING not in world:
        raise RuntimeError("World-scan V3 protocol marker is missing")
    for offset, _original, label in WORLD_HOOKS:
        expected = struct.pack("<I", _encode_branch(offset, WORLD_CAVE, link=False))
        if binary[offset:offset + 4] != expected:
            raise RuntimeError(f"Patched {label} hook differs at 0x{offset:x}")
        verified.append(label)
    if FORBIDDEN_LOAD_PATH in binary:
        raise RuntimeError("Rejected legacy ShundoBridge load command")
    return {"fblSha256": sha256_bytes(binary), "verifiedLayers": verified}


def stamp_runtime(root: Path) -> None:
    info_path = root / INFO_PLIST
    info = plistlib.loads(info_path.read_bytes())
    if info.get("CFBundleIdentifier") != "com.nianticlabs.pokemongo":
        raise RuntimeError("Unexpected bundle identifier")
    if str(info.get("CFBundleShortVersionString") or "") != BASE_SHORT_VERSION:
        raise RuntimeError("Unexpected iPogo base version")
    info["ShundoSpawnRuntimeVersion"] = RUNTIME_VERSION
    info["ShundoSpawnRuntimeBuild"] = RUNTIME_BUILD
    info["ShundoWorldScanRuntimeVersion"] = WORLD_VERSION
    info["ShundoSpawnRuntimeDescription"] = (
        f"iPogo {BASE_IPOGO_LABEL} external-location compatibility, notification logging, and world telemetry"
    )
    if SUPPORTED_DEVICE_ADDITIONS:
        supported_devices = info.get("UISupportedDevices")
        if not isinstance(supported_devices, list):
            supported_devices = []
        for device in SUPPORTED_DEVICE_ADDITIONS:
            if device not in supported_devices:
                supported_devices.append(device)
        info["UISupportedDevices"] = supported_devices
    info["CFBundleVersion"] = BUNDLE_VERSION
    info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))


def verify_ipa(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if any(name.startswith("Payload/PokmonGO.app/Frameworks/ShundoBridge.framework/") for name in names):
            raise RuntimeError("Rejected failed injected-framework design")
        info = plistlib.loads(archive.read(INFO_PLIST.as_posix()))
        binary = archive.read(FBL.as_posix())
    expected_metadata = {
        "CFBundleIdentifier": "com.nianticlabs.pokemongo",
        "CFBundleShortVersionString": BASE_SHORT_VERSION,
        "CFBundleVersion": BUNDLE_VERSION,
        "ShundoSpawnRuntimeVersion": RUNTIME_VERSION,
        "ShundoSpawnRuntimeBuild": RUNTIME_BUILD,
        "ShundoWorldScanRuntimeVersion": WORLD_VERSION,
    }
    for key, expected in expected_metadata.items():
        if str(info.get(key) or "") != expected:
            raise RuntimeError(f"IPA metadata {key} is wrong")
    supported_devices = info.get("UISupportedDevices")
    for device in SUPPORTED_DEVICE_ADDITIONS:
        if not isinstance(supported_devices, list) or device not in supported_devices:
            raise RuntimeError(f"IPA metadata does not support required device {device}")
    report = verify_patched_binary(binary)
    report.update({
        "status": f"verified-ipogo-{BASE_IPOGO_LABEL}-hunter-runtime",
        "ipa": str(path.resolve()),
        "ipaSha256": sha256_file(path),
        "metadata": expected_metadata,
        "forbiddenFrameworkPresent": False,
    })
    return report


def macho_code_signature_range(binary: bytes) -> tuple[int, int]:
    if len(binary) < 32 or struct.unpack_from("<I", binary, 0)[0] != MH_MAGIC_64:
        raise RuntimeError("Expected a 64-bit little-endian Mach-O")
    command_count = struct.unpack_from("<I", binary, 16)[0]
    offset = 32
    for _ in range(command_count):
        command, command_size = struct.unpack_from("<II", binary, offset)
        if command_size < 8 or offset + command_size > len(binary):
            raise RuntimeError("Malformed Mach-O load command")
        if command == 0x1D:
            data_offset, data_size = struct.unpack_from("<II", binary, offset + 8)
            if data_offset + data_size > len(binary):
                raise RuntimeError("Code signature extends beyond the Mach-O")
            return data_offset, data_size
        offset += command_size
    raise RuntimeError("Mach-O has no LC_CODE_SIGNATURE")


def macho_segments(binary: bytes) -> dict[str, tuple[int, int]]:
    if len(binary) < 32 or struct.unpack_from("<I", binary, 0)[0] != MH_MAGIC_64:
        raise RuntimeError("Expected a 64-bit little-endian Mach-O")
    command_count = struct.unpack_from("<I", binary, 16)[0]
    offset = 32
    segments: dict[str, tuple[int, int]] = {}
    for _ in range(command_count):
        command, command_size = struct.unpack_from("<II", binary, offset)
        if command_size < 8 or offset + command_size > len(binary):
            raise RuntimeError("Malformed Mach-O load command")
        if command == 0x19:
            name = binary[offset + 8:offset + 24].split(b"\0", 1)[0].decode("ascii")
            file_offset, file_size = struct.unpack_from("<QQ", binary, offset + 40)
            segments[name] = (file_offset, file_size)
        offset += command_size
    return segments


def verify_resign(unsigned_ipa: Path, signed_ipa: Path) -> dict[str, object]:
    unsigned_report = verify_ipa(unsigned_ipa)
    signed_report = verify_ipa(signed_ipa)
    with zipfile.ZipFile(unsigned_ipa) as archive:
        unsigned_binary = archive.read(FBL.as_posix())
    with zipfile.ZipFile(signed_ipa) as archive:
        signed_binary = archive.read(FBL.as_posix())
    unsigned_segments = macho_segments(unsigned_binary)
    signed_segments = macho_segments(signed_binary)
    runtime_segments: list[str] = []
    for name, (unsigned_offset, unsigned_size) in unsigned_segments.items():
        if name == "__LINKEDIT":
            continue
        if name not in signed_segments:
            raise RuntimeError(f"Re-signing removed Mach-O segment {name}")
        signed_offset, signed_size = signed_segments[name]
        if (unsigned_offset, unsigned_size) != (signed_offset, signed_size):
            raise RuntimeError(f"Re-signing changed Mach-O segment layout for {name}")
        # __TEXT begins with the Mach-O header and load commands. codesign may
        # add LC_CODE_SIGNATURE in existing header padding, so compare from the
        # first executable page. Every runtime patch and both caves are after it.
        compare_offset = max(unsigned_offset, TEXT_INSTRUCTION_START if name == "__TEXT" else unsigned_offset)
        compare_end = unsigned_offset + unsigned_size
        if unsigned_binary[compare_offset:compare_end] != signed_binary[compare_offset:compare_end]:
            raise RuntimeError(f"Re-signing changed runtime bytes in Mach-O segment {name}")
        runtime_segments.append(name)
    signed_signature = macho_code_signature_range(signed_binary)
    differences = sum(a != b for a, b in zip(unsigned_binary, signed_binary)) + abs(len(unsigned_binary) - len(signed_binary))
    return {
        "status": f"verified-ipogo-{BASE_IPOGO_LABEL}-resign",
        "unsignedIpaSha256": unsigned_report["ipaSha256"],
        "signedIpaSha256": signed_report["ipaSha256"],
        "unsignedFblSha256": unsigned_report["fblSha256"],
        "signedFblSha256": signed_report["fblSha256"],
        "unsignedFblFileSize": len(unsigned_binary),
        "signedFblFileSize": len(signed_binary),
        "signatureOffset": signed_signature[0],
        "signingBookkeepingAndSignatureDifferenceCount": differences,
        "verifiedRuntimeSegments": runtime_segments,
        "runtimeBytesIdentical": True,
    }


def build(source: Path, output: Path, report_path: Path | None) -> dict[str, object]:
    if sha256_file(source) != SOURCE_IPA_SHA256:
        raise RuntimeError("Source IPA hash does not match inspected iPogo 4.3.4")
    if output.exists():
        raise RuntimeError(f"Output already exists: {output}")
    with tempfile.TemporaryDirectory(prefix="ipogo-434-runtime-") as temporary_name:
        temporary = Path(temporary_name)
        root = temporary / "root"
        run("ditto", "-x", "-k", str(source), str(root))
        patch_report = patch_binary(root / FBL, temporary)
        stamp_runtime(root)
        output.parent.mkdir(parents=True, exist_ok=True)
        run(
            "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
            str(root / "Payload"), str(output),
        )
    report = verify_ipa(output)
    report.update(patch_report)
    report["sourceIpaSha256"] = SOURCE_IPA_SHA256
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("source_ipa", type=Path)
    build_parser.add_argument("output_ipa", type=Path)
    build_parser.add_argument("--report", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("ipa", type=Path)
    verify_parser.add_argument("--report", type=Path)
    resign_parser = subparsers.add_parser("verify-resign")
    resign_parser.add_argument("unsigned_ipa", type=Path)
    resign_parser.add_argument("signed_ipa", type=Path)
    resign_parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        report = build(args.source_ipa, args.output_ipa, args.report)
    elif args.command == "verify":
        report = verify_ipa(args.ipa)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        report = verify_resign(args.unsigned_ipa, args.signed_ipa)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build an unsigned, spawn-compatible iPogo world-scan candidate.

The builder accepts only the empirically verified Hunter Runtime. It adds a
read-only log marker after four existing Swift Array mutations and does not
alter the simulated-source mask, scanner decisions, notification pipeline,
bundle identity, or Mach-O load commands.
"""

from __future__ import annotations

import argparse
import hashlib
import plistlib
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

from hunter_lab_artifact import GOLD_IPA_SHA256, INVARIANTS, verify_fbl
from patch_ipogo_simulated_flag import BINARY_RELATIVE_PATH, sha256


APP = Path("Payload/PokmonGO.app")
INFO_PLIST = APP / "Info.plist"
PAYLOAD_SOURCE = Path(__file__).with_name("ipogo_world_scan_payload.s")

RUNTIME_MARKER_KEY = "ShundoSpawnRuntimeVersion"
WORLD_MARKER_KEY = "ShundoWorldScanRuntimeVersion"
RUNTIME_VERSION = "3"
WORLD_VERSION = "3"
RUNTIME_BUILD_NUMBER = "4005"

WORLD_CAVE = 0xB9A000
WORLD_CAVE_SIZE = 0x400
# Verified file-backed zero padding at the end of the existing executable
# __TEXT segment. Hunter Lab already treats 0xB9A000-0xB9A800 as reserved and
# proves it sits outside every declared section and direct code reference.
WORLD_CAVE_EXPECTED = b"\0" * WORLD_CAVE_SIZE
END_ACCESS = 0x806E44
WILD_GETTER = 0x2463B0
NEARBY_GETTER = 0x2462F0
GYM_GETTER = 0x246534
STOP_GETTER = 0x2465F4
BRIDGE_RELEASE = 0x806D9C

HOOKS = (
    (0x25FF38, bytes.fromhex("7999ff17"), "nearby mutation completion"),
    (0x25FF3C, bytes.fromhex("7899ff17"), "wild mutation completion"),
    (0x25FF40, bytes.fromhex("7799ff17"), "gym mutation completion"),
    (0x25FF44, bytes.fromhex("7699ff17"), "PokeStop mutation completion"),
)

OBJC_GET_CLASS = 0x806940
MSG_SEND_STRING_WITH_UTF8 = 0x81370C
NSLOG = 0x806088

END_ACCESS_MARKER = 0x97FFFFF7
WILD_GETTER_MARKER = 0x97FFFFF6
NEARBY_GETTER_MARKER = 0x97FFFFF5
GYM_GETTER_MARKER = 0x97FFFFF4
STOP_GETTER_MARKER = 0x97FFFFF3
BRIDGE_RELEASE_MARKER = 0x97FFFFF2
CLASS_ADRP_MARKER = 0x90FFFFE0
CLASS_ADD_MARKER = 0x91FFFFE0
OBJC_GET_CLASS_MARKER = 0x97FFFFFA
FORMAT_ADRP_MARKER = 0x90FFFFC2
FORMAT_ADD_MARKER = 0x91FFFFC2
UTF8_MARKER = 0x97FFFFF9
NSLOG_MARKER = 0x97FFFFF8

CLASS_STRING = b"NSString\0"
FORMAT_STRING = (
    b"SHUNDO_WORLD_SCAN_V3 wild=%llu nearby=%llu gyms=%llu stops=%llu\0"
)
LOG_PREFIX = b"SHUNDO_WORLD_SCAN_V3 "

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
TEXT_INSTRUCTION_START = 0x4000
TEXT_INSTRUCTION_END = 0x804714


def _run(*arguments: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=capture,
        text=capture,
    )


def _encode_branch(source: int, target: int, *, link: bool) -> int:
    delta = target - source
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise RuntimeError(f"ARM64 branch out of range: 0x{source:x} -> 0x{target:x}")
    return (0x94000000 if link else 0x14000000) | ((delta >> 2) & 0x03FFFFFF)


def _encode_adrp(register: int, source: int, target: int) -> int:
    immediate = ((target & ~0xFFF) - (source & ~0xFFF)) >> 12
    if not -(1 << 20) <= immediate < (1 << 20):
        raise RuntimeError("ARM64 ADRP target is out of range")
    encoded = immediate & 0x1FFFFF
    return 0x90000000 | ((encoded & 3) << 29) | ((encoded >> 2) << 5) | register


def _encode_add_immediate(destination: int, base: int, immediate: int) -> int:
    if not 0 <= immediate <= 0xFFF:
        raise RuntimeError("ARM64 ADD immediate is out of range")
    return 0x91000000 | (immediate << 10) | (base << 5) | destination


def _put_instruction(data: bytearray, offset: int, instruction: int) -> None:
    data[offset:offset + 4] = struct.pack("<I", instruction)


def _find_unique_instruction(payload: bytearray, marker: int, label: str) -> int:
    needle = struct.pack("<I", marker)
    hits = [index for index in range(0, len(payload) - 3, 4) if payload[index:index + 4] == needle]
    if len(hits) != 1:
        raise RuntimeError(f"Expected one {label} marker, found {len(hits)}")
    return hits[0]


def _compile_payload(temporary: Path) -> bytearray:
    obj = temporary / "world-scan.o"
    _run(
        "xcrun", "clang", "-target", "arm64-apple-ios15.0", "-c",
        str(PAYLOAD_SOURCE.resolve()), "-o", str(obj),
    )
    data = obj.read_bytes()
    if len(data) < 32 or struct.unpack_from("<I", data, 0)[0] != MH_MAGIC_64:
        raise RuntimeError("World-scan assembler did not produce a 64-bit Mach-O object")
    command_count = struct.unpack_from("<I", data, 16)[0]
    cursor = 32
    text_section: tuple[int, int, int] | None = None
    for _ in range(command_count):
        command, command_size = struct.unpack_from("<II", data, cursor)
        if command == LC_SEGMENT_64:
            section_count = struct.unpack_from("<I", data, cursor + 64)[0]
            for index in range(section_count):
                section = cursor + 72 + index * 80
                name = data[section:section + 16].split(b"\0", 1)[0]
                if name == b"__text":
                    size = struct.unpack_from("<Q", data, section + 40)[0]
                    offset = struct.unpack_from("<I", data, section + 48)[0]
                    relocations = struct.unpack_from("<I", data, section + 60)[0]
                    text_section = (offset, size, relocations)
        cursor += command_size
    if text_section is None:
        raise RuntimeError("World-scan object is missing __text")
    offset, size, relocations = text_section
    if relocations:
        raise RuntimeError("World-scan payload unexpectedly contains relocations")
    payload = bytearray(data[offset:offset + size])
    if LOG_PREFIX not in payload or CLASS_STRING not in payload:
        raise RuntimeError("World-scan payload strings are missing")
    return payload


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def _direct_target(instruction: int, address: int) -> int | None:
    if instruction & 0x7C000000 == 0x14000000:
        return address + _sign_extend(instruction & 0x03FFFFFF, 26) * 4
    if instruction & 0xFF000010 == 0x54000000:
        return address + _sign_extend((instruction >> 5) & 0x7FFFF, 19) * 4
    if instruction & 0x7E000000 == 0x34000000:
        return address + _sign_extend((instruction >> 5) & 0x7FFFF, 19) * 4
    if instruction & 0x7E000000 == 0x36000000:
        return address + _sign_extend((instruction >> 5) & 0x3FFF, 14) * 4
    if instruction & 0x9F000000 == 0x10000000:
        immediate = ((instruction >> 5) & 0x7FFFF) << 2 | ((instruction >> 29) & 3)
        return address + _sign_extend(immediate, 21)
    if instruction & 0x9F000000 == 0x90000000:
        immediate = ((instruction >> 5) & 0x7FFFF) << 2 | ((instruction >> 29) & 3)
        return (address & ~0xFFF) + _sign_extend(immediate, 21) * 0x1000
    if instruction & 0x3B000000 == 0x18000000:
        return address + _sign_extend((instruction >> 5) & 0x7FFFF, 19) * 4
    return None


def _verify_pristine_cave(binary: bytes) -> None:
    if binary[WORLD_CAVE:WORLD_CAVE + WORLD_CAVE_SIZE] != WORLD_CAVE_EXPECTED:
        raise RuntimeError("World-scan code cave is not pristine")
    for address in range(TEXT_INSTRUCTION_START, TEXT_INSTRUCTION_END, 4):
        target = _direct_target(struct.unpack_from("<I", binary, address)[0], address)
        if target is not None and WORLD_CAVE <= target < WORLD_CAVE + WORLD_CAVE_SIZE:
            raise RuntimeError(
                f"World-scan cave is referenced by 0x{address:x} -> 0x{target:x}"
            )


def _build_payload(temporary: Path) -> bytes:
    payload = _compile_payload(temporary)
    if len(payload) > WORLD_CAVE_SIZE:
        raise RuntimeError(
            f"World-scan payload is {len(payload)} bytes; cave holds {WORLD_CAVE_SIZE}"
        )
    class_offset = payload.find(CLASS_STRING)
    format_offset = payload.find(FORMAT_STRING)
    if class_offset < 0 or format_offset < 0:
        raise RuntimeError("World-scan payload string offsets are invalid")

    call_markers = (
        (END_ACCESS_MARKER, END_ACCESS, "swift_endAccess BL"),
        (WILD_GETTER_MARKER, WILD_GETTER, "wild getter BL"),
        (NEARBY_GETTER_MARKER, NEARBY_GETTER, "nearby getter BL"),
        (GYM_GETTER_MARKER, GYM_GETTER, "gym getter BL"),
        (STOP_GETTER_MARKER, STOP_GETTER, "PokeStop getter BL"),
        (BRIDGE_RELEASE_MARKER, BRIDGE_RELEASE, "bridge release BL"),
    )
    patches = {
        _find_unique_instruction(payload, OBJC_GET_CLASS_MARKER, "objc_getClass BL"):
            _encode_branch(
                WORLD_CAVE + _find_unique_instruction(payload, OBJC_GET_CLASS_MARKER, "objc_getClass BL"),
                OBJC_GET_CLASS,
                link=True,
            ),
        _find_unique_instruction(payload, UTF8_MARKER, "UTF8 bridge BL"):
            _encode_branch(
                WORLD_CAVE + _find_unique_instruction(payload, UTF8_MARKER, "UTF8 bridge BL"),
                MSG_SEND_STRING_WITH_UTF8,
                link=True,
            ),
        _find_unique_instruction(payload, NSLOG_MARKER, "NSLog BL"):
            _encode_branch(
                WORLD_CAVE + _find_unique_instruction(payload, NSLOG_MARKER, "NSLog BL"),
                NSLOG,
                link=True,
            ),
    }
    for marker, target, label in call_markers:
        offset = _find_unique_instruction(payload, marker, label)
        patches[offset] = _encode_branch(WORLD_CAVE + offset, target, link=True)
    class_adrp = _find_unique_instruction(payload, CLASS_ADRP_MARKER, "class ADRP")
    class_add = _find_unique_instruction(payload, CLASS_ADD_MARKER, "class ADD")
    format_adrp = _find_unique_instruction(payload, FORMAT_ADRP_MARKER, "format ADRP")
    format_add = _find_unique_instruction(payload, FORMAT_ADD_MARKER, "format ADD")
    class_address = WORLD_CAVE + class_offset
    format_address = WORLD_CAVE + format_offset
    patches[class_adrp] = _encode_adrp(0, WORLD_CAVE + class_adrp, class_address)
    patches[class_add] = _encode_add_immediate(0, 0, class_address & 0xFFF)
    patches[format_adrp] = _encode_adrp(2, WORLD_CAVE + format_adrp, format_address)
    patches[format_add] = _encode_add_immediate(2, 2, format_address & 0xFFF)
    for offset, instruction in patches.items():
        _put_instruction(payload, offset, instruction)
    return bytes(payload) + WORLD_CAVE_EXPECTED[len(payload):]


def _patch_binary(binary_path: Path, temporary: Path) -> dict[str, object]:
    original = binary_path.read_bytes()
    verify_fbl(original, require_gold_hash=True)
    _verify_pristine_cave(original)
    payload = _build_payload(temporary)
    patched = bytearray(original)
    patched[WORLD_CAVE:WORLD_CAVE + WORLD_CAVE_SIZE] = payload
    hook_report: list[dict[str, object]] = []
    for offset, expected, label in HOOKS:
        actual = bytes(patched[offset:offset + 4])
        if actual != expected:
            raise RuntimeError(
                f"{label} hook differs at 0x{offset:x}: expected {expected.hex()}, got {actual.hex()}"
            )
        # These are coroutine resume thunks. Preserve their original tail-call
        # shape so the cave returns directly to the coroutine caller.
        replacement = struct.pack("<I", _encode_branch(offset, WORLD_CAVE, link=False))
        patched[offset:offset + 4] = replacement
        hook_report.append({
            "label": label,
            "offset": f"0x{offset:x}",
            "entry": f"0x{WORLD_CAVE:x}",
            "original": expected.hex(),
            "replacement": replacement.hex(),
        })
    binary_path.write_bytes(patched)
    _verify_patched_binary(bytes(patched), payload)
    return {
        "fblSha256": hashlib.sha256(patched).hexdigest(),
        "payloadSha256": hashlib.sha256(payload).hexdigest(),
        "payloadBytes": WORLD_CAVE_SIZE - len(WORLD_CAVE_EXPECTED[len(payload):]),
        "hooks": hook_report,
    }


def _verify_patched_binary(binary: bytes, payload: bytes) -> None:
    # Recheck every empirical-gold invariant.  The observer must remain outside
    # all spawn-compatibility and notification bytes.
    for invariant in INVARIANTS:
        actual = binary[invariant.offset:invariant.offset + len(invariant.expected)]
        if actual != invariant.expected:
            raise RuntimeError(f"World observer changed {invariant.label}")
    if binary[WORLD_CAVE:WORLD_CAVE + WORLD_CAVE_SIZE] != payload:
        raise RuntimeError("World-scan payload verification failed")
    if LOG_PREFIX not in payload:
        raise RuntimeError("World-scan marker is missing")
    for offset, _expected, label in HOOKS:
        expected_branch = struct.pack("<I", _encode_branch(offset, WORLD_CAVE, link=False))
        if binary[offset:offset + 4] != expected_branch:
            raise RuntimeError(f"Patched {label} hook verification failed")


def _stamp_runtime(root: Path) -> None:
    info_path = root / INFO_PLIST
    with info_path.open("rb") as source:
        info = plistlib.load(source)
    info[RUNTIME_MARKER_KEY] = RUNTIME_VERSION
    info[WORLD_MARKER_KEY] = WORLD_VERSION
    info["ShundoSpawnRuntimeDescription"] = (
        "Empirical spawn runtime with read-only world scan telemetry"
    )
    info["CFBundleVersion"] = RUNTIME_BUILD_NUMBER
    info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))


def _verify_base(path: Path) -> None:
    if sha256(path) != GOLD_IPA_SHA256:
        raise RuntimeError(
            "World-scan runtime accepts only the empirically verified signed base IPA"
        )
    with zipfile.ZipFile(path) as archive:
        verify_fbl(archive.read(BINARY_RELATIVE_PATH.as_posix()), require_gold_hash=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.output_ipa.exists():
        raise RuntimeError(f"Output already exists: {args.output_ipa}")
    _verify_base(args.source_ipa)

    with tempfile.TemporaryDirectory(prefix="ipogo-worldscan-") as temporary_name:
        temporary = Path(temporary_name)
        root = temporary / "root"
        _run("ditto", "-x", "-k", str(args.source_ipa), str(root))
        report = _patch_binary(root / BINARY_RELATIVE_PATH, temporary)
        _stamp_runtime(root)
        args.output_ipa.parent.mkdir(parents=True, exist_ok=True)
        _run(
            "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
            str(root / "Payload"), str(args.output_ipa),
        )

    report.update({
        "status": "verified-worldscan-candidate",
        "sourceIpaSha256": GOLD_IPA_SHA256,
        "outputIpaSha256": sha256(args.output_ipa),
        "runtimeVersion": RUNTIME_VERSION,
        "worldScanVersion": WORLD_VERSION,
        "bundleVersion": RUNTIME_BUILD_NUMBER,
    })
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(__import__("json").dumps(report, indent=2, sort_keys=True) + "\n")
    print(__import__("json").dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

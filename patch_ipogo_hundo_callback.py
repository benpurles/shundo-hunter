#!/usr/bin/env python3
"""Replace the first notification probe with a request-scheduling body logger.

This is an in-place arm64 patch: it adds no framework, dylib, or Mach-O load
command. The wrapper mirrors the body of iPogo's UNNotificationRequest to the
device log, then forwards the untouched request to UNUserNotificationCenter.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import tempfile
from pathlib import Path

from patch_ipogo_shundo_runtime import (
    EXPECTED_NOTIFICATION_CALL,
    NOTIFICATION_CALL_OFFSET,
    NOTIFICATION_CAVE_EXPECTED,
    NOTIFICATION_CAVE_OFFSET,
    NOTIFICATION_WRAPPER,
)
from patch_ipogo_simulated_flag import BINARY_RELATIVE_PATH, replace_exact, sha256


ADD_NOTIFICATION_CALL_OFFSET = 0x257700
EXPECTED_ADD_NOTIFICATION_CALL = bytes.fromhex("9fbc1694")

BODY_STRING_OFFSET = 0x674708
EXPECTED_BODY_STORAGE = bytes.fromhex("200020d4200020d4")
PATCHED_BODY_STORAGE = b"body\0\0\0\0"

CAVE_SIZE = 188
NSSTRING_CLASS_OFFSET = NOTIFICATION_CAVE_OFFSET + 0x94
FORMAT_STRING_OFFSET = NSSTRING_CLASS_OFFSET + len(b"NSString\0")
FORMAT_STRING = b"SHUNDO_HUNTER_NOTIFICATION %@\0"

OBJC_MSG_SEND = 0x80697C
NSLOG = 0x806088
NS_SELECTOR_FROM_STRING = 0x8060A0
OBJC_GET_CLASS = 0x806940
MSG_SEND_STRING_WITH_UTF8 = 0x81370C
CONTENT_SELECTOR_REFERENCE = 0xD41450

# Address-independent instructions assembled from notification_callback_patch.s.
WRAPPER_TEMPLATE = bytearray.fromhex(
    "ff8301d1fd7b05a9f35301a9f55b02a9"
    "e00703a9e20f04a90000009000000091"
    "00000094020000904200009100000094"
    "00000094f30300aae02340f908000090"
    "012942f900000094e10313aa00000094"
    "f40300aa000000900000009100000094"
    "020000904200009100000094e10314aa"
    "00000094e00743a9e20f44a900000094"
    "f55b42a9f35341a9fd7b45a9ff830191"
    "c0035fd6"
)


def encode_bl(source: int, target: int) -> int:
    delta = target - source
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise RuntimeError(f"Invalid arm64 branch from 0x{source:x} to 0x{target:x}")
    return 0x94000000 | ((delta >> 2) & 0x03FFFFFF)


def encode_adrp(register: int, source: int, target: int) -> int:
    page_delta = (target & ~0xFFF) - (source & ~0xFFF)
    immediate = page_delta >> 12
    if not -(1 << 20) <= immediate < (1 << 20):
        raise RuntimeError("ADRP target is out of range")
    encoded = immediate & 0x1FFFFF
    immlo = encoded & 0x3
    immhi = encoded >> 2
    return 0x90000000 | (immlo << 29) | (immhi << 5) | register


def encode_add_immediate(destination: int, source_register: int, immediate: int) -> int:
    if not 0 <= immediate <= 0xFFF:
        raise RuntimeError("ADD immediate is out of range")
    return 0x91000000 | (immediate << 10) | (source_register << 5) | destination


def put_instruction(code: bytearray, relative_offset: int, instruction: int) -> None:
    code[relative_offset:relative_offset + 4] = struct.pack("<I", instruction)


def build_wrapper() -> bytes:
    code = bytearray(WRAPPER_TEMPLATE)
    calls = {
        0x20: OBJC_GET_CLASS,
        0x2C: MSG_SEND_STRING_WITH_UTF8,
        0x30: NS_SELECTOR_FROM_STRING,
        0x44: OBJC_MSG_SEND,
        0x4C: OBJC_MSG_SEND,
        0x5C: OBJC_GET_CLASS,
        0x68: MSG_SEND_STRING_WITH_UTF8,
        0x70: NSLOG,
        0x7C: OBJC_MSG_SEND,
    }
    for relative_offset, target in calls.items():
        source = NOTIFICATION_CAVE_OFFSET + relative_offset
        put_instruction(code, relative_offset, encode_bl(source, target))

    addresses = {
        0x18: (0, NSSTRING_CLASS_OFFSET),
        0x24: (2, BODY_STRING_OFFSET),
        0x3C: (8, CONTENT_SELECTOR_REFERENCE),
        0x54: (0, NSSTRING_CLASS_OFFSET),
        0x60: (2, FORMAT_STRING_OFFSET),
    }
    for relative_offset, (register, target) in addresses.items():
        source = NOTIFICATION_CAVE_OFFSET + relative_offset
        put_instruction(code, relative_offset, encode_adrp(register, source, target))

    additions = {
        0x1C: (0, NSSTRING_CLASS_OFFSET & 0xFFF),
        0x28: (2, BODY_STRING_OFFSET & 0xFFF),
        0x58: (0, NSSTRING_CLASS_OFFSET & 0xFFF),
        0x64: (2, FORMAT_STRING_OFFSET & 0xFFF),
    }
    for relative_offset, (register, immediate) in additions.items():
        put_instruction(
            code,
            relative_offset,
            encode_add_immediate(register, register, immediate),
        )

    cave = bytes(code) + b"NSString\0" + FORMAT_STRING
    if len(cave) > CAVE_SIZE:
        raise RuntimeError(f"Notification callback does not fit the {CAVE_SIZE}-byte cave")
    return cave + NOTIFICATION_CAVE_EXPECTED[:CAVE_SIZE - len(cave)]


PATCHED_ADD_NOTIFICATION_CALL = struct.pack(
    "<I", encode_bl(ADD_NOTIFICATION_CALL_OFFSET, NOTIFICATION_CAVE_OFFSET)
)
PATCHED_CAVE = build_wrapper()
OLD_CAVE = NOTIFICATION_WRAPPER + NOTIFICATION_CAVE_EXPECTED[len(NOTIFICATION_WRAPPER):]


def patch_binary(binary: Path) -> None:
    data = bytearray(binary.read_bytes())
    replace_exact(data, NOTIFICATION_CALL_OFFSET, bytes.fromhex("8e741094"), EXPECTED_NOTIFICATION_CALL)
    replace_exact(data, BODY_STRING_OFFSET, EXPECTED_BODY_STORAGE, PATCHED_BODY_STORAGE)
    replace_exact(
        data,
        ADD_NOTIFICATION_CALL_OFFSET,
        EXPECTED_ADD_NOTIFICATION_CALL,
        PATCHED_ADD_NOTIFICATION_CALL,
    )
    replace_exact(data, NOTIFICATION_CAVE_OFFSET, OLD_CAVE, PATCHED_CAVE)
    binary.write_bytes(data)
    verify_binary(binary)


def verify_binary(binary: Path) -> None:
    data = binary.read_bytes()
    checks = (
        (NOTIFICATION_CALL_OFFSET, EXPECTED_NOTIFICATION_CALL, "retired notification call"),
        (BODY_STRING_OFFSET, PATCHED_BODY_STORAGE, "body selector string"),
        (ADD_NOTIFICATION_CALL_OFFSET, PATCHED_ADD_NOTIFICATION_CALL, "notification request callback"),
        (NOTIFICATION_CAVE_OFFSET, PATCHED_CAVE, "notification body logger"),
    )
    for offset, expected, label in checks:
        if data[offset:offset + len(expected)] != expected:
            raise RuntimeError(f"{label} verification failed at 0x{offset:x}")
    if data[NOTIFICATION_CAVE_OFFSET + CAVE_SIZE:NOTIFICATION_CAVE_OFFSET + CAVE_SIZE + 4] != bytes.fromhex("fc6fbba9"):
        raise RuntimeError("Notification cave crossed into the following function")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    args = parser.parse_args()
    if args.output_ipa.exists():
        raise RuntimeError(f"Output already exists: {args.output_ipa}")

    with tempfile.TemporaryDirectory(prefix="ipogo-hundo-callback-") as temporary:
        root = Path(temporary)
        subprocess.run(["ditto", "-x", "-k", str(args.source_ipa), str(root)], check=True)
        binary = root / BINARY_RELATIVE_PATH
        patch_binary(binary)
        args.output_ipa.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                str(root / "Payload"), str(args.output_ipa),
            ],
            check=True,
        )
    print(f"Created unsigned notification-request runtime: {args.output_ipa}")
    print(f"SHA-256: {sha256(args.output_ipa)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

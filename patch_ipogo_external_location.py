#!/usr/bin/env python3
"""Create a reversible iPogo test IPA that masks DVT source information.

The patch reuses iPogo's existing CLLocation altitude swizzle slot:
  1. The swizzle setup targets -[CLLocation sourceInformation] instead.
  2. The replacement implementation returns nil.

The original IPA is never modified. Exact hashes and bytes are checked so the
patch refuses to touch a different iPogo build.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path


EXPECTED_IPA_SHA256 = "5ff1c7ba5ac79143692823326872714d10a0d7ac3cc033df40a3c88d41382cfb"
EXPECTED_BINARY_SHA256 = "9e3ec66f2bc9a92d68548eb20f8259eac2b80c166957756160362021ce6ea2cf"
BINARY_RELATIVE_PATH = Path("Payload/PokmonGO.app/Frameworks/FBLPromises.framework/FBLPromises")

# VM addresses equal file offsets in this Mach-O's __TEXT and __DATA segments.
SWIZZLE_SELECTOR_LOAD_OFFSET = 0x130224
RETURN_NIL_IMPLEMENTATION_OFFSET = 0x132C3C
STRING_STORAGE_OFFSET = 0x81F820

EXPECTED_SELECTOR_LOAD = bytes.fromhex("8860009001c946f9")
PATCHED_SELECTOR_LOAD = bytes.fromhex("613700f021802091")
EXPECTED_RETURN_NIL_PREFIX = bytes.fromhex("fd7bbfa9fd030091")
PATCHED_RETURN_NIL_PREFIX = bytes.fromhex("000080d2c0035fd6")  # mov x0, #0; ret
EXPECTED_STRING_STORAGE = b"Coordinates imported successfully.\x00"
PATCHED_SELECTOR_STRING = b"sourceInformation\x00"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_exact(blob: bytearray, offset: int, expected: bytes, replacement: bytes) -> None:
    actual = bytes(blob[offset : offset + len(expected)])
    if actual != expected:
        raise RuntimeError(
            f"Refusing patch at 0x{offset:x}: expected {expected.hex()}, found {actual.hex()}"
        )
    if len(replacement) > len(expected):
        raise RuntimeError("Replacement is larger than its verified storage")
    blob[offset : offset + len(replacement)] = replacement


def verify_patched_binary(path: Path) -> None:
    data = path.read_bytes()
    if data[SWIZZLE_SELECTOR_LOAD_OFFSET : SWIZZLE_SELECTOR_LOAD_OFFSET + 8] != PATCHED_SELECTOR_LOAD:
        raise RuntimeError("Selector-load verification failed")
    if data[RETURN_NIL_IMPLEMENTATION_OFFSET : RETURN_NIL_IMPLEMENTATION_OFFSET + 8] != PATCHED_RETURN_NIL_PREFIX:
        raise RuntimeError("Return-nil implementation verification failed")
    if data[STRING_STORAGE_OFFSET : STRING_STORAGE_OFFSET + len(PATCHED_SELECTOR_STRING)] != PATCHED_SELECTOR_STRING:
        raise RuntimeError("Selector-string verification failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    args = parser.parse_args()

    if sha256(args.source_ipa) != EXPECTED_IPA_SHA256:
        raise RuntimeError("Source IPA hash does not match the inspected iPogo 4.3.3 build")
    if args.output_ipa.exists():
        raise RuntimeError(f"Output already exists: {args.output_ipa}")

    with tempfile.TemporaryDirectory(prefix="ipogo-external-location-") as temporary:
        root = Path(temporary)
        subprocess.run(["ditto", "-x", "-k", str(args.source_ipa), str(root)], check=True)
        binary = root / BINARY_RELATIVE_PATH
        if sha256(binary) != EXPECTED_BINARY_SHA256:
            raise RuntimeError("Injected framework hash does not match the inspected build")

        data = bytearray(binary.read_bytes())
        replace_exact(data, SWIZZLE_SELECTOR_LOAD_OFFSET, EXPECTED_SELECTOR_LOAD, PATCHED_SELECTOR_LOAD)
        replace_exact(data, RETURN_NIL_IMPLEMENTATION_OFFSET, EXPECTED_RETURN_NIL_PREFIX, PATCHED_RETURN_NIL_PREFIX)
        replace_exact(data, STRING_STORAGE_OFFSET, EXPECTED_STRING_STORAGE, PATCHED_SELECTOR_STRING)
        binary.write_bytes(data)
        verify_patched_binary(binary)

        args.output_ipa.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(root / "Payload"), str(args.output_ipa)],
            check=True,
        )

    print(f"Created: {args.output_ipa}")
    print(f"SHA-256: {sha256(args.output_ipa)}")
    print("The output is intentionally unsigned and must be signed before installation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Version-locked Shundo Hunter runtime builder for iPogo 4.3.8.

The 0.427.0 iPogo base preserves every Hunter-critical FBLPromises binary
invariant from the physically accepted 4.3.5 release. This module keeps the
same audited offsets and regenerated wrappers while locking the source hashes
and bundle metadata to the supplied 4.3.8 IPA.
"""

from __future__ import annotations

import struct

import build_ipogo_434_runtime as engine


def _write_instruction(blob: bytearray, offset: int, instruction: int) -> None:
    blob[offset:offset + 4] = struct.pack("<I", instruction)


def _build_notification_wrapper() -> bytes:
    """Regenerate every address-bearing instruction in the local logger."""
    wrapper = bytearray(engine.NOTIFICATION_WRAPPER)
    class_relative = wrapper.find(b"NSString\0")
    format_relative = wrapper.find(b"SHUNDO_HUNTER_NOTIFICATION ")
    if class_relative != 0x44 or format_relative != 0x54:
        raise RuntimeError("Unexpected notification-wrapper string layout")

    class_address = engine.NOTIFICATION_CAVE_OFFSET + class_relative
    format_address = engine.NOTIFICATION_CAVE_OFFSET + format_relative
    address_instructions = {
        0x14: engine._encode_adrp(0, engine.NOTIFICATION_CAVE_OFFSET + 0x14, class_address),
        0x18: engine._encode_add_immediate(0, 0, class_address & 0xFFF),
        0x20: engine._encode_adrp(2, engine.NOTIFICATION_CAVE_OFFSET + 0x20, format_address),
        0x24: engine._encode_add_immediate(2, 2, format_address & 0xFFF),
    }
    for relative_offset, instruction in address_instructions.items():
        _write_instruction(wrapper, relative_offset, instruction)

    branch_instructions = {
        0x1C: (engine.OBJC_GET_CLASS, True),
        0x28: (engine.MSG_SEND_STRING_WITH_UTF8, True),
        0x2C: (engine.NSLOG, True),
        0x40: (engine.NOTIFICATION_OBJC_MSG_SEND, False),
    }
    for relative_offset, (target, link) in branch_instructions.items():
        source = engine.NOTIFICATION_CAVE_OFFSET + relative_offset
        _write_instruction(wrapper, relative_offset, engine._encode_branch(source, target, link=link))
    return bytes(wrapper)


def _configure() -> None:
    engine.SUPPORTED_DEVICE_ADDITIONS = ()
    engine.SOURCE_IPA_SHA256 = "0238ad99cc0040f279ec14c9aff332b5d3f1e16696fef36a26c4e5dccfa747cf"
    engine.SOURCE_FBL_SHA256 = "fd681eb216d55c9fd9c8b082d142311a4988fa02adf59b921dac23d046621caf"
    engine.BASE_IPOGO_LABEL = "4.3.8"
    engine.BASE_SHORT_VERSION = "0.427.0"
    engine.RUNTIME_VERSION = "7"
    engine.RUNTIME_BUILD = "worldscan-v3-ipogo438-20260912a"
    engine.WORLD_VERSION = "3"
    # Preserve the new iPogo base build exactly. Pokémon GO's update gate reads
    # this value, so it must never be replaced by a Hunter release number.
    engine.BUNDLE_VERSION = "4"

    engine.HOOK_OFFSET = 0x130220
    engine.EXPECTED_HOOK = bytes.fromhex(
        "8860009001c946f9a8600090156140f9e00313aaa9581b94200100b4f40300aa"
        "e00313aae10315aaa4581b94800000b4e10300aae00314aa90591b94"
    )
    engine.PATCHED_HOOK = bytes.fromhex(
        "f40313aa603700f000002191cb591b94a8600090016140f9a8581b94e1ffffb0"
        "21f03f9198591b94f30314aa1f2003d51f2003d51f2003d51f2003d5"
    )
    engine.CLASS_STRING_OFFSET = 0x81F840
    engine.SELECTOR_STRING_OFFSET = 0x8213B0
    engine.SELECTOR_REFERENCE_OFFSET = 0xD440C0
    engine.EXPECTED_SELECTOR_REFERENCE = struct.pack("<Q", 0xACB256)
    engine.PATCHED_SELECTOR_REFERENCE = struct.pack("<Q", engine.SELECTOR_STRING_OFFSET)
    engine.FALSE_IMPLEMENTATION_OFFSET = 0x12DFFC
    engine.SOURCE_INFORMATION_OFFSET = 0x132C38

    engine.STARTUP_CAVE_OFFSET = 0x139E70
    engine.STARTUP_WRAPPER = bytes.fromhex(
        "fd7bbfa9fd030091203700d000002191b6321b94000100b4486000f0016140f9"
        "92311b94800000b4a1ffff9021f03f9181321b94fd7bc1a8577d1714"
    )
    engine.MOD_INIT_POINTER_OFFSET = 0xB9ECD8
    engine.EXPECTED_MOD_INIT_POINTER = struct.pack("<Q", 0x719404)
    engine.PATCHED_MOD_INIT_POINTER = struct.pack("<Q", engine.STARTUP_CAVE_OFFSET)

    engine.NOTIFICATION_CALL_OFFSET = 0x2574F4
    engine.NOTIFICATION_CAVE_OFFSET = 0x67472C
    engine.PATCHED_NOTIFICATION_CALL = struct.pack(
        "<I",
        engine._encode_branch(
            engine.NOTIFICATION_CALL_OFFSET,
            engine.NOTIFICATION_CAVE_OFFSET,
            link=True,
        ),
    )

    engine.TEXT_INSTRUCTION_END = 0x80472C
    engine.WORLD_HOOKS = (
        (0x25FF50, bytes.fromhex("7999ff17"), "nearby mutation completion"),
        (0x25FF54, bytes.fromhex("7899ff17"), "wild mutation completion"),
        (0x25FF58, bytes.fromhex("7799ff17"), "gym mutation completion"),
        (0x25FF5C, bytes.fromhex("7699ff17"), "PokeStop mutation completion"),
    )
    engine.END_ACCESS = 0x806E5C
    engine.WILD_GETTER = 0x2463C8
    engine.NEARBY_GETTER = 0x246308
    engine.GYM_GETTER = 0x24654C
    engine.STOP_GETTER = 0x24660C
    engine.BRIDGE_RELEASE = 0x806DB4
    engine.OBJC_GET_CLASS = 0x806958
    engine.MSG_SEND_STRING_WITH_UTF8 = 0x813724
    engine.NSLOG = 0x8060A0
    engine.NOTIFICATION_OBJC_MSG_SEND = 0x806994
    engine.NOTIFICATION_WRAPPER = _build_notification_wrapper()


_configure()

RUNTIME_BUILD = engine.RUNTIME_BUILD
RUNTIME_VERSION = engine.RUNTIME_VERSION
verify_ipa = engine.verify_ipa
verify_resign = engine.verify_resign
sha256_file = engine.sha256_file


if __name__ == "__main__":
    raise SystemExit(engine.main())

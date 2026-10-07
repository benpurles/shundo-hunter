#!/usr/bin/env python3
"""Build an isolated, unsigned Hunter Lab with a decoded live-feed probe.

The builder accepts only the empirical-gold spawn-compatible IPA. It creates a
side-by-side bundle, removes production callback identities, uses verified
executable tail padding in FBLPromises, observes the authenticated feed's
snapshot/delta merger, and never signs, installs, launches, moves the phone, or
changes notifications.
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

from hunter_lab_artifact import APP, FBL, INVARIANTS, verify_fbl, verify_gold_ipa, write_report


LAB_BUNDLE_ID = "com.nianticlabs.pokemongo.hunterlab"
LAB_NOTIFICATION_ID = LAB_BUNDLE_ID + ".notification"
LAB_WIDGET_ID = LAB_BUNDLE_ID + ".homewidget"
LAB_BUILD = "5015"
LAB_VERSION = "15"
LAB_MODE = "read-only-auto-refresh-feed-v15-all-levels"
LAB_MARKER_KEY = "ShundoHunterLabVersion"
LAB_URL_SCHEMES = (
    "hunterlab-facebook",
    "hunterlab-pokemongo",
    "hunterlab-google",
)

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LIVE_CALL = 0x1373C0
SNAPSHOT_CALL = 0x138A28
ORIGINAL_MERGER = 0x13A188
FEED_MERGER_HOOKS = (LIVE_CALL, SNAPSHOT_CALL)
FPRINTF_STUB = 0x806694
FFLUSH_STUB = 0x806664
STDERR_POINTER_GOT = 0xB9CDA8
MODEL_METADATA_ACCESSOR = 0x1711C4
ORIGINAL_INITIALIZER = 0x139E74
INITIALIZER_POINTER = 0xB9ECD8
DISPATCH_TIME_STUB = 0x8065F8
DISPATCH_AFTER_STUB = 0x806508
STACK_BLOCK_GOT = 0xB9CD38
MAIN_QUEUE_GOT = 0xB9CDC0
MANAGER_GETTER = 0x136AF0
MANAGER_START = 0x136D04
SWIFT_RELEASE_STUB = 0x806FA0

# This launch closure normally starts the authenticated feed manager only when
# iPogo's separate Live Feeds preference is enabled. Hunter Lab is isolated and
# exists solely to capture the user's own 100-IV snapshot, so remove both
# preference exits. The existing manager path first requests a fresh HTTP
# snapshot and then starts its delta socket; the snapshot still flows through
# SNAPSHOT_CALL above.
AUTO_FEED_OPTIONAL_EXIT = 0x12D66C
AUTO_FEED_DISABLED_EXIT = 0x12D674
AUTO_FEED_PATCHES = {
    AUTO_FEED_OPTIONAL_EXIT: 0x370006E1,  # tbnz w1, #0, disabled
    AUTO_FEED_DISABLED_EXIT: 0x540006A1,  # b.ne disabled
}

# The side-by-side Lab has its own empty UserDefaults container. iPogo's feed
# request builder treats a missing level preference as level 35, which reduces
# the global 100-IV snapshot to only a handful of level-35 records. Production
# normally supplies the user's saved feed preference here. Force the request's
# level field to zero (iPogo's all-levels value) after the preference lookup so
# the Lab cannot silently regress to the level-35 default.
FEED_LEVEL_SELECTION = 0x139714
FEED_LEVEL_SELECTION_ORIGINAL = 0x9A960016  # csel x22, x0, x22, eq
FEED_LEVEL_ALL = 0xAA1F03F6  # mov x22, xzr
NOP = 0xD503201F

# File-backed zero padding at the end of the existing R-X __TEXT segment. It is
# outside all sections, contains no function start, and is rejected if any
# direct ARM64 control-flow/literal reference targets the reserved range.
CODE_CAVE = 0xB9A000
CODE_CAVE_SIZE = 0x400
FORMAT_CAVE = 0xB9A400
FORMAT_CAVE_SIZE = 0x400
RESERVED_PADDING_END = 0xB9A800
TEXT_INSTRUCTION_START = 0x4000
TEXT_INSTRUCTION_END = 0x804714

PAGE_SIZE = 0x4000
SEGMENT_NAME = b"__HUNTER"
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LINKEDIT_DATA_COMMANDS = {
    0x1D,  # LC_CODE_SIGNATURE
    0x1E,  # LC_SEGMENT_SPLIT_INFO
    0x26,  # LC_FUNCTION_STARTS
    0x29,  # LC_DATA_IN_CODE
    0x2B,  # LC_DYLIB_CODE_SIGN_DRS
    0x2E,  # LC_LINKER_OPTIMIZATION_HINT
    0x80000033,  # LC_DYLD_EXPORTS_TRIE
    0x80000034,  # LC_DYLD_CHAINED_FIXUPS
}

METADATA_ACCESSOR_MARKER = 0x97FFFFFB
RENDER_FORMAT_ADR_MARKER = 0x10FFFFE0
RENDER_PRINTF_MARKER = 0x97FFFFFE
RENDER_FFLUSH_MARKER = 0x97FFFFFC
RENDER_STDERR_ADRP_MARKER = 0x90FFFFC8
RENDER_STDERR_LDR_MARKER = 0xF9400508
MERGER_TAIL_MARKER = 0x17FFFFFD
ENTRY_FORMAT_ADR_MARKER = 0x10FFFFC1
ENTRY_PRINTF_MARKER = 0x97FFFFFA
ENTRY_FFLUSH_MARKER = 0x97FFFFF9
ENTRY_STDERR_ADRP_MARKER = 0x90FFFFA8
ENTRY_STDERR_LDR_MARKER = 0xF9400108
INITIALIZER_ENTRY_MARKER = 0xD503245F
ORIGINAL_INITIALIZER_MARKER = 0x97FFFFF8
DISPATCH_TIME_MARKER = 0x97FFFFF7
STACK_BLOCK_ADRP_MARKER = 0x90FFFF88
STACK_BLOCK_LDR_MARKER = 0xF9400188
MAIN_QUEUE_ADRP_MARKER = 0x90FFFF68
MAIN_QUEUE_LDR_MARKER = 0xF94001A1
DISPATCH_AFTER_MARKER = 0x97FFFFF6
MANAGER_GETTER_MARKER = 0x97FFFFF5
MANAGER_START_MARKER = 0x97FFFFF4
SWIFT_RELEASE_MARKER = 0x97FFFFF3
LOG_PREFIX = b"HUNTER_FEED_ITEM_V12 "
ENTRY_PREFIX = b"HUNTER_FEED_ENTRY_V12"


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


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
    opcode = 0x94000000 if link else 0x14000000
    return opcode | ((delta >> 2) & 0x03FFFFFF)


def _encode_adrp(register: int, source: int, target: int) -> int:
    page_delta = (target & ~0xFFF) - (source & ~0xFFF)
    immediate = page_delta >> 12
    if not -(1 << 20) <= immediate < (1 << 20):
        raise RuntimeError("ARM64 ADRP target is out of range")
    encoded = immediate & 0x1FFFFF
    return 0x90000000 | ((encoded & 3) << 29) | ((encoded >> 2) << 5) | register


def _encode_ldr_x(destination: int, base: int, byte_offset: int) -> int:
    if byte_offset % 8 or not 0 <= byte_offset <= 0x7FF8:
        raise RuntimeError("ARM64 LDR X immediate is not encodable")
    return 0xF9400000 | ((byte_offset // 8) << 10) | (base << 5) | destination


def _encode_add_immediate(destination: int, base: int, immediate: int) -> int:
    if not 0 <= immediate <= 0xFFF:
        raise RuntimeError("ARM64 ADD immediate is not encodable")
    return 0x91000000 | (immediate << 10) | (base << 5) | destination


def _encode_adr(register: int, source: int, target: int) -> int:
    delta = target - source
    if not -(1 << 20) <= delta < (1 << 20):
        raise RuntimeError("ARM64 ADR target is out of range")
    encoded = delta & 0x1FFFFF
    return 0x10000000 | ((encoded & 3) << 29) | ((encoded >> 2) << 5) | register


def _put_instruction(data: bytearray, offset: int, instruction: int) -> None:
    data[offset:offset + 4] = struct.pack("<I", instruction)


def _find_unique_instruction(payload: bytearray, instruction: int, label: str) -> int:
    needle = struct.pack("<I", instruction)
    hits = [index for index in range(0, len(payload) - 3, 4) if payload[index:index + 4] == needle]
    if len(hits) != 1:
        raise RuntimeError(f"Expected one {label} marker, found {len(hits)}")
    return hits[0]


def _compile_payload(source: Path, temporary: Path) -> bytearray:
    obj = temporary / "hunter-feed-probe.o"
    _run(
        "xcrun", "clang", "-target", "arm64-apple-ios15.0", "-c",
        str(source.resolve()), "-o", str(obj),
    )
    data = obj.read_bytes()
    if len(data) < 32 or struct.unpack_from("<I", data, 0)[0] != MH_MAGIC_64:
        raise RuntimeError("Probe assembler did not produce a 64-bit Mach-O object")
    ncmds = struct.unpack_from("<I", data, 16)[0]
    command_offset = 32
    text_section: tuple[int, int, int, int] | None = None
    for _ in range(ncmds):
        command, command_size = struct.unpack_from("<II", data, command_offset)
        if command_size < 8 or command_offset + command_size > len(data):
            raise RuntimeError("Malformed probe object load command")
        if command == LC_SEGMENT_64:
            nsects = struct.unpack_from("<I", data, command_offset + 64)[0]
            section_offset = command_offset + 72
            for index in range(nsects):
                item = section_offset + index * 80
                sectname = data[item:item + 16].split(b"\0", 1)[0]
                offset = struct.unpack_from("<I", data, item + 48)[0]
                size = struct.unpack_from("<Q", data, item + 40)[0]
                reloff, nreloc = struct.unpack_from("<II", data, item + 56)
                if sectname == b"__text":
                    text_section = (offset, size, reloff, nreloc)
        command_offset += command_size
    if text_section is None:
        raise RuntimeError("Probe object is missing __text")
    offset, size, _reloff, nreloc = text_section
    if nreloc:
        raise RuntimeError("Probe payload unexpectedly contains relocations")
    payload = bytearray(data[offset:offset + size])
    if LOG_PREFIX not in payload:
        raise RuntimeError("Probe payload is missing its bounded log prefix")
    return payload


def _parse_segments(binary: bytes) -> tuple[int, int, list[dict[str, int | bytes]]]:
    if len(binary) < 32 or struct.unpack_from("<I", binary, 0)[0] != MH_MAGIC_64:
        raise RuntimeError("Expected a 64-bit little-endian Mach-O")
    ncmds, sizeofcmds = struct.unpack_from("<II", binary, 16)
    command_offset = 32
    segments: list[dict[str, int | bytes]] = []
    for _ in range(ncmds):
        command, command_size = struct.unpack_from("<II", binary, command_offset)
        if command_size < 8 or command_offset + command_size > len(binary):
            raise RuntimeError("Malformed FBLPromises load command")
        if command == LC_SEGMENT_64:
            segname = binary[command_offset + 8:command_offset + 24].split(b"\0", 1)[0]
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", binary, command_offset + 24)
            maxprot, initprot, nsects, flags = struct.unpack_from("<IIII", binary, command_offset + 56)
            segments.append({
                "commandOffset": command_offset,
                "name": segname,
                "vmaddr": vmaddr,
                "vmsize": vmsize,
                "fileoff": fileoff,
                "filesize": filesize,
                "maxprot": maxprot,
                "initprot": initprot,
                "nsects": nsects,
                "flags": flags,
            })
        command_offset += command_size
    if command_offset != 32 + sizeofcmds:
        raise RuntimeError("Mach-O sizeofcmds does not match parsed commands")
    return ncmds, sizeofcmds, segments


def _first_section_offset(binary: bytes, segments: list[dict[str, int | bytes]]) -> int:
    first = len(binary)
    for segment in segments:
        command_offset = int(segment["commandOffset"])
        for index in range(int(segment["nsects"])):
            item = command_offset + 72 + index * 80
            file_offset = struct.unpack_from("<I", binary, item + 48)[0]
            if file_offset:
                first = min(first, file_offset)
    return first


def _shift_u32(command: bytearray, offset: int, threshold: int) -> None:
    value = struct.unpack_from("<I", command, offset)[0]
    if value and value >= threshold:
        struct.pack_into("<I", command, offset, value + PAGE_SIZE)


def _shift_linkedit_offsets(command: bytearray, threshold: int) -> None:
    kind = struct.unpack_from("<I", command, 0)[0]
    if kind in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
        for offset in (8, 16, 24, 32, 40):
            _shift_u32(command, offset, threshold)
    elif kind == LC_SYMTAB:
        for offset in (8, 16):
            _shift_u32(command, offset, threshold)
    elif kind == LC_DYSYMTAB:
        for offset in (32, 40, 48, 56, 64, 72):
            _shift_u32(command, offset, threshold)
    elif kind in LINKEDIT_DATA_COMMANDS or kind == 0x16:  # LC_TWOLEVEL_HINTS
        _shift_u32(command, 8, threshold)


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def _direct_arm64_target(instruction: int, address: int) -> int | None:
    if instruction & 0x7C000000 == 0x14000000:  # B / BL
        return address + _sign_extend(instruction & 0x03FFFFFF, 26) * 4
    if instruction & 0xFF000010 == 0x54000000:  # B.cond
        return address + _sign_extend((instruction >> 5) & 0x7FFFF, 19) * 4
    if instruction & 0x7E000000 == 0x34000000:  # CBZ / CBNZ
        return address + _sign_extend((instruction >> 5) & 0x7FFFF, 19) * 4
    if instruction & 0x7E000000 == 0x36000000:  # TBZ / TBNZ
        return address + _sign_extend((instruction >> 5) & 0x3FFF, 14) * 4
    if instruction & 0x9F000000 == 0x10000000:  # ADR
        immediate = ((instruction >> 5) & 0x7FFFF) << 2 | ((instruction >> 29) & 3)
        return address + _sign_extend(immediate, 21)
    if instruction & 0x9F000000 == 0x90000000:  # ADRP
        immediate = ((instruction >> 5) & 0x7FFFF) << 2 | ((instruction >> 29) & 3)
        return (address & ~0xFFF) + _sign_extend(immediate, 21) * 0x1000
    if instruction & 0x3B000000 == 0x18000000:  # LDR literal family
        return address + _sign_extend((instruction >> 5) & 0x7FFFF, 19) * 4
    return None


def _assert_unreferenced_text_padding(binary: bytes) -> None:
    if binary[CODE_CAVE:RESERVED_PADDING_END] != b"\0" * (RESERVED_PADDING_END - CODE_CAVE):
        raise RuntimeError("Reserved __TEXT tail padding is not pristine zero fill")
    for address in range(TEXT_INSTRUCTION_START, TEXT_INSTRUCTION_END, 4):
        instruction = struct.unpack_from("<I", binary, address)[0]
        target = _direct_arm64_target(instruction, address)
        if target is not None and CODE_CAVE <= target < RESERVED_PADDING_END:
            raise RuntimeError(
                f"Reserved __TEXT tail is referenced by instruction 0x{address:x} -> 0x{target:x}"
            )

    # Prove the reserved range begins after every declared __TEXT section and
    # is not named as a function start in LC_FUNCTION_STARTS.
    ncmds = struct.unpack_from("<I", binary, 16)[0]
    cursor = 32
    last_text_section_end = 0
    function_starts: tuple[int, int] | None = None
    for _ in range(ncmds):
        kind, size = struct.unpack_from("<II", binary, cursor)
        if kind == LC_SEGMENT_64 and binary[cursor + 8:cursor + 24].split(b"\0", 1)[0] == b"__TEXT":
            nsects = struct.unpack_from("<I", binary, cursor + 64)[0]
            for index in range(nsects):
                section = cursor + 72 + index * 80
                address, section_size = struct.unpack_from("<QQ", binary, section + 32)
                last_text_section_end = max(last_text_section_end, address + section_size)
        elif kind == 0x26:  # LC_FUNCTION_STARTS
            function_starts = struct.unpack_from("<II", binary, cursor + 8)
        cursor += size
    if last_text_section_end > CODE_CAVE:
        raise RuntimeError(
            f"Reserved __TEXT padding overlaps a declared section ending at 0x{last_text_section_end:x}"
        )
    if function_starts is None:
        raise RuntimeError("FBLPromises has no LC_FUNCTION_STARTS table")
    dataoff, datasize = function_starts
    table = binary[dataoff:dataoff + datasize]
    address = 0
    index = 0
    while index < len(table):
        delta = 0
        shift = 0
        while True:
            if index >= len(table):
                raise RuntimeError("Truncated LC_FUNCTION_STARTS ULEB128")
            byte = table[index]
            index += 1
            delta |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
            if shift > 63:
                raise RuntimeError("Invalid LC_FUNCTION_STARTS ULEB128")
        if delta == 0:
            break
        address += delta
        if CODE_CAVE <= address < RESERVED_PADDING_END:
            raise RuntimeError(f"Reserved __TEXT tail contains function start 0x{address:x}")


def _inject_trailing_text_probe(binary_path: Path, assembly_source: Path, temporary: Path) -> dict[str, object]:
    original = bytearray(binary_path.read_bytes())
    verify_fbl(bytes(original))
    ncmds, sizeofcmds, segments = _parse_segments(original)
    if [item["name"] for item in segments] != [b"__TEXT", b"__DATA", b"__LINKEDIT"]:
        raise RuntimeError("Unexpected FBLPromises segment topology")
    text = segments[0]
    if int(text["fileoff"]) != 0 or int(text["filesize"]) != int(text["vmsize"]):
        raise RuntimeError("FBLPromises __TEXT is not directly file-backed")
    if RESERVED_PADDING_END > int(text["filesize"]) or (text["maxprot"], text["initprot"]) != (5, 5):
        raise RuntimeError("Reserved padding is not inside executable __TEXT")
    _assert_unreferenced_text_padding(original)

    payload = _compile_payload(assembly_source, temporary)
    format_offset = payload.find(LOG_PREFIX)
    if format_offset < 0:
        raise RuntimeError("Probe format string is missing")
    code = payload[:format_offset]
    format_string = payload[format_offset:]
    if len(code) > CODE_CAVE_SIZE or len(format_string) > FORMAT_CAVE_SIZE:
        raise RuntimeError("Probe does not fit reserved __TEXT tail padding")
    metadata_call_offset = _find_unique_instruction(code, METADATA_ACCESSOR_MARKER, "metadata accessor BL")
    render_format_adr_offset = _find_unique_instruction(code, RENDER_FORMAT_ADR_MARKER, "render format ADR")
    render_printf_offset = _find_unique_instruction(code, RENDER_PRINTF_MARKER, "render printf BL")
    render_fflush_offset = _find_unique_instruction(code, RENDER_FFLUSH_MARKER, "render fflush BL")
    render_stderr_adrp_offset = _find_unique_instruction(code, RENDER_STDERR_ADRP_MARKER, "render stderr ADRP")
    render_stderr_ldr_offset = _find_unique_instruction(code, RENDER_STDERR_LDR_MARKER, "render stderr LDR")
    merger_tail_offset = _find_unique_instruction(code, MERGER_TAIL_MARKER, "merger tail B")
    entry_format_adr_offset = _find_unique_instruction(code, ENTRY_FORMAT_ADR_MARKER, "entry format ADR")
    entry_printf_offset = _find_unique_instruction(code, ENTRY_PRINTF_MARKER, "entry printf BL")
    entry_fflush_offset = _find_unique_instruction(code, ENTRY_FFLUSH_MARKER, "entry fflush BL")
    entry_stderr_adrp_offset = _find_unique_instruction(code, ENTRY_STDERR_ADRP_MARKER, "entry stderr ADRP")
    entry_stderr_ldr_offset = _find_unique_instruction(code, ENTRY_STDERR_LDR_MARKER, "entry stderr LDR")
    entry_format_offset = format_string.find(ENTRY_PREFIX)
    if entry_format_offset < 0:
        raise RuntimeError("Probe entry diagnostic string is missing")
    initializer_entry_offset = _find_unique_instruction(code, INITIALIZER_ENTRY_MARKER, "initializer entry")
    original_initializer_offset = _find_unique_instruction(code, ORIGINAL_INITIALIZER_MARKER, "original initializer BL")
    dispatch_time_offset = _find_unique_instruction(code, DISPATCH_TIME_MARKER, "dispatch time BL")
    stack_block_adrp_offset = _find_unique_instruction(code, STACK_BLOCK_ADRP_MARKER, "stack block ADRP")
    stack_block_ldr_offset = _find_unique_instruction(code, STACK_BLOCK_LDR_MARKER, "stack block LDR")
    main_queue_adrp_offset = _find_unique_instruction(code, MAIN_QUEUE_ADRP_MARKER, "main queue ADRP")
    main_queue_ldr_offset = _find_unique_instruction(code, MAIN_QUEUE_LDR_MARKER, "main queue LDR")
    dispatch_after_offset = _find_unique_instruction(code, DISPATCH_AFTER_MARKER, "dispatch after BL")
    manager_getter_offset = _find_unique_instruction(code, MANAGER_GETTER_MARKER, "manager getter BL")
    manager_start_offset = _find_unique_instruction(code, MANAGER_START_MARKER, "manager start BL")
    swift_release_offset = _find_unique_instruction(code, SWIFT_RELEASE_MARKER, "swift release BL")
    _put_instruction(
        code,
        metadata_call_offset,
        _encode_branch(CODE_CAVE + metadata_call_offset, MODEL_METADATA_ACCESSOR, link=True),
    )
    _put_instruction(
        code,
        render_format_adr_offset,
        _encode_adr(1, CODE_CAVE + render_format_adr_offset, FORMAT_CAVE),
    )
    _put_instruction(code, render_stderr_adrp_offset, _encode_adrp(8, CODE_CAVE + render_stderr_adrp_offset, STDERR_POINTER_GOT))
    _put_instruction(code, render_stderr_ldr_offset, _encode_ldr_x(8, 8, STDERR_POINTER_GOT & 0xFFF))
    _put_instruction(code, render_printf_offset, _encode_branch(CODE_CAVE + render_printf_offset, FPRINTF_STUB, link=True))
    _put_instruction(code, render_fflush_offset, _encode_branch(CODE_CAVE + render_fflush_offset, FFLUSH_STUB, link=True))
    _put_instruction(
        code,
        entry_format_adr_offset,
        _encode_adr(1, CODE_CAVE + entry_format_adr_offset, FORMAT_CAVE + entry_format_offset),
    )
    _put_instruction(code, entry_printf_offset, _encode_branch(CODE_CAVE + entry_printf_offset, FPRINTF_STUB, link=True))
    _put_instruction(code, entry_fflush_offset, _encode_branch(CODE_CAVE + entry_fflush_offset, FFLUSH_STUB, link=True))
    _put_instruction(code, entry_stderr_adrp_offset, _encode_adrp(8, CODE_CAVE + entry_stderr_adrp_offset, STDERR_POINTER_GOT))
    _put_instruction(code, entry_stderr_ldr_offset, _encode_ldr_x(8, 8, STDERR_POINTER_GOT & 0xFFF))
    _put_instruction(code, initializer_entry_offset, NOP)
    _put_instruction(code, original_initializer_offset, _encode_branch(CODE_CAVE + original_initializer_offset, ORIGINAL_INITIALIZER, link=True))
    _put_instruction(code, dispatch_time_offset, _encode_branch(CODE_CAVE + dispatch_time_offset, DISPATCH_TIME_STUB, link=True))
    _put_instruction(code, stack_block_adrp_offset, _encode_adrp(8, CODE_CAVE + stack_block_adrp_offset, STACK_BLOCK_GOT))
    _put_instruction(code, stack_block_ldr_offset, _encode_ldr_x(8, 8, STACK_BLOCK_GOT & 0xFFF))
    _put_instruction(code, main_queue_adrp_offset, _encode_adrp(8, CODE_CAVE + main_queue_adrp_offset, MAIN_QUEUE_GOT))
    _put_instruction(code, main_queue_ldr_offset, _encode_ldr_x(1, 8, MAIN_QUEUE_GOT & 0xFFF))
    _put_instruction(code, dispatch_after_offset, _encode_branch(CODE_CAVE + dispatch_after_offset, DISPATCH_AFTER_STUB, link=True))
    _put_instruction(code, manager_getter_offset, _encode_branch(CODE_CAVE + manager_getter_offset, MANAGER_GETTER, link=True))
    _put_instruction(code, manager_start_offset, _encode_branch(CODE_CAVE + manager_start_offset, MANAGER_START, link=True))
    _put_instruction(code, swift_release_offset, _encode_branch(CODE_CAVE + swift_release_offset, SWIFT_RELEASE_STUB, link=True))
    _put_instruction(
        code,
        merger_tail_offset,
        _encode_branch(CODE_CAVE + merger_tail_offset, ORIGINAL_MERGER, link=False),
    )

    expected_merger_calls = {
        hook: _encode_branch(hook, ORIGINAL_MERGER, link=True)
        for hook in FEED_MERGER_HOOKS
    }
    for hook, expected in expected_merger_calls.items():
        if struct.unpack_from("<I", original, hook)[0] != expected:
            raise RuntimeError(f"Decoded feed merger call changed at 0x{hook:x}")
    for hook in FEED_MERGER_HOOKS:
        original[hook:hook + 4] = struct.pack("<I", _encode_branch(hook, CODE_CAVE, link=True))
    if struct.unpack_from("<Q", original, INITIALIZER_POINTER)[0] != ORIGINAL_INITIALIZER:
        raise RuntimeError("Original Hunter Lab module initializer pointer changed")
    struct.pack_into("<Q", original, INITIALIZER_POINTER, CODE_CAVE + initializer_entry_offset)
    for address, expected in AUTO_FEED_PATCHES.items():
        actual = struct.unpack_from("<I", original, address)[0]
        if actual != expected:
            raise RuntimeError(
                f"Authenticated feed launch gate changed at 0x{address:x}: "
                f"expected 0x{expected:08x}, found 0x{actual:08x}"
            )
        _put_instruction(original, address, NOP)
    actual_level_selection = struct.unpack_from("<I", original, FEED_LEVEL_SELECTION)[0]
    if actual_level_selection != FEED_LEVEL_SELECTION_ORIGINAL:
        raise RuntimeError(
            f"Feed level selection changed at 0x{FEED_LEVEL_SELECTION:x}: "
            f"expected 0x{FEED_LEVEL_SELECTION_ORIGINAL:08x}, "
            f"found 0x{actual_level_selection:08x}"
        )
    _put_instruction(original, FEED_LEVEL_SELECTION, FEED_LEVEL_ALL)
    original[CODE_CAVE:CODE_CAVE + len(code)] = code
    original[FORMAT_CAVE:FORMAT_CAVE + len(format_string)] = format_string
    binary_path.write_bytes(original)
    return {
        "layout": "unreferenced-file-backed-rx-text-padding",
        "codeAddress": f"0x{CODE_CAVE:x}",
        "codeReserved": CODE_CAVE_SIZE,
        "formatAddress": f"0x{FORMAT_CAVE:x}",
        "formatReserved": FORMAT_CAVE_SIZE,
        "payloadSize": len(payload),
        "payloadSha256": hashlib.sha256(payload).hexdigest(),
        "hookSites": [f"0x{hook:x}" for hook in FEED_MERGER_HOOKS],
        "originalMerger": f"0x{ORIGINAL_MERGER:x}",
        "captures": ["initial-http-snapshot", "websocket-delta"],
        "metadataAccessor": f"0x{MODEL_METADATA_ACCESSOR:x}",
        "logger": "fprintf-stderr-existing-stub",
        "entryDiagnostic": "HUNTER_FEED_ENTRY_V12",
        "delayedLaunch": {
            "initializerPointer": f"0x{INITIALIZER_POINTER:x}",
            "initializerAddress": f"0x{CODE_CAVE + initializer_entry_offset:x}",
            "delaySeconds": 12,
            "managerEntry": f"0x{MANAGER_START:x}",
        },
        "flush": "fflush-null-existing-stub",
        "automaticRefresh": {
            "entry": "existing authenticated Live Feeds launch closure",
            "patchedGates": [f"0x{address:x}" for address in AUTO_FEED_PATCHES],
            "requestMethod": "manager-vtable-0x78-snapshot-then-deltas",
            "levelFilter": "all-levels-forced-after-preference-lookup",
            "levelPatch": f"0x{FEED_LEVEL_SELECTION:x}",
        },
        "directReferenceScanPassed": True,
    }


def _write_bundle_info(path: Path, bundle_id: str, display_name: str) -> None:
    info = plistlib.loads(path.read_bytes())
    info["CFBundleIdentifier"] = bundle_id
    info["CFBundleVersion"] = LAB_BUILD
    info["CFBundleDisplayName"] = display_name
    info[LAB_MARKER_KEY] = LAB_VERSION
    info["ShundoHunterLabMode"] = LAB_MODE
    path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))


def _isolate_main_bundle(app: Path) -> dict[str, object]:
    info_path = app / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info["CFBundleIdentifier"] = LAB_BUNDLE_ID
    info["CFBundleVersion"] = LAB_BUILD
    info["CFBundleDisplayName"] = "iPogo Hunter Lab"
    info[LAB_MARKER_KEY] = LAB_VERSION
    info["ShundoHunterLabMode"] = LAB_MODE
    info["CFBundleURLTypes"] = [
        {
            "CFBundleURLName": "hunter-lab-isolated",
            "CFBundleURLSchemes": list(LAB_URL_SCHEMES),
        }
    ]
    info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))

    google_paths = [
        app / "GoogleService-Info.plist",
        app / "Frameworks/UnityFramework.framework/GoogleService-Info.plist",
    ]
    updated_google: list[str] = []
    for path in google_paths:
        if path.is_file():
            google = plistlib.loads(path.read_bytes())
            google["BUNDLE_ID"] = LAB_BUNDLE_ID
            path.write_bytes(plistlib.dumps(google, fmt=plistlib.FMT_BINARY))
            updated_google.append(str(path.relative_to(app)))
    return {"urlSchemes": list(LAB_URL_SCHEMES), "googleServicePlists": updated_google}


def verify_unsigned_v2(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        info = plistlib.loads(archive.read((APP / "Info.plist").as_posix()))
        notification = plistlib.loads(archive.read((APP / "PlugIns/notification.appex/Info.plist").as_posix()))
        widget = plistlib.loads(archive.read((APP / "PlugIns/homewidget.appex/Info.plist").as_posix()))
        fbl = archive.read(FBL.as_posix())
        google = plistlib.loads(archive.read((APP / "GoogleService-Info.plist").as_posix()))
        unity_google = plistlib.loads(
            archive.read((APP / "Frameworks/UnityFramework.framework/GoogleService-Info.plist").as_posix())
        )
    ids = {
        "main": info.get("CFBundleIdentifier"),
        "notification": notification.get("CFBundleIdentifier"),
        "widget": widget.get("CFBundleIdentifier"),
    }
    expected_ids = {"main": LAB_BUNDLE_ID, "notification": LAB_NOTIFICATION_ID, "widget": LAB_WIDGET_ID}
    if ids != expected_ids:
        raise RuntimeError(f"Hunter Lab v2 identities are not isolated: {ids}")
    for label, bundle_info in (("main", info), ("notification", notification), ("widget", widget)):
        if str(bundle_info.get("CFBundleVersion") or "") != LAB_BUILD:
            raise RuntimeError(f"{label} does not use build {LAB_BUILD}")
        if bundle_info.get(LAB_MARKER_KEY) != LAB_VERSION:
            raise RuntimeError(f"{label} is missing lab marker {LAB_VERSION}")
    schemes = tuple(
        scheme
        for item in info.get("CFBundleURLTypes", [])
        for scheme in item.get("CFBundleURLSchemes", [])
    )
    if schemes != LAB_URL_SCHEMES:
        raise RuntimeError(f"Hunter Lab URL schemes are not isolated: {schemes}")
    if google.get("BUNDLE_ID") != LAB_BUNDLE_ID or unity_google.get("BUNDLE_ID") != LAB_BUNDLE_ID:
        raise RuntimeError("Hunter Lab Google service identity is not isolated")
    if any("ShundoBridge.framework" in name for name in names):
        raise RuntimeError("Hunter Lab v2 contains forbidden ShundoBridge.framework")

    fbl_report = verify_fbl(fbl, require_gold_hash=False)
    ncmds, sizeofcmds, segments = _parse_segments(fbl)
    names = [segment["name"] for segment in segments]
    if names != [b"__TEXT", b"__DATA", b"__LINKEDIT"]:
        raise RuntimeError(f"Hunter Lab segment topology changed: {names}")
    code = fbl[CODE_CAVE:CODE_CAVE + CODE_CAVE_SIZE]
    format_region = fbl[FORMAT_CAVE:FORMAT_CAVE + FORMAT_CAVE_SIZE]
    if LOG_PREFIX not in format_region:
        raise RuntimeError("Hunter Lab v3 payload log marker is missing")
    if fbl[CODE_CAVE + CODE_CAVE_SIZE:FORMAT_CAVE] != b"\0" * (FORMAT_CAVE - CODE_CAVE - CODE_CAVE_SIZE):
        raise RuntimeError("Gap inside reserved __TEXT padding changed")
    if fbl[FORMAT_CAVE + FORMAT_CAVE_SIZE:RESERVED_PADDING_END] != b"\0" * (RESERVED_PADDING_END - FORMAT_CAVE - FORMAT_CAVE_SIZE):
        raise RuntimeError("Tail of reserved __TEXT padding changed")
    for hook in FEED_MERGER_HOOKS:
        render_call = struct.pack("<I", _encode_branch(hook, CODE_CAVE, link=True))
        if fbl[hook:hook + 4] != render_call:
            raise RuntimeError(f"Decoded feed hook at 0x{hook:x} does not target the RX tail padding")
    for address in AUTO_FEED_PATCHES:
        if struct.unpack_from("<I", fbl, address)[0] != NOP:
            raise RuntimeError(f"Automatic feed launch gate at 0x{address:x} is not disabled")
    if struct.unpack_from("<I", fbl, FEED_LEVEL_SELECTION)[0] != FEED_LEVEL_ALL:
        raise RuntimeError("Hunter Lab does not force the internal feed to all levels")
    initializer_pointer = struct.unpack_from("<Q", fbl, INITIALIZER_POINTER)[0]
    if not CODE_CAVE <= initializer_pointer < CODE_CAVE + CODE_CAVE_SIZE:
        raise RuntimeError("Delayed feed initializer pointer is outside the verified RX cave")
    if struct.pack("<I", METADATA_ACCESSOR_MARKER) in code:
        raise RuntimeError("Probe contains an unpatched metadata accessor marker")
    logger_markers = (
        RENDER_FORMAT_ADR_MARKER,
        RENDER_PRINTF_MARKER,
        RENDER_STDERR_ADRP_MARKER,
        RENDER_STDERR_LDR_MARKER,
        ENTRY_FORMAT_ADR_MARKER,
        ENTRY_PRINTF_MARKER,
        ENTRY_FFLUSH_MARKER,
        ENTRY_STDERR_ADRP_MARKER,
        ENTRY_STDERR_LDR_MARKER,
        ORIGINAL_INITIALIZER_MARKER,
        DISPATCH_TIME_MARKER,
        STACK_BLOCK_ADRP_MARKER,
        STACK_BLOCK_LDR_MARKER,
        MAIN_QUEUE_ADRP_MARKER,
        MAIN_QUEUE_LDR_MARKER,
        DISPATCH_AFTER_MARKER,
        MANAGER_GETTER_MARKER,
        MANAGER_START_MARKER,
        SWIFT_RELEASE_MARKER,
    )
    if any(struct.pack("<I", marker) in code for marker in logger_markers):
        raise RuntimeError("Probe contains an unpatched logger marker")
    if struct.pack("<I", RENDER_FFLUSH_MARKER) in code:
        raise RuntimeError("Probe contains an unpatched flush marker")
    if struct.pack("<I", MERGER_TAIL_MARKER) in code:
        raise RuntimeError("Probe contains an unpatched merger-tail marker")
    return {
        "status": "verified-unsigned-hunter-lab-v2",
        "artifact": str(path.resolve()),
        "bundleIdentifiers": ids,
        "bundleVersion": LAB_BUILD,
        "labVersion": LAB_VERSION,
        "mode": LAB_MODE,
        "urlSchemes": list(schemes),
        "fblPromises": fbl_report,
        "probeLayout": {
            "kind": "unreferenced-file-backed-rx-text-padding",
            "codeAddress": f"0x{CODE_CAVE:x}",
            "codeReserved": CODE_CAVE_SIZE,
            "formatAddress": f"0x{FORMAT_CAVE:x}",
            "formatReserved": FORMAT_CAVE_SIZE,
            "directReferenceScanPassed": True,
        },
        "machO": {"ncmds": ncmds, "sizeofcmds": sizeofcmds},
        "feedRequest": {
            "level": "all",
            "levelPatch": f"0x{FEED_LEVEL_SELECTION:x}",
            "iv": 100,
            "stats": "15/15/15",
        },
    }


def build(source: Path, output: Path, assembly_source: Path, report_path: Path | None) -> dict[str, object]:
    base_report = verify_gold_ipa(source)
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing artifact: {output}")
    with tempfile.TemporaryDirectory(prefix="hunter-lab-v2-") as temporary_name:
        temporary = Path(temporary_name)
        _run("ditto", "-x", "-k", str(source.resolve()), str(temporary))
        app = temporary / APP
        isolation = _isolate_main_bundle(app)
        _write_bundle_info(app / "PlugIns/notification.appex/Info.plist", LAB_NOTIFICATION_ID, "Hunter Lab Notifications")
        _write_bundle_info(app / "PlugIns/homewidget.appex/Info.plist", LAB_WIDGET_ID, "Hunter Lab Widget")
        probe = _inject_trailing_text_probe(temporary / FBL, assembly_source, temporary)
        output.parent.mkdir(parents=True, exist_ok=True)
        _run(
            "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
            str(temporary / "Payload"), str(output.resolve()),
        )
    unsigned_report = verify_unsigned_v2(output)
    report = {"schema": 2, "base": base_report, "isolation": isolation, "probe": probe, "lab": unsigned_report}
    if report_path:
        write_report(report, report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build unsigned, isolated Hunter Lab v2")
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    parser.add_argument(
        "--assembly",
        type=Path,
        default=Path(__file__).with_name("hunter_feed_probe_payload.s"),
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = build(args.source_ipa, args.output_ipa, args.assembly, args.report)
    print(json.dumps(report["lab"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

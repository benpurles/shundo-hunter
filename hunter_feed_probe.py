"""Read-only LLDB probe for iPogo 4.3.3's decoded internal feed.

Usage after attaching LLDB to the Hunter Lab process:

    command script import /absolute/path/to/hunter_feed_probe.py
    hunter-feed-start

The breakpoint auto-continues.  It never writes target memory or changes
control flow.  Each feed snapshot/delta is printed as one HUNTER_FEED JSON
line, including a few sanitized decoded records.
"""

from __future__ import annotations

import json
import struct

import lldb


MODULE_NAME = "FBLPromises"
MERGE_FUNCTION_OFFSET = 0x13A188
MERGE_FUNCTION_SYMBOL = (
    "_$s11FBLPromises32iZxRfxidHMa6zPEaIArPO6MPOaINDTeNC32"
    "KXyKj5bnYyr4V2YeFtU0Y70cdVB2C1JD33_BA1EAB72269B9A8FB0522475B8802E7D"
    "LL7results7replaceySayAA32i6tKmuuuoZ2uFKQeYBBTzDaanM5iALNHVG_SbtFTf4nnd_n"
)
MODEL_METADATA_POINTER_OFFSET = 0xE05DB0
MAX_SAMPLES = 5


def _error() -> lldb.SBError:
    return lldb.SBError()


def _read_unsigned(process: lldb.SBProcess, address: int, size: int) -> int:
    error = _error()
    value = process.ReadUnsignedFromMemory(address, size, error)
    if error.Fail():
        raise RuntimeError(f"read failed at 0x{address:x}: {error.GetCString()}")
    return value


def _read_pointer(process: lldb.SBProcess, address: int) -> int:
    error = _error()
    value = process.ReadPointerFromMemory(address, error)
    if error.Fail():
        raise RuntimeError(f"pointer read failed at 0x{address:x}: {error.GetCString()}")
    return value


def _read_double(process: lldb.SBProcess, address: int) -> float:
    error = _error()
    raw = process.ReadMemory(address, 8, error)
    if error.Fail() or len(raw) != 8:
        raise RuntimeError(f"double read failed at 0x{address:x}: {error.GetCString()}")
    return struct.unpack("<d", raw)[0]


def _register(frame: lldb.SBFrame, name: str) -> int:
    register = frame.FindRegister(name)
    if not register.IsValid():
        raise RuntimeError(f"missing register {name}")
    return register.GetValueAsUnsigned()


def _optional_int(process: lldb.SBProcess, item: int, offset: int) -> int | None:
    value = _read_unsigned(process, item + offset, 8)
    tag = _read_unsigned(process, item + offset + 8, 1)
    return value if tag == 0 else None


def _module(target: lldb.SBTarget) -> lldb.SBModule:
    for module in target.module_iter():
        if module.GetFileSpec().GetFilename() == MODULE_NAME:
            return module
    raise RuntimeError(f"{MODULE_NAME} is not loaded")


def _load_address(target: lldb.SBTarget, module: lldb.SBModule, file_address: int) -> int:
    address = module.ResolveFileAddress(file_address)
    if not address.IsValid():
        raise RuntimeError(f"cannot resolve {MODULE_NAME}+0x{file_address:x}")
    load_address = address.GetLoadAddress(target)
    if load_address == lldb.LLDB_INVALID_ADDRESS:
        raise RuntimeError(f"{MODULE_NAME}+0x{file_address:x} has no load address")
    return load_address


def _sample_records(
    target: lldb.SBTarget,
    process: lldb.SBProcess,
    module: lldb.SBModule,
    storage: int,
    count: int,
) -> list[dict[str, object]]:
    metadata_slot = _load_address(target, module, MODEL_METADATA_POINTER_OFFSET)
    metadata = _read_pointer(process, metadata_slot)
    if metadata == 0:
        return []
    value_witness = _read_pointer(process, metadata - 8)
    stride = _read_unsigned(process, value_witness + 0x48, 8)
    alignment_mask = _read_unsigned(process, value_witness + 0x50, 1)
    first = storage + ((0x20 + alignment_mask) & ~alignment_mask)

    cp_offset = _read_unsigned(process, metadata + 0x28, 4)
    iv_offset = _read_unsigned(process, metadata + 0x2C, 4)
    level_offset = _read_unsigned(process, metadata + 0x30, 4)
    samples: list[dict[str, object]] = []
    for index in range(min(count, MAX_SAMPLES)):
        item = first + stride * index
        pokemon_id = _read_unsigned(process, item + 0x10, 8)
        coordinates = _read_pointer(process, item + 0x18)
        coordinate_count = _read_unsigned(process, coordinates + 0x10, 8)
        if coordinate_count < 2:
            continue
        longitude = _read_double(process, coordinates + 0x20)
        latitude = _read_double(process, coordinates + 0x28)
        samples.append(
            {
                "index": index,
                "pokemonId": pokemon_id,
                "iv": _optional_int(process, item, iv_offset),
                "level": _optional_int(process, item, level_offset),
                "cp": _optional_int(process, item, cp_offset),
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
            }
        )
    return samples


def feed_breakpoint(frame: lldb.SBFrame, _location, _internal_dict) -> bool:
    try:
        thread = frame.GetThread()
        process = thread.GetProcess()
        target = process.GetTarget()
        module = _module(target)
        storage = _register(frame, "x0")
        replace = bool(_register(frame, "w1") & 1)
        count = _read_unsigned(process, storage + 0x10, 8) if storage else 0
        payload = {
            "event": "decoded-feed",
            "mode": "snapshot" if replace else "delta",
            "count": count,
            "samples": _sample_records(target, process, module, storage, count) if count else [],
        }
        print("HUNTER_FEED " + json.dumps(payload, separators=(",", ":"), sort_keys=True))
    except Exception as error:  # LLDB must continue even if a layout check fails.
        print("HUNTER_FEED " + json.dumps({"event": "probe-error", "error": str(error)}))
    return False


class HunterFeedStart:
    def __init__(self, debugger, _internal_dict):
        self.debugger = debugger

    def __call__(self, debugger, _command, _execution_context, result):
        target = debugger.GetSelectedTarget()
        if not target.IsValid() or not target.GetProcess().IsValid():
            result.SetError("Attach to the Hunter Lab process first")
            return
        try:
            try:
                module = _module(target)
                address = module.ResolveFileAddress(MERGE_FUNCTION_OFFSET)
                breakpoint = target.BreakpointCreateBySBAddress(address)
                location = f"{MODULE_NAME}+0x{MERGE_FUNCTION_OFFSET:x}"
            except RuntimeError:
                breakpoint = target.BreakpointCreateByName(MERGE_FUNCTION_SYMBOL, MODULE_NAME)
                location = "pending decoded-feed merger symbol"
            breakpoint.SetScriptCallbackFunction(__name__ + ".feed_breakpoint")
            breakpoint.SetOneShot(False)
            result.AppendMessage(
                f"Hunter feed probe armed at {location}; "
                "open or refresh iPogo's internal feed"
            )
        except Exception as error:
            result.SetError(str(error))


def __lldb_init_module(debugger, _internal_dict):
    debugger.HandleCommand(
        "command script add -c " + __name__ + ".HunterFeedStart hunter-feed-start"
    )
    print("Hunter feed probe loaded. Run: hunter-feed-start")

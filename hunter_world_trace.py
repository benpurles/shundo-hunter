"""Read-only LLDB hit trace for iPogo 4.3.3's world scanner boundaries.

Import after attaching to the signed development build, then run
``hunter-world-trace-start``. Every breakpoint auto-continues and only reports
which candidate boundary executed; it never writes process memory.
"""

from __future__ import annotations

import json
import time

import lldb


MODULE_NAME = "FBLPromises"
CANDIDATES = {
    0x245A94: "wild-unsafe-addressor",
    0x246330: "nearby-modify",
    0x2463B0: "wild-getter",
    0x2463F0: "wild-modify",
    0x24AC28: "decoded-rpc-processor",
    0x24EA1C: "per-response-scanner",
    0x25633C: "typed-rpc-observer",
    0x2574DC: "notification-pipeline",
    0x25FF38: "nearby-modify-resume",
    0x25FF3C: "wild-modify-resume",
    0x25FF40: "gym-modify-resume",
    0x25FF44: "pokestop-modify-resume",
}

_labels_by_load_address: dict[int, str] = {}
_hits: dict[str, int] = {}


def _module(target: lldb.SBTarget) -> lldb.SBModule:
    for module in target.module_iter():
        if module.GetFileSpec().GetFilename() == MODULE_NAME:
            return module
    raise RuntimeError(f"{MODULE_NAME} is not loaded")


def trace_breakpoint(frame: lldb.SBFrame, _location, _internal_dict) -> bool:
    load_address = frame.GetPCAddress().GetLoadAddress(frame.GetThread().GetProcess().GetTarget())
    label = _labels_by_load_address.get(load_address, f"0x{load_address:x}")
    _hits[label] = _hits.get(label, 0) + 1
    print(
        "HUNTER_WORLD_TRACE "
        + json.dumps(
            {
                "label": label,
                "hits": _hits[label],
                "monotonic": round(time.monotonic(), 6),
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )
    return False


class HunterWorldTraceStart:
    def __init__(self, debugger, _internal_dict):
        self.debugger = debugger

    def __call__(self, debugger, _command, _execution_context, result):
        target = debugger.GetSelectedTarget()
        if not target.IsValid() or not target.GetProcess().IsValid():
            result.SetError("Attach to iPogo first")
            return
        try:
            module = _module(target)
            armed = []
            for file_address, label in CANDIDATES.items():
                address = module.ResolveFileAddress(file_address)
                load_address = address.GetLoadAddress(target)
                if load_address == lldb.LLDB_INVALID_ADDRESS:
                    raise RuntimeError(f"cannot resolve {label} at 0x{file_address:x}")
                breakpoint = target.BreakpointCreateBySBAddress(address)
                breakpoint.SetScriptCallbackFunction(__name__ + ".trace_breakpoint")
                breakpoint.SetOneShot(False)
                _labels_by_load_address[load_address] = label
                armed.append(label)
            result.AppendMessage("HUNTER_WORLD_TRACE_ARMED " + ",".join(armed))
        except Exception as error:
            result.SetError(str(error))


def __lldb_init_module(debugger, _internal_dict):
    debugger.HandleCommand(
        "command script add -c " + __name__ + ".HunterWorldTraceStart hunter-world-trace-start"
    )
    print("Hunter world trace loaded. Run: hunter-world-trace-start", flush=True)

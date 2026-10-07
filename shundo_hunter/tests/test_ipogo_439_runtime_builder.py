import struct
import unittest

import build_ipogo_439_runtime as runtime


def direct_target(instruction: int, source: int) -> int | None:
    opcode = instruction & 0xFC000000
    if opcode not in (0x14000000, 0x94000000):
        return None
    immediate = instruction & 0x03FFFFFF
    if immediate & 0x02000000:
        immediate -= 1 << 26
    return source + immediate * 4


class Ipogo439NotificationWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime._configure()

    def test_release_metadata_is_locked_to_supplied_base(self) -> None:
        self.assertEqual(runtime.engine.BASE_IPOGO_LABEL, "4.3.9")
        self.assertEqual(runtime.engine.BASE_SHORT_VERSION, "0.429.1")
        self.assertEqual(runtime.engine.BUNDLE_VERSION, "0")
        self.assertEqual(runtime.engine.RUNTIME_VERSION, "8")
        self.assertEqual(runtime.engine.SUPPORTED_DEVICE_ADDITIONS, ("iPhone14,3",))

    def test_all_notification_calls_resolve_to_439_targets(self) -> None:
        expected = {
            0x1C: runtime.engine.OBJC_GET_CLASS,
            0x28: runtime.engine.MSG_SEND_STRING_WITH_UTF8,
            0x2C: runtime.engine.NSLOG,
            0x40: runtime.engine.NOTIFICATION_OBJC_MSG_SEND,
        }
        for relative, target in expected.items():
            instruction = struct.unpack_from(
                "<I", runtime.engine.NOTIFICATION_WRAPPER, relative
            )[0]
            self.assertEqual(
                direct_target(instruction, runtime.engine.NOTIFICATION_CAVE_OFFSET + relative),
                target,
            )

    def test_cave_local_strings_resolve_inside_the_439_wrapper(self) -> None:
        wrapper = runtime.engine.NOTIFICATION_WRAPPER
        cave = runtime.engine.NOTIFICATION_CAVE_OFFSET
        for adrp_relative, add_relative, expected_relative in (
            (0x14, 0x18, 0x44),
            (0x20, 0x24, 0x54),
        ):
            adrp = struct.unpack_from("<I", wrapper, adrp_relative)[0]
            add = struct.unpack_from("<I", wrapper, add_relative)[0]
            adrp_immediate = (((adrp >> 5) & 0x7FFFF) << 2) | ((adrp >> 29) & 0x3)
            if adrp_immediate & (1 << 20):
                adrp_immediate -= 1 << 21
            page = ((cave + adrp_relative) & ~0xFFF) + (adrp_immediate << 12)
            immediate = (add >> 10) & 0xFFF
            self.assertEqual(page + immediate, cave + expected_relative)


if __name__ == "__main__":
    unittest.main()

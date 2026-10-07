import struct
import unittest

import build_ipogo_435_runtime as runtime


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def _branch_target(instruction: int, source: int) -> int:
    return source + _sign_extend(instruction & 0x03FFFFFF, 26) * 4


def _adrp_add_target(adrp: int, add: int, source: int) -> int:
    immediate = ((adrp >> 5) & 0x7FFFF) << 2 | ((adrp >> 29) & 0x3)
    page = (source & ~0xFFF) + _sign_extend(immediate, 21) * 0x1000
    return page + ((add >> 10) & 0xFFF)


class Ipogo435NotificationWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = runtime.engine
        self.cave = self.engine.NOTIFICATION_CAVE_OFFSET
        self.wrapper = self.engine.NOTIFICATION_WRAPPER

    def instruction(self, relative_offset: int) -> int:
        return struct.unpack_from("<I", self.wrapper, relative_offset)[0]

    def test_cave_local_strings_resolve_inside_the_435_wrapper(self) -> None:
        self.assertEqual(
            _adrp_add_target(self.instruction(0x14), self.instruction(0x18), self.cave + 0x14),
            self.cave + 0x44,
        )
        self.assertEqual(
            _adrp_add_target(self.instruction(0x20), self.instruction(0x24), self.cave + 0x20),
            self.cave + 0x54,
        )
        self.assertEqual(self.wrapper[0x44:0x4D], b"NSString\0")
        self.assertTrue(self.wrapper[0x54:].startswith(b"SHUNDO_HUNTER_NOTIFICATION "))

    def test_all_notification_calls_resolve_to_435_targets(self) -> None:
        expected = {
            0x1C: self.engine.OBJC_GET_CLASS,
            0x28: self.engine.MSG_SEND_STRING_WITH_UTF8,
            0x2C: self.engine.NSLOG,
            0x40: self.engine.NOTIFICATION_OBJC_MSG_SEND,
        }
        for relative_offset, target in expected.items():
            with self.subTest(relative_offset=relative_offset):
                self.assertEqual(
                    _branch_target(self.instruction(relative_offset), self.cave + relative_offset),
                    target,
                )

if __name__ == "__main__":
    unittest.main()

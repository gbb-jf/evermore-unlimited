"""Patch integrity checks; ROM-dependent cases use only the local private dump."""

import hashlib
from pathlib import Path
import random
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build_npc import (HOOK, SOURCE_SHA256, SOURCE_SIZE, SPAWN_OFFSET,
                       TALK_OFFSET, TARGET_SIZE, TEXT_OFFSET, build_rom,
                       create_bps, packed_script, packed_text, write_checked)


def apply_bps(source, patch):
    """Independent BPS reader, including checksums and overlapping TargetCopy."""
    if patch[:4] != b"BPS1":
        raise ValueError("Invalid BPS header")
    source_crc, target_crc, patch_crc = struct.unpack("<III", patch[-12:])
    if zlib.crc32(source) != source_crc or zlib.crc32(patch[:-4]) != patch_crc:
        raise ValueError("Checksum mismatch")
    cursor = 4

    def number():
        nonlocal cursor
        value, shift = 0, 1
        while True:
            byte = patch[cursor]
            cursor += 1
            value += (byte & 127) * shift
            if byte & 128:
                return value
            shift <<= 7
            value += shift

    source_size, target_size, metadata_size = number(), number(), number()
    if source_size != len(source):
        raise ValueError("Wrong source size")
    cursor += metadata_size
    output = bytearray()
    source_relative, target_relative = 0, 0
    while len(output) < target_size:
        action = number()
        length, mode = (action >> 2) + 1, action & 3
        if mode == 0:
            output.extend(source[len(output):len(output) + length])
        elif mode == 1:
            output.extend(patch[cursor:cursor + length])
            cursor += length
        else:
            offset = number()
            delta = (offset >> 1) * (-1 if offset & 1 else 1)
            if mode == 2:
                source_relative += delta
                output.extend(source[source_relative:source_relative + length])
                source_relative += length
            else:
                target_relative += delta
                for _ in range(length):
                    output.append(output[target_relative])
                    target_relative += 1
    if cursor != len(patch) - 12 or zlib.crc32(output) != target_crc:
        raise ValueError("Invalid output or trailing data")
    return bytes(output)


class BpsTests(unittest.TestCase):
    def test_round_trip_cases(self):
        for source, target in [(b"", b""), (b"a", b"b"), (b"abc", b"abc"),
                               (b"abc", b"ab"), (b"", b"\xff" * 10000),
                               (b"abcd", b"abXYcd" + b"\xff" * 10000 + b"END"),
                               (b"abcdef", b"x" * 40 + b"yz" + b"q" * 60)]:
            with self.subTest(source=source[:8], size=len(target)):
                self.assertEqual(apply_bps(source, create_bps(source, target)), target)

    def test_randomized_round_trips(self):
        rng = random.Random(42)
        for _ in range(50):
            source = rng.randbytes(rng.randrange(500))
            target = bytearray(source)
            for _ in range(5):
                at = rng.randrange(len(target) + 1)
                target[at:at + rng.randrange(20)] = rng.randbytes(rng.randrange(30))
            self.assertEqual(apply_bps(source, create_bps(source, target)), target)

    def test_patch_rejects_wrong_input_and_corruption(self):
        patch = create_bps(b"abc", b"abd")
        with self.assertRaises(ValueError):
            apply_bps(b"xyz", patch)
        with self.assertRaises(ValueError):
            apply_bps(b"abc", patch[:-1] + bytes([patch[-1] ^ 1]))


class AddressTests(unittest.TestCase):
    def test_script_address_round_trip(self):
        for offset in (0x128000, 0x1BC446, SPAWN_OFFSET, TALK_OFFSET, 0x3FFFFF):
            packed = packed_script(offset)
            unpacked = 0x128000 + (packed & 0x7FFF) + ((packed & 0xFF8000) << 1)
            self.assertEqual(unpacked, offset)

    def test_text_address_round_trip(self):
        for offset in (0x10000, TEXT_OFFSET, 0x3F7FFF):
            packed = packed_text(offset)
            self.assertEqual((packed & 0x7FFF) + ((packed & 0x7F8000) << 1), offset)

    def test_checked_write_rejects_mismatch(self):
        data = bytearray(b"abcd")
        with self.assertRaises(ValueError):
            write_checked(data, 0, b"xx", b"yz")
        self.assertEqual(data, b"abcd")

    def test_unsupported_input_rejected(self):
        with self.assertRaises(ValueError):
            build_rom(b"not a ROM")


class LocalRomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / "roms/original.sfc"
        if not cls.path.is_file():
            raise unittest.SkipTest("Private source ROM not present")
        cls.source = cls.path.read_bytes()
        cls.target = build_rom(cls.source)

    def test_source_preserved_and_build_reproducible(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), SOURCE_SHA256)
        self.assertEqual(build_rom(self.source), self.target)

    def test_snes_checksum(self):
        self.assertEqual(len(self.target), TARGET_SIZE)
        complement, checksum = struct.unpack("<HH", self.target[0xFFDC:0xFFE0])
        self.assertEqual(complement ^ checksum, 0xFFFF)
        self.assertEqual(sum(self.target) & 0xFFFF, checksum)

    def test_patch_reconstructs_exact_rom(self):
        patch = create_bps(self.source, self.target)
        self.assertEqual(apply_bps(self.source, patch), self.target)
        self.assertLess(len(patch), 1024)

    def test_only_expected_original_ranges_changed(self):
        allowed = set(range(0xFFDC, 0xFFE0)) | set(range(HOOK, HOOK + 4))
        allowed |= set(range(0x129C3E, 0x129C41)) | set(range(0x11D006, 0x11D009))
        changes = {i for i in range(SOURCE_SIZE) if self.source[i] != self.target[i]}
        self.assertTrue(changes <= allowed)

    def test_modified_or_headered_rom_rejected(self):
        changed = bytearray(self.source)
        changed[100] ^= 1
        for data in (changed, b"\0" * 512 + self.source):
            with self.assertRaises(ValueError):
                build_rom(data)


if __name__ == "__main__":
    unittest.main()

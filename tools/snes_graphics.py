"""Native SNES 4bpp encoding and little-endian address helpers."""
import struct

def u16(value):
    return struct.pack("<H", value & 0xffff)

def u24(value):
    return value.to_bytes(3, "little")

def encode_block(pixels):
    """Encode a 16x16 block as four standard SNES 4bpp 8x8 tiles."""
    data = bytearray(128)
    for y in range(16):
        for x in range(16):
            value = pixels[y][x]
            tile = x // 8 + 2 * (y // 8)
            for plane in range(4):
                if value & (1 << plane):
                    at = tile * 32 + (y % 8) * 2 + (plane % 2) + (plane // 2) * 16
                    data[at] |= 1 << (7 - x % 8)
    return bytes(data)



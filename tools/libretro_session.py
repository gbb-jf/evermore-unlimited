"""Small headless libretro frontend for reproducible ROM experiments.

Requires Pillow for screenshots and a separately built Snes9x libretro core.
No ROM, game graphics, or emulator code is bundled with this module.
"""

import ctypes as C
from pathlib import Path


class GameInfo(C.Structure):
    _fields_ = [("path", C.c_char_p), ("data", C.c_void_p),
                ("size", C.c_size_t), ("meta", C.c_char_p)]


class Session:
    BUTTONS = {"B": 0, "Y": 1, "Select": 2, "Start": 3,
               "Up": 4, "Down": 5, "Left": 6, "Right": 7,
               "A": 8, "X": 9, "L": 10, "R": 11}

    def __init__(self, core, rom):
        self.core = C.CDLL(str(Path(core).resolve()))
        self.buttons = set()
        self.frame = 0
        self.pixel_format = 0
        self.capture = False
        self.video_frame = None
        self.directory = str(Path(rom).resolve().parent).encode()
        self.log_callback = C.CFUNCTYPE(None, C.c_int, C.c_char_p)(lambda *_: None)
        signatures = {
            "retro_load_game": ([C.POINTER(GameInfo)], C.c_bool),
            "retro_get_memory_data": ([C.c_uint], C.c_void_p),
            "retro_get_memory_size": ([C.c_uint], C.c_size_t),
            "retro_serialize_size": ([], C.c_size_t),
            "retro_serialize": ([C.c_void_p, C.c_size_t], C.c_bool),
            "retro_unserialize": ([C.c_void_p, C.c_size_t], C.c_bool),
            "retro_set_controller_port_device": ([C.c_uint, C.c_uint], None),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.core, name)
            function.argtypes, function.restype = args, result
        # Retain callbacks for the complete lifetime of the C core.
        callbacks = [
            ("environment", C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p), self._environment),
            ("video_refresh", C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t), self._video),
            ("audio_sample", C.CFUNCTYPE(None, C.c_int16, C.c_int16), lambda *_: None),
            ("audio_sample_batch", C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t), lambda _, n: n),
            ("input_poll", C.CFUNCTYPE(None), lambda: None),
            ("input_state", C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint),
             lambda port, device, index, button: int(port == 0 and button in self.buttons)),
        ]
        self.callbacks = []
        for name, callback_type, function in callbacks:
            callback = callback_type(function)
            self.callbacks.append(callback)
            setter = getattr(self.core, "retro_set_" + name)
            setter.argtypes = [callback_type]
            setter(callback)
        self.core.retro_init()
        self.rom = C.create_string_buffer(Path(rom).read_bytes())
        info = GameInfo(str(Path(rom).resolve()).encode(), C.cast(self.rom, C.c_void_p),
                        len(self.rom) - 1, None)
        if not self.core.retro_load_game(C.byref(info)):
            raise RuntimeError("Emulator could not load ROM")
        self.core.retro_set_controller_port_device(0, 1)
        size = self.core.retro_get_memory_size(2)
        self.ram = (C.c_ubyte * size).from_address(self.core.retro_get_memory_data(2))

    def _environment(self, command, data):
        if command == 10:  # SET_PIXEL_FORMAT
            self.pixel_format = C.cast(data, C.POINTER(C.c_int))[0]
            return self.pixel_format in (0, 1, 2)
        if command in (9, 31):  # GET_SYSTEM_DIRECTORY / GET_SAVE_DIRECTORY
            C.cast(data, C.POINTER(C.c_char_p))[0] = self.directory
            return True
        if command == 17:  # GET_VARIABLE_UPDATE
            C.cast(data, C.POINTER(C.c_bool))[0] = False
            return True
        if command == 47:  # GET_AUDIO_VIDEO_ENABLE
            C.cast(data, C.POINTER(C.c_int))[0] = 3
            return True
        if command == 27:  # GET_LOG_INTERFACE (variadic arguments are ignored)
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.cast(self.log_callback, C.c_void_p)
            return True
        if command in (11, 18):  # input descriptors / support no-game
            return True
        return False

    def _video(self, data, width, height, pitch):
        if self.capture and data and data != C.c_void_p(-1).value:
            self.video_frame = (C.string_at(data, pitch * height), width, height, pitch)

    def run(self, frames, *buttons):
        self.buttons = {self.BUTTONS[name] for name in buttons}
        for _ in range(frames):
            self.core.retro_run()
            self.frame += 1

    def word(self, address):
        return self.ram[address] | self.ram[address + 1] << 8

    def screenshot(self, path):
        from PIL import Image
        self.capture = True
        self.run(1)
        self.capture = False
        data, width, height, pitch = self.video_frame
        if self.pixel_format == 1:
            result = Image.frombytes("RGB", (width, height), data, "raw", "BGRX", pitch)
        else:
            pixels = bytearray()
            for y in range(height):
                for x in range(width):
                    offset = y * pitch + 2 * x
                    value = int.from_bytes(data[offset:offset + 2], "little")
                    if self.pixel_format == 2:
                        r, g, b = value >> 11, (value >> 5) & 63, value & 31
                        pixels.extend((r * 255 // 31, g * 255 // 63, b * 255 // 31))
                    else:
                        r, g, b = (value >> 10) & 31, (value >> 5) & 31, value & 31
                        pixels.extend((r * 255 // 31, g * 255 // 31, b * 255 // 31))
            result = Image.frombytes("RGB", (width, height), bytes(pixels))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        result.save(path)

    def save_state(self, path):
        size = self.core.retro_serialize_size()
        buffer = C.create_string_buffer(size)
        if not self.core.retro_serialize(buffer, size):
            raise RuntimeError("Could not serialize emulator state")
        Path(path).write_bytes(buffer.raw)

    def load_state(self, path):
        data = Path(path).read_bytes()
        buffer = C.create_string_buffer(data)
        if not self.core.retro_unserialize(buffer, len(data)):
            raise RuntimeError("Could not restore emulator state")

    def close(self):
        self.core.retro_unload_game()
        self.core.retro_deinit()

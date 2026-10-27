"""Shared emulator selection: Luna by default, libretro only when requested."""

import hashlib
from pathlib import Path


DEFAULT_LUNA = Path(__file__).resolve().parent / "vendor/luna/target/release/luna"


def add_arguments(parser):
    emulator = parser.add_mutually_exclusive_group()
    emulator.add_argument("--luna", type=Path,
                          help="Luna CLI executable (default: tools/vendor/luna/target/release/luna)")
    emulator.add_argument("--core", type=Path, help="Explicit alternative libretro core")


def open_session(rom, *, luna=None, core=None):
    if luna is not None and core is not None:
        raise ValueError("Choose either Luna or a libretro core")
    executable = Path(core if core is not None else luna or DEFAULT_LUNA)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    if core is None:
        from luna_session import Session
        session = Session(executable, rom)
        return session, {"emulator": session.info["name"], "version": session.info["version"],
                         "executable_sha256": digest, "backend": "stdio-mcp"}

    import ctypes as C
    from libretro_session import Session

    class SystemInfo(C.Structure):
        _fields_ = [("library_name", C.c_char_p), ("library_version", C.c_char_p),
                    ("valid_extensions", C.c_char_p), ("need_fullpath", C.c_bool),
                    ("block_extract", C.c_bool)]

    session = Session(executable, rom)
    info = SystemInfo()
    session.core.retro_get_system_info.argtypes = [C.POINTER(SystemInfo)]
    session.core.retro_get_system_info(C.byref(info))
    return session, {"emulator": info.library_name.decode(), "version": info.library_version.decode(),
                     "core_sha256": digest, "backend": "libretro"}

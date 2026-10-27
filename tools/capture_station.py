"""Generate a private, ROM-derived reference image for the scene editor."""

import hashlib
import json
from pathlib import Path

from libretro_session import Session


def capture(root, core=None):
    root = Path(root)
    core = Path(core or root / "tools/vendor/snes9x_libretro.so")
    source = root / "roms/original.sfc"
    from build_npc import SOURCE_SHA256, SOURCE_SIZE
    source_bytes = source.read_bytes()
    if len(source_bytes) != SOURCE_SIZE or hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("Reference capture requires the clean, unheadered US ROM")
    output = root / "build/editor"
    output.mkdir(parents=True, exist_ok=True)
    session = Session(core, source)
    try:
        session.run(1500)
        session.run(1, "Start")
        session.run(240)
        session.run(1, "Start")
        session.run(120)
        for button in ("Up", "B", "Start", "B"):
            session.run(1, button)
            session.run(15)
        session.run(18000)
        session.screenshot(output / "station.png")
        metadata = {"x": session.word(0x2401), "y": session.word(0x2405),
                    "width": 256, "height": 192, "fresh_boot": True,
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        (output / "station.json").write_text(json.dumps(metadata, indent=2) + "\n")
        return metadata
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    from character_model import ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--core", type=Path)
    args = parser.parse_args()
    print(json.dumps(capture(args.root, args.core)))

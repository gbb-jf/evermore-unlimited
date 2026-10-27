#!/usr/bin/env python3
"""Verify private cowboy graphics and four talk facings using real controller input."""

import argparse
import hashlib
import json
from pathlib import Path

from build_npc import build_rom
from cowboy_graphics import FRAME_OFFSET, PALETTE_ID, load_art
from emulator_session import add_arguments, open_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--rom", type=Path, default=Path("build/evermore-npc.sfc"))
    parser.add_argument("--original", type=Path, default=Path("roms/original.sfc"))
    parser.add_argument("--output-dir", type=Path, default=Path("build/cowboy-facings"))
    args = parser.parse_args()
    if args.rom.read_bytes() != build_rom(args.original.read_bytes()):
        parser.error("Rebuild the current ROM before verification")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session, report = open_session(args.rom, luna=args.luna, core=args.core)
    report.update({"fresh_boot": True, "ram_writes": False, "events": [], "poses": [],
                   "rom_sha256": hashlib.sha256(args.rom.read_bytes()).hexdigest()})

    def run(frames, *buttons):
        session.run(frames, *buttons)
        report["events"].append({"frames": frames, "buttons": list(buttons), "at_frame": session.frame})

    def check(condition, message):
        if not condition:
            session.screenshot(args.output_dir / "failure.png")
            raise RuntimeError(message)

    try:
        run(1500)
        run(1, "Start")
        run(240)
        run(1, "Start")
        run(120)
        for button in ("Up", "B", "Start", "B"):
            run(1, button)
            run(15)
        run(18000)
        npc = session.word(0x0341)
        check(session.word(npc + 0x66) == 0x19AA, "Cowboy talk script missing")
        check(session.word(npc + 8) == 0xF1, "Cowboy is not using private frame bank")
        slot = session.ram[npc + 0x0C]
        check(session.word(0x1278 + slot) == PALETTE_ID, "Cowboy palette is shared")
        _, palette = load_art()
        for color in range(1, 16):
            check(session.word(0x6287 + slot * 16 + color * 2) ==
                  int.from_bytes(palette[color * 2:color * 2 + 2], "little"),
                  "Cowboy palette buffer does not match original artwork")
        # The actual professor is loaded by the original room script. Verify its
        # actor definition, native animation bank and palette independently.
        professor = session.word(0x285B)
        check(professor != npc and session.word(professor + 0x60) == 0xC252,
              "Original professor actor missing")
        check(session.ram[professor + 2] == 0xC9, "Professor animation was replaced")
        check(session.word(0x1278 + session.ram[professor + 0x0C]) == 0xBA6B,
              "Professor palette was replaced")
        report["professor_preserved"] = True
        report["palette_id"] = hex(PALETTE_ID)

        paths = (
            ("north", 0, ((32, "Right"), (9, "Down"))),
            ("west", 3, ((24, "Left"), (14, "Down"), (8, "Right"))),
            ("south", 2, ((8, "Left"), (22, "Down"), (24, "Right"), (1, "Up"))),
            ("east", 1, ((24, "Right"), (22, "Up"), (8, "Left"))),
        )
        for facing, number, path in paths:
            for frames, button in path:
                run(frames, button)
            run(1, "B")
            run(150)
            check(session.word(npc + 6) == ((FRAME_OFFSET + number * 26) & 0xFFFF),
                  f"Wrong frame for {facing} conversation")
            check(session.word(npc + 8) == 0xF1, "Frame returned to shared graphics")
            screenshot = args.output_dir / f"cowboy-{facing}.png"
            session.screenshot(screenshot)
            report["events"].append({"frames": 1, "buttons": [], "capture": screenshot.name,
                                     "at_frame": session.frame})
            report["poses"].append({"facing": facing, "file": screenshot.name,
                                     "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()})
            for _ in range(64):
                if not session.word(npc + 0x0E) & 0x8000:
                    break
                run(5, "B")
                run(30)
            check(not session.word(npc + 0x0E) & 0x8000, "Conversation did not close")
            run(60)
            check((session.word(npc + 0x1A), session.word(npc + 0x1C)) == (544, 288),
                  "Cowboy moved after conversation")
            print(f"Private {facing} frame and repeat conversation passed", flush=True)
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report["total_frames"] = session.frame
        (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        session.close()


if __name__ == "__main__":
    main()

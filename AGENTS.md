# Evermore Unlimited

## Project intent

This is a Secret of Evermore SNES ROM-hacking project using the owner's local
ROM. Develop small, playable experiments with reproducible patches. The larger
story and gameplay design are undecided; do not introduce those decisions unless
the current task calls for them. Full decompilation is not a prerequisite.

The current experiment adds a stationary cowboy NPC to the opening Omnitopia
station. It has independent graphics and a palette, turns toward the player,
and says “Looks like the experiment worked!” The original adventure continues
through the robot fight and descent to Prehistoria.

## Read first

- `README.md`: setup, build, play, and verification commands.
- `docs/opening-npc.md`: script hooks, actor behavior, and original allocations.
- `docs/cowboy-graphics.md`: graphics formats, native hooks, and added allocations.
- `docs/character-editor.md`: editor, shared documents, CLI, and current limits.

## Source and generated files

- `tools/build_npc.py` validates the original ROM and builds the modified ROM,
  BPS patch, checksum, manifest, and artwork previews.
- `tools/character_rom.py` compiles versioned characters/scenes and installs scoped
  animation, patrol, palette, tile-pointer, and dialogue hooks.
- `tools/cowboy_graphics.py` retains compatibility helpers for the original art checks.
- `assets/characters/cowboy.json` is the editable artwork source: 32×32 idle/walk
  frames, a 16-color palette, `.` for transparency, and hexadecimal indices `1`–`f`.
  Facing order is north/east/south/west; the feet anchor is `(16, 32)`.
- `assets/scenes/opening-station.json` contains instances, dialogue and patrols.
- `tools/characters.py` and `tools/editor_server.py` expose the shared validated
  documents through the CLI and local visual editor. Preserve revision checks.
- `tools/libretro_session.py` supplies headless emulator input, observations,
  screenshots, and research save states. The verification scripts use it.
- `tests/test_build_npc.py` checks patch integrity and graphics encoding.

Keep `roms/`, `build/`, `tools/vendor/`, extracted original assets, emulator
binaries, and save states out of Git. Commit original artwork, code, and useful
technical documentation. Generated PNG previews are outputs, not artwork inputs.

## ROM workflow

- Read the clean, unheadered US ROM from `roms/original.sfc`. The accepted size
  and SHA-256 are defined in `tools/build_npc.py`; preserve strict validation.
- Never modify the original ROM. Rebuild `build/evermore-npc.sfc` and
  `build/evermore-npc.bps` from source; do not make output-only hex edits.
- Keep builds deterministic and maintain the SNES checksum, BPS CRCs, and manifest.
- Check expected original bytes at every hook and allocation contents before
  writing. Allocate new content in unused expanded space without overlapping
  existing scripts, text, graphics, or native code. Document new allocations.
- Preserve shared original graphics and palettes when adding custom characters.
  Trace references before changing a table entry; an apparent local edit may
  affect other actors or regions.
- Use the existing ROM format and engine for game changes. Keep emulator-only
  enhancements explicit when a task requests them.

## Reverse-engineering conventions

- Distinguish unheadered file offsets, native HiROM addresses, and packed script
  addresses. Native addresses add `$C00000` to file offsets; script listings use
  a separate `$800000` address convention. Use the builder's packing helpers.
- NPC template IDs, character definition indices, animation offsets, frame
  pointers, and tile IDs are different identifiers. Do not interchange them.
- For native 65816 hooks, establish accumulator/index widths, data/program bank,
  direct page, stack balance, flags, and register expectations at entry and exit.
  Preserve displaced instructions and unrelated actors' behavior. A relocated
  PHK selects the new code bank, which may differ from the intended source bank.
- Record confirmed addresses and formats with their supporting code or emulator
  observations. Label hypotheses and untested compatibility clearly.
- Existing references include SoEScriptDumper, Evermizer, and SoETilesViewer.
  Their relevant versions and links are in the technical notes. They are research
  tools, not mandatory build dependencies; verify findings against the local ROM.

## Build and verification

Run commands from the project root. Python 3.10+ and Pillow are required for the
build and previews. The optional emulator checks require a separately supplied
Snes9x libretro core; the pinned source version is documented in `README.md`.

```sh
python3 tools/build_npc.py
python3 -m unittest discover -s tests -v
python3 tools/verify_cowboy.py --core tools/vendor/snes9x_libretro.so
python3 tools/verify_npc.py --core tools/vendor/snes9x_libretro.so
python3 tools/verify_editor.py --core tools/vendor/snes9x_libretro.so
npm run test:editor
npm run test:browser
```

- For ROM, script, native-hook, or graphics changes, rebuild and run the relevant
  unit and emulator checks. Graphics changes need directional rendering and
  palette checks; changes affecting the opening need the escape/progression check.
- Inspect screenshots at native scale and enlarged with nearest-neighbor scaling.
  Automated reference checks alone cannot establish that the character looks right.
- Acceptance runs must start from a fresh boot and use controller input. Reading
  RAM for assertions is fine; do not force progression with RAM writes or old save
  states. Research save states are useful during investigation but can retain
  obsolete pointers and palettes after a ROM change.
- Keep meaningful integrity checks: independent BPS reconstruction and tile
  decoding, source preservation, deterministic output, and narrow original-ROM
  change ranges. Do not relax a failing check without understanding the failure.
- Documentation-only changes do not require rebuilding or running the emulator.
- Report what was verified and any remaining limits. Do not claim full-campaign,
  other-region, other-patch, or physical-hardware compatibility from opening tests.

Keep build/play instructions and technical notes current when their behavior or
allocations change. Leave generated evidence in `build/` and link useful artifacts
in the completion message.

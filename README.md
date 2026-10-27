# Evermore Unlimited

A local character and NPC editor for Secret of Evermore. Draw original pixel
artwork, animate four facings, place characters in the opening space station,
write dialogue and patrols, and build a playable patch from your original ROM.

The default scene still has one stationary cowboy saying **“Looks like the
experiment worked!”** The larger adventure and expansion design remain open.

## Open the editor

Requires Python 3.10+ and Pillow (`python3-pil` on Ubuntu, or `python3 -m pip
install Pillow` in a virtual environment). From the project root:

```sh
python3 tools/characters.py serve
```

Open **http://127.0.0.1:8765** if a browser does not open automatically. Add
`--no-browser` to suppress opening a browser, or `--port 8766` to change ports.
Node/npm are needed only for JavaScript tests; `npm start` is an alternative
editor launch command.

- **Characters:** create/duplicate characters, draw, erase, fill, pick colors,
  select/copy/paste pixels, mirror, undo, and redo.
- **Animations:** edit idle/walk clips for north/east/south/west, with 1–16 frames
  per clip, individual durations, playback, grid, and onion skin.
- **Palette:** 15 opaque colors plus transparency, previewed at SNES precision.
  Import/export indexed PNG sheets and versioned JSON.
- **Opening station:** add/remove instances, drag positions and waypoints on the
  grid, edit facing/dialogue, and simulate patrols with pauses.
- **Save & build ROM:** save source files and generate the patched ROM, BPS,
  manifest, and sprite sheets. Errors keep the editor usable.

**Capture ROM reference** makes a private station background using the optional
emulator below. Scene editing works without it. **Open Snes9x** launches an
installed `snes9x` or `snes9x-gtk` from a desktop session; otherwise open the ROM
manually. See [the editor guide](docs/character-editor.md) for controls and CLI use.

## Build and play

Keep your clean, **unheadered US** ROM at `roms/original.sfc`. Build in the editor
or run either command:

```sh
python3 tools/build_npc.py
python3 tools/characters.py build
```

Outputs:

- `build/evermore-npc.sfc` — playable modified ROM.
- `build/evermore-npc.bps` — patch for the supported original.
- `build/manifest.json` — input/output hashes, checksum, document revisions,
  compiled scene, frame records, and ROM allocations.
- `build/<character>-idle.png` and `build/<character>-walk.png` — directional
  sheets with embedded frame counts/durations for PNG round trips.

Start a **new game**. After “Now what?” in the opening station, the default cowboy
stands down and right of the boy. Walk up and press SNES **B**; advance dialogue
pages with B. The Bazooka chest, robot fight, escape, landing, and dog reunion
continue normally. The result needs no emulator overlay.

The source is preserved and unsupported/patched inputs are rejected. Supported
size: 3,145,728 bytes; SHA-256:

```text
17c864a76d498feb6479eee8e7d6807b951c66225033228622bb66754baab1db
```

The output expands to 4 MiB. ROMs, references, screenshots, emulator binaries,
and save states remain outside version control.

## Shared source files

- `assets/characters/<id>.json`: original artwork, palette, and animation.
- `assets/scenes/opening-station.json`: NPC placement, dialogue, and routes.
- `schemas/`: version 1 schemas for artists, agents, and external tools.

Browser and CLI share validation and revision-checked atomic saves. External
changes refresh clean documents; conflicts preserve unsaved edits for explicit
reload or export. Generated PNGs are previews, not artwork inputs. The original
`assets/cowboy.json` migrated to `assets/characters/cowboy.json`.

## Verification

```sh
python3 -m unittest discover -s tests -v
npm ci
npm run test:editor
npx playwright install chromium
npm run test:browser
```

Browser tests use isolated copies under `build/browser-tests/` and never change
your character/scene files. Reports/screenshots go to `build/editor-browser-report.json`
and `build/editor-*-browser.png`. Set `CHROMIUM_PATH` to use existing Chromium.

Optional fresh-boot emulator checks:

```sh
python3 tools/verify_cowboy.py --core tools/vendor/snes9x_libretro.so
python3 tools/verify_npc.py --core tools/vendor/snes9x_libretro.so
python3 tools/verify_editor.py --core tools/vendor/snes9x_libretro.so
```

The first two check the default scene: four talk facings, private palette,
original professor, repeated dialogue, and progression through playable Prehistoria.
The third builds an isolated two-character scene and checks separate palettes,
walking animation, and patrol pause/resume during dialogue. All acceptance runs
start fresh and use controller inputs, without RAM writes or old save states.
Customized scenes may require different input routes for playtesting.

Evidence goes to `build/cowboy-facings/`, `build/verification/`, and
`build/editor-runtime/`. Integrity tests independently decode tiles/BPS, check
determinism/checksums, and preserve unrelated original ROM data.

Luna is available as an alternative headless backend for the opening check:

```sh
python3 tools/verify_npc.py --luna tools/vendor/luna/target/release/luna \
  --output-dir build/luna/verification
```

See [the Luna trial](docs/luna.md) for its pinned build and interface details.

Build the pinned optional emulator (C/C++ compiler and Make required):

```sh
git clone https://github.com/libretro/snes9x.git tools/vendor/snes9x
git -C tools/vendor/snes9x checkout fae2fea08f74180759ef540ee94259213f503480
make -C tools/vendor/snes9x/libretro -j4
python3 tools/verify_editor.py --core tools/vendor/snes9x/libretro/snes9x_libretro.so
```

Current scope: the opening station, eight instances using at most two distinct
custom characters, stationary or waypoint movement. Routes do not add collision
avoidance/pathfinding; test edited placements in game. Full-campaign, other-region,
other-patch, old-state, and physical-SNES compatibility are unverified.
See [script notes](docs/opening-npc.md) and [compiler notes](docs/cowboy-graphics.md).

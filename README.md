# Evermore Unlimited

A first Secret of Evermore ROM-hacking experiment: an additional, stationary NPC
in the opening space station, before the descent to Prehistoria.

The NPC is a cowboy with independent pixel graphics, directional frames, and a
private palette. It says **“Looks like the experiment worked!”** Talking does not
give items or change progression. This is a temporary test character, with no
larger story or gameplay design attached. The original professor is unchanged.

## Build and play

Requires Python 3.10 or newer and Pillow (`python3-pil` on Ubuntu, or
`python3 -m pip install Pillow` in a virtual environment). Keep your clean, **unheadered US** ROM at
`roms/original.sfc`, then run from the project root:

```sh
python3 tools/build_npc.py
```

Outputs:

- `build/evermore-npc.sfc` — open this in your SNES emulator.
- `build/evermore-npc.bps` — patch for the same clean US ROM.
- `build/manifest.json` — input/output hashes, checksum, and experiment details.
- `build/cowboy-sheet.png` — indexed sprite sheet, north/east/south/west.
- `build/cowboy-preview.png` — enlarged pixel preview of the same artwork.

Start a **new game** and play through the introduction. When the boy says
“Now what?” and you gain control in the station, the extra character stands
down and to the right of him. Walk over and use the normal interaction button
(SNES **B**). Close the conversation with B; it can be repeated. The Bazooka
chest and robot encounter proceed normally.

The builder preserves the original ROM and rejects unsupported or previously
patched inputs. The supported source is 3,145,728 bytes, SHA-256:

```text
17c864a76d498feb6479eee8e7d6807b951c66225033228622bb66754baab1db
```

The output is expanded to 4 MiB. ROMs, extracted data, emulator binaries,
screenshots, and saves are kept out of version control.

## Checks and screenshots

```sh
python3 -m unittest discover -s tests -v
```

Tests cover input validation, unchanged original bytes outside the intended
patch sites, deterministic builds, SNES checksums, and BPS reconstruction.
ROM-dependent tests skip when the private original is absent.

The graphics checks also decode the inserted SNES tiles back into pixels and
compare them to the authored frames. They verify that the original professor's
definition, palette, animation data, and graphics remain unchanged.

The optional emulator check requires Pillow and a Snes9x libretro core:

```sh
python3 tools/verify_npc.py --core tools/vendor/snes9x_libretro.so
python3 tools/verify_cowboy.py --core tools/vendor/snes9x_libretro.so
```

It boots a new game and uses controller inputs, without loading a save state or
writing emulator RAM. It reaches the NPC, repeats the dialogue three times,
opens the original Bazooka chest, defeats both robots, completes the escape,
and checks restored player control and dog availability in Prehistoria.
Screenshots and the input log are written to `build/verification/`.
The second check walks around the cowboy and talks from all four sides, checks
the private graphics and palette references, and verifies the original professor
still uses its original animation and palette. Its screenshots and input log are
written to `build/cowboy-facings/`.

The verification uses fixed input timings for the Snes9x core listed below.
Other cores may require different timings. Screenshots should also be inspected
to confirm rendering and dialogue; the automated checks alone cannot judge them.

To rebuild the optional emulator core (C/C++ compiler and Make required):

```sh
git clone https://github.com/libretro/snes9x.git tools/vendor/snes9x
git -C tools/vendor/snes9x checkout fae2fea08f74180759ef540ee94259213f503480
make -C tools/vendor/snes9x/libretro -j4
python3 tools/verify_npc.py --core tools/vendor/snes9x/libretro/snes9x_libretro.so
```

## How the patch works

The build inserts a call immediately before the original opening script returns
player control. The new initializer runs the displaced instruction, creates one
additional actor, freezes its wandering AI, and attaches an ordinary talk script.
The original script then resumes. Text and new scripts occupy the added ROM space.
No emulator extension is required to play the resulting ROM.

See [the technical notes](docs/opening-npc.md) for patch locations, reference
versions, and verification limits. This prototype was checked through the opening
and arrival in Prehistoria; a complete campaign playthrough has not been tested.

## Edit the cowboy

The editable source is [assets/cowboy.json](assets/cowboy.json): four 32×32 grids
and a 16-color palette. A dot is transparent; `1`–`f` select palette colors. The
feet anchor is `(16, 32)`. Edit the grids or colors and rebuild to see the change.
The PNG files are generated previews; the builder reads the JSON source.

See [the graphics notes](docs/cowboy-graphics.md) for the native hooks and private
ROM allocations. Restart from a fresh game after changing the graphics; save
states made with earlier ROM versions can retain old references and palettes.

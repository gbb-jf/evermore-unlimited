# Evermore Unlimited

A first Secret of Evermore ROM-hacking experiment: an additional, stationary NPC
in the opening space station, before the descent to Prehistoria.

The NPC uses an existing professor sprite and says **“Looks like the experiment
worked!”** Talking does not give items or change progression. This is a temporary
test character, with no larger story or gameplay design attached.

## Build and play

Requires Python 3.10 or newer. Keep your clean, **unheadered US** ROM at
`roms/original.sfc`, then run from the project root:

```sh
python3 tools/build_npc.py
```

Outputs:

- `build/evermore-npc.sfc` — open this in your SNES emulator.
- `build/evermore-npc.bps` — patch for the same clean US ROM.
- `build/manifest.json` — input/output hashes, checksum, and experiment details.

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

The optional emulator check requires Pillow and a Snes9x libretro core:

```sh
python3 tools/verify_npc.py --core tools/vendor/snes9x_libretro.so
```

It boots a new game and uses controller inputs, without loading a save state or
writing emulator RAM. It reaches the NPC, repeats the dialogue three times,
opens the original Bazooka chest, defeats both robots, completes the escape,
and checks restored player control and dog availability in Prehistoria.
Screenshots and the input log are written to `build/verification/`.

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

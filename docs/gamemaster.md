# Opening station gamemaster

The opt-in experiment replaces the first robot encounter with a native dialogue
menu offering **Thraxx, Salabog, and Magmar**. Open the Bazooka chest after talking
to the cowboy. The gamemaster greets the boy by his current character name and
comments on it; this works before the first save. Advance pages and confirm with
SNES B, and select with Up/Down. The default build and editor retain the robots.

## Build and launch

Use the original US ROM and prerequisites in [README](../README.md). Build the
separate experiment without replacing the editor's normal output:

```sh
python3 tools/build_npc.py --gamemaster --output-dir build/gamemaster
```

The ROM works offline with a friendly scripted name comment. Live commentary
requires local Ollama with an installed model and the scoped Luna bridge:

```sh
python3 tools/setup_gamemaster_luna.py --build both
python3 tools/gamemaster.py --model YOUR_INSTALLED_MODEL
```

Set up the pinned Luna checkout using [Luna setup](luna.md) first. On Linux the
GUI requires ALSA and udev development packages. The setup script checks the
pinned commit, applies the tracked patch idempotently, copies the tracked bridge
source, and builds the requested packages (`cli`, `gui`, or `both`). The launcher
requires a desktop display. `--luna PATH` selects a different patched GUI;
`--endpoint URL` changes the default `http://127.0.0.1:11434` Ollama endpoint.
There is no automatic model download or model selection.

To play with the offline comment, launch the built ROM directly:

```sh
tools/vendor/luna/target/release/luna-gui build/gamemaster/evermore-npc.sfc
```

Ollama writes only a short, kind name comment. The ROM owns the three choices,
attacks, damage, victory and subsequent escape. Failure or 600 engine yields
(about ten seconds at normal speed) selects the scripted fallback. The companion
also discards model responses taking ten wall-clock seconds or longer. Fast
headless emulation may reach the ROM fallback before a real model responds.

## Station combat

These are small station adaptations using original actor graphics rather than
relocations of the complete later-game boss arenas. Shoot the exposed Thraxx
heart while its claws converge, dodge Salabog's aimed fire, or move away from
Magmar's jumping slam. Each instance has 600 HP and locally reduced defenses for
the opening Bazooka. Their original definitions and later story-dead flags stay
unchanged. Victory removes the temporary actors and calls the original station
escape, followed by the landing and dog reunion.

The cowboy leaves when combat starts: the original bosses reserve sprite
palette slots that would recolor a bystander. His conversation before the chest
and the normal build's interaction remain available.

## ROM and bridge layout

All file offsets below are unheadered; native addresses add `$C00000`.

| File offset | Purpose |
| --- | --- |
| `$1BC4DD` | Five-byte call/end after the original Bazooka award |
| `$330000` | Offline text and three-choice menu |
| `$338000` | Encounter bytecode, movement, damage and cleanup |
| `$33F000` | `EVERMORE-GM-0001` opt-in signature |
| `$344000` | Native text resolver shim |
| `$0CCCF5` | JML replacing `STA $26; LDA #$00F5` in the relocated resolver |
| `$35FFF9`, `$35FFFC` | Reserved final entries in the relocated text table |

The manifest records exact allocation ends. Allocations check erased bytes and
overlaps; hooks check expected bytes. The original ROM is strictly validated,
and builds retain deterministic checksums and independently reconstructible BPS.

The shim enters with 16-bit A/X and A holding the text ID. It preserves the stack
and status while checking the dedicated ID, magic, version and ready status.
For a ready reply it returns `$7F:F000` through direct-page `$22/$24`; otherwise
it reproduces the displaced instructions and continues at `$8CCCFA`. It does not
alter the character graphics hooks or original text data.

WRAM `$7E:28E0`–`$7E:28FB` holds the opening-only protocol and actor handles:
magic, version, request, status, choice, elapsed count, boss, two claws, attack
step, target X/Y and projectile, as consecutive 16-bit words. Status values are
1=request, 2=reply ready, 3=fallback, 4=combat, 5=victory. These temporary station
words are not a persistent save format; other-room ownership is not established.
`$7F:F000`–`$7F:F1FF` is the bounded dialogue payload used only when the scoped
resolver selects it. Its compatibility outside the opening is untested.

The bridge is enabled only when both the ROM signature and
`LUNA_EVERMORE_BRIDGE` directory exist, and accepts requests only while the
original opening flag is set. It runs at emulator frame boundaries in
the shared API used by CLI and GUI. A private temporary directory contains
atomic request/reply JSON files. Session identity, reset/load generation and ROM
request number must match. Reset invalidates pending requests. Publication
copies validated text before setting ready status; the only writes are the
512-byte text area and two-byte status. There is no new general memory-write
interface. Existing verification sessions remain read-only.

## Verification

```sh
python3 -m unittest discover -s tests -v
cargo +stable test --manifest-path tools/vendor/luna/Cargo.toml \
  --locked -p luna-api evermore_gamemaster
python3 tools/verify_gamemaster.py --choice 0
python3 tools/verify_gamemaster.py --choice 1 --fixture
python3 tools/verify_gamemaster.py --choice 2 --fixture
```

`--fixture` exercises the actual dialogue bridge using deterministic commentary,
without Ollama. Each acceptance run boots fresh, enters `rr` through the naming
screen, talks to the cowboy, selects the requested boss, takes an attack, fights
with controller input, and checks cleanup, escape, landing, reunion and movement.
Reports, read-only RAM observations, native screenshots and 4× nearest-neighbor
screenshots go to `build/gamemaster/verification/<boss>/`. Failure states are
research evidence only and are never used to start acceptance runs.

Fixture success does not establish a real installed model's output or latency.
Opening checks do not establish full-campaign, other-patch, other-region,
physical-hardware or old-save-state compatibility. A named save/load round trip
and interactive desktop play need separate acceptance evidence.

Verified on 2026-10-27: all 52 Python tests, five Rust bridge tests, editor unit
and browser checks, and the three fresh-boot boss runs passed. The pinned CLI and GUI both
compiled with the bridge. Native and 4× screenshots were visually inspected for
name substitution, commentary, the three-choice menu, boss graphics, attacks,
and restored Prehistoria play. The tested ROM SHA-256 is
`d6538158158bee878586a4622e1d9058ade665760bb8bee88ff000a16c3e0517`.

| Boss | Commentary source | Frames through restored control | Report |
| --- | --- | ---: | --- |
| Thraxx | Offline fallback | 39,233 | `build/gamemaster/verification/thraxx/report.json` |
| Salabog | Fixture through Luna bridge | 39,632 | `build/gamemaster/verification/salabog/report.json` |
| Magmar | Fixture through Luna bridge | 38,415 | `build/gamemaster/verification/magmar/report.json` |

Each run confirmed a damaging signature attack, a successful dodge, controller
defeat, actor cleanup, unchanged later boss flags, station escape, dog reunion,
and restored movement. No Ollama server was listening locally during acceptance;
real model output and response latency remain unverified.

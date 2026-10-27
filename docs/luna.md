# Luna emulator trial

[Luna](https://github.com/k0b3n4irb/luna) provides a headless CLI, a stdio MCP
server, and a separate desktop application. The local trial uses version
`1.41.0+6e2e3b2`, commit `6e2e3b27c015c61ab3591abb22a1968dd83c0567`.
Source, binaries, and private evidence stay in ignored directories.

## Build the headless emulator

Requires Git and Rust/Cargo with Rust 1.95 or newer. This trial compiled with
the installed stable Rust 1.97.0; `+stable` bypasses the upstream toolchain file,
which otherwise installs Rust 1.95 and additional development components.

```sh
git clone https://github.com/k0b3n4irb/luna.git tools/vendor/luna
git -C tools/vendor/luna checkout 6e2e3b27c015c61ab3591abb22a1968dd83c0567
cargo +stable build --manifest-path tools/vendor/luna/Cargo.toml \
  --release --locked -p luna-cli
tools/vendor/luna/target/release/luna --version
python3 tools/build_npc.py
mkdir -p build/luna
```

Render the opening title sequence from a fresh boot, without loading battery
RAM or a save state:

```sh
tools/vendor/luna/target/release/luna state build/evermore-npc.sfc \
  --until-frame 1500 --screenshot build/luna/title.png \
  --out build/luna/title-state.json
```

For an interactive agent session, start the stdio MCP server:

```sh
tools/vendor/luna/target/release/luna mcp --rom build/evermore-npc.sfc
```

The server exposes `set_joypad`, `step_kind`, `state`, `screenshot`, and
`peek_memory`. `step_kind` with `kind: "frames"` advances by a requested number
of observed frame transitions; inspect `state.scheduler.frame_count` for the
actual count. During the initial boot in this trial, a request for 1,500
transitions advanced the counter from 0 to 1,501. Record actual frame counters
when replaying input. Joypad masks use SNES register order: B `$8000`, Start
`$1000`, Up `$0800`, Down `$0400`, Left `$0200`, Right `$0100`.

The CLI supports frame-indexed input with `--input "1500:0x1000,1501:0"`,
or `--input @path/to/script.input`. These change controller input only.

## Opening verification

```sh
python3 tools/verify_npc.py --luna tools/vendor/luna/target/release/luna \
  --output-dir build/luna/verification
```

`tools/luna_session.py` connects to the native stdio MCP server using Python's
standard library. The opening recipe starts a fresh game, supplies controller
input, and reads WRAM for assertions; it never loads save states or writes RAM.
Requests are bounded to 300 frames and time out after 60 seconds. The report
records the Luna version, executable/ROM hashes, actual frame counters, inputs,
and screenshot hashes under `build/luna/verification/`.

Verified on 2026-10-27: the complete recipe passed across 40,446 emulated
frames. The cowboy appeared at `(544, 288)`, completed three conversations
without wandering, and the original robot fight, escape, landing, dog reunion,
and resumed player movement passed. Seven screenshots were captured; station,
dialogue, and Prehistoria screenshots were visually inspected at native scale
and 4× nearest-neighbor scale. All 39 project unit tests also passed.

The tested ROM SHA-256 is
`75f10cd5dcdb6a78fa9c081eb0296951915654c7cd1bd3149c944201e9017317`.
Evidence: `build/luna/verification/report.json` and the PNG files beside it.

## Scope

The directional graphics and editor verification scripts and editor reference
capture still use the pinned Snes9x libretro core. Luna's native CLI/MCP
interface is separate from libretro;
its executable cannot be passed as `--core`. The editor's **Open Snes9x** button
still launches Snes9x. A desktop Luna window requires the separate `luna-gui`
package and a desktop display; this headless trial does not test that frontend.

Opening tests do not establish full-campaign, other-region, other-patch,
old-save-state, or physical-hardware compatibility.

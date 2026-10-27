"""Headless Luna session over its native stdio MCP interface.

Uses controller input and read-only observations. No libretro core, third-party
Python MCP package, battery files, or saved states are needed.
"""

import base64
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time


class Session:
    BUTTONS = {"B": 0x8000, "Y": 0x4000, "Select": 0x2000, "Start": 0x1000,
               "Up": 0x0800, "Down": 0x0400, "Left": 0x0200, "Right": 0x0100,
               "A": 0x0080, "X": 0x0040, "L": 0x0020, "R": 0x0010}

    def __init__(self, executable, rom):
        self.frame = 0
        self._ident = 0
        self._read_buffer = b""
        self._stderr = tempfile.TemporaryFile(mode="w+t")
        self._selector = selectors.DefaultSelector()
        self.process = None
        try:
            self.process = subprocess.Popen(
                [str(Path(executable).resolve()), "mcp"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self._stderr)
            self._selector.register(self.process.stdout, selectors.EVENT_READ)
            result = self._rpc("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "evermore-verification", "version": "1"}})
            self.info = result["serverInfo"]
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._call("load_rom", {"path": str(Path(rom).resolve())})
            self.frame = self.state()["scheduler"]["frame_count"]
        except Exception:
            self.close()
            raise

    def _send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def _rpc(self, method, params):
        self._ident += 1
        self._send({"jsonrpc": "2.0", "id": self._ident,
                    "method": method, "params": params})
        deadline = time.monotonic() + 60
        while True:
            while b"\n" not in self._read_buffer:
                timeout = deadline - time.monotonic()
                if timeout <= 0 or not self._selector.select(timeout=timeout):
                    raise RuntimeError(f"Luna timed out responding to {method}")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    self._stderr.seek(0)
                    raise RuntimeError(f"Luna exited before responding: {self._stderr.read()[-4000:]}")
                self._read_buffer += chunk
            line, self._read_buffer = self._read_buffer.split(b"\n", 1)
            response = json.loads(line)
            if response.get("id") == self._ident:
                if "error" in response:
                    raise RuntimeError(f"Luna RPC error: {response['error']}")
                return response["result"]

    def _call(self, name, arguments=None):
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            raise RuntimeError(f"Luna {name} failed: {result.get('content')}")
        if "structuredContent" in result:
            return result["structuredContent"]
        return json.loads(next(item["text"] for item in result["content"] if item["type"] == "text"))

    def state(self):
        return self._call("state")["state"]

    def run(self, frames, *buttons):
        if frames < 0:
            raise ValueError("Frame count must be nonnegative")
        self._call("set_joypad", {"port": 0, "mask": sum(self.BUTTONS[b] for b in set(buttons))})
        # Bound each request so emulator failures time out and long cutscenes
        # do not need an unbounded RPC wait. Keep the same input between chunks.
        remaining = frames
        while remaining > 0:
            count = min(remaining, 300)
            result = self._call("step_kind", {"kind": "frames", "count": count,
                                              "max_steps": max(1000000, count * 100000)})
            current = self.state()["scheduler"]["frame_count"]
            advanced = current - self.frame
            self.frame = current
            # A long instruction/DMA can cross more than one frame. Account
            # for the actual PPU counter instead of assuming one per step.
            if advanced < count or result.get("kind") != "step" or result.get("interrupted"):
                raise RuntimeError(f"Luna stopped early after {advanced}/{count} frames: {result}")
            remaining -= advanced

    def word(self, address):
        if not 0 <= address < 0x1ffff:
            raise ValueError("WRAM word address out of range")
        data = self._call("peek_memory", {"bank": 0x7e + (address >> 16),
                                          "offset": address & 0xffff, "count": 2})["bytes"]
        return int.from_bytes(bytes(data), "little")

    @property
    def ram(self):
        # Immutable bytes preserve read-only assertions used by the recipes.
        result = self._call("wram_snapshot", {"include_data": True})
        return base64.b64decode(result["wram_base64"])

    def screenshot(self, path):
        # Match the libretro frontend's one extra, input-free capture frame.
        self.run(1)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(self._call("screenshot")["png_base64"]))

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process.stdin.close()
            self.process.stdout.close()
        self._selector.close()
        self._stderr.close()

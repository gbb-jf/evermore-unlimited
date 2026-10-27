"""Loopback-only workshop server. Uses the same Store and builder as the CLI."""

import base64
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
from urllib.parse import urlparse, parse_qs
import webbrowser

from character_model import ROOT, Store, Conflict, Invalid, MAX_INSTANCES, MAX_PALETTES, blank_character, export_sheet, import_sheet, validate
from emulator_session import DEFAULT_LUNA


def serve(root=ROOT, port=8765, open_browser=True):
    root = Path(root).resolve()
    store = Store(root)
    token = secrets.token_hex(24)
    state = {"running": False, "action": None, "status": "idle"}
    state_lock = threading.Lock()
    web_root = ROOT / "editor"

    def job(action):
        with state_lock:
            if state["running"]:
                raise Conflict("A build or reference capture is already running")
            state.update(running=True, action=action, status="running", error=None)

        def work():
            try:
                if action == "build":
                    command = [sys.executable, str(ROOT / "tools/characters.py"), "--root", str(root), "--json", "build"]
                else:
                    command = [sys.executable, str(ROOT / "tools/capture_station.py"), "--root", str(root),
                               "--luna", str(DEFAULT_LUNA)]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                        timeout=600 if action == "capture" else 180)
                with state_lock:
                    state.update(running=False, status="passed" if result.returncode == 0 else "failed",
                                 output=result.stdout, error=result.stderr or (result.stdout if result.returncode else None))
            except Exception as error:
                with state_lock:
                    state.update(running=False, status="failed", error=str(error))
        threading.Thread(target=work, daemon=True).start()
        return dict(state)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send(self, data, status=200, content_type="application/json"):
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def guarded(self, method):
            try:
                method()
            except FileNotFoundError as error:
                self.send({"error": f"Not found: {error.filename or str(error)}"}, 404)
            except Conflict as error:
                self.send({"error": str(error), "conflict": True}, 409)
            except (Invalid, ValueError, OSError, KeyError, TypeError) as error:
                self.send({"error": str(error), "errors": getattr(error, "errors", [])}, 400)

        def do_GET(self):
            self.guarded(self.get)

        def get(self):
            parsed = urlparse(self.path)
            path = parsed.path
            # Disallow DNS rebinding of the writable local service.
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self.send({"error": "Use the localhost editor address"}, 403)
                return
            if path == "/api/project":
                reference = root / "build/editor/station.json"
                manifest = root / "build/manifest.json"
                self.send({"characters": store.list(), "scene": store.get("scenes", "opening-station"),
                           "token": token, "limits": {"instances": MAX_INSTANCES, "palettes": MAX_PALETTES},
                           "reference": json.loads(reference.read_text()) if reference.exists() else None,
                           "build": json.loads(manifest.read_text()) if manifest.exists() else None})
            elif path == "/api/job":
                with state_lock:
                    self.send(dict(state))
            elif path.startswith("/api/doc/"):
                _, _, _, kind, ident = path.split("/")
                self.send(store.get(kind, ident))
            elif path.startswith("/api/export/"):
                ident = path.split("/")[-1]
                mode = parse_qs(parsed.query).get("mode", ["idle"])[0]
                if mode not in ("idle", "walk"):
                    raise ValueError("Unknown animation mode")
                self.send(export_sheet(store.get("characters", ident)["document"], mode), content_type="image/png")
            elif path == "/api/reference.png":
                self.send((root / "build/editor/station.png").read_bytes(), content_type="image/png")
            elif path == "/api/schema/character":
                self.send((ROOT / "schemas/character.schema.json").read_bytes())
            elif path == "/api/schema/scene":
                self.send((ROOT / "schemas/scene.schema.json").read_bytes())
            else:
                relative = "index.html" if path == "/" else path.lstrip("/")
                target = (web_root / relative).resolve()
                if not target.is_relative_to(web_root.resolve()) or not target.is_file():
                    self.send({"error": "Not found"}, 404)
                    return
                self.send(target.read_bytes(), content_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")

        def do_POST(self):
            self.guarded(self.post)

        def do_PUT(self):
            self.guarded(self.post)

        def post(self):
            origin = self.headers.get("Origin")
            valid_origins = (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
            if self.headers.get("X-Editor-Token") != token or (origin and origin not in valid_origins):
                self.send({"error": "Reload the local editor before saving"}, 403)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 4 * 1024 * 1024 or self.headers.get_content_type() != "application/json":
                raise ValueError("Expected a JSON request of at most 4 MiB")
            body = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            path = urlparse(self.path).path
            if path.startswith("/api/doc/"):
                _, _, _, kind, ident = path.split("/")
                validate(body["document"], kind)
                if body["document"].get("id") != ident:
                    raise ValueError("Document ID must match its URL")
                self.send(store.save(kind, body["document"], body.get("revision")))
            elif path == "/api/create":
                if body.get("source"):
                    document = deepcopy(store.get("characters", body["source"])["document"])
                    document.update(id=body["id"], name=body.get("name") or body["id"])
                else:
                    document = blank_character(body["id"], body.get("name"))
                self.send(store.save("characters", document, None), 201)
            elif path == "/api/import-png":
                self.send({"document": import_sheet(body["document"], base64.b64decode(body["png"], validate=True),
                                                     body.get("mode", "idle"), body.get("mapping", "exact"))})
            elif path in ("/api/build", "/api/capture"):
                self.send(job("build" if path.endswith("build") else "capture"), 202)
            elif path == "/api/play":
                local_gui = DEFAULT_LUNA.with_name("luna-gui")
                executable = str(local_gui) if local_gui.is_file() else shutil.which("luna-gui")
                rom = root / "build/evermore-npc.sfc"
                if not executable or not rom.is_file():
                    raise ValueError("Build the ROM and install Luna's desktop app (luna-gui) first. See docs/luna.md.")
                if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                    raise ValueError(f"This server has no desktop display. Open {rom} in Luna, or start the editor from a desktop terminal.")
                subprocess.Popen([executable, str(rom)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                self.send({"launched": True})
            else:
                self.send({"error": "Not found"}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Character workshop: http://127.0.0.1:{port}", flush=True)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

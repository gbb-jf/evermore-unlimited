"""Versioned character documents shared by the editor, CLI, and ROM compiler."""

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
FACING_ORDER = ("north", "east", "south", "west")
MODES = ("idle", "walk")
SLUG = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
EMPTY = ["." * 32 for _ in range(32)]
MAX_INSTANCES = 8
MAX_PALETTES = 2  # Five native dynamic slots minus professor, Carltron, robots.


@contextmanager
def project_lock(root):
    """Coordinate CLI and browser writers, including separate Python processes."""
    import fcntl
    assets = Path(root) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    with (assets / ".editor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Invalid(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(f"{e['field']}: {e['message']}" for e in errors))


class Conflict(ValueError):
    pass


def canonical(document):
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()


def revision(data):
    return hashlib.sha256(data).hexdigest()


def validate(document, kind="characters"):
    errors = []

    def error(field, message):
        errors.append({"field": field, "message": message})

    def integer(value, lo, hi):
        return type(value) is int and lo <= value <= hi

    if not isinstance(document, dict):
        raise Invalid([{"field": "$", "message": "Expected an object"}])
    if document.get("version") != 1:
        error("version", "Expected version 1")
    if not isinstance(document.get("id"), str) or not SLUG.fullmatch(document["id"]):
        error("id", "Use a lowercase ID starting with a letter, followed by letters, numbers or hyphens (max 48)")
    name = document.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 40:
        error("name", "Use a nonempty name of at most 40 characters")
    if kind == "characters":
        if not isinstance(document.get("description", ""), str):
            error("description", "Expected text")
        palette = document.get("palette")
        if not isinstance(palette, list) or len(palette) != 16:
            error("palette", "Exactly 16 colors are required")
        else:
            if palette[0] != "transparent":
                error("palette.0", "Index 0 must be transparent")
            for i, color in enumerate(palette[1:], 1):
                if not isinstance(color, str) or not COLOR.fullmatch(color):
                    error(f"palette.{i}", "Expected #RRGGBB")
        animations = document.get("animations", {})
        if not isinstance(animations, dict):
            animations = {}
        for mode in MODES:
            directions = animations.get(mode, {})
            if not isinstance(directions, dict):
                directions = {}
            for direction in FACING_ORDER:
                path = f"animations.{mode}.{direction}"
                frames = directions.get(direction)
                if not isinstance(frames, list) or not 1 <= len(frames) <= 16:
                    error(path, "Each clip needs 1–16 frames")
                    continue
                for i, frame in enumerate(frames):
                    if not isinstance(frame, dict):
                        error(f"{path}.{i}", "Expected a frame object")
                        continue
                    if not integer(frame.get("duration"), 1, 120):
                        error(f"{path}.{i}.duration", "Use 1–120 game ticks (60 ticks per second)")
                    pixels = frame.get("pixels")
                    if not isinstance(pixels, list) or len(pixels) != 32:
                        error(f"{path}.{i}.pixels", "Expected 32 pixel rows")
                    else:
                        for y, row in enumerate(pixels):
                            if not isinstance(row, str) or len(row) != 32 or any(c not in ".123456789abcdef" for c in row):
                                error(f"{path}.{i}.pixels.{y}", "Each row needs 32 palette indices: . or 1–f")
    elif kind == "scenes":
        if document.get("id") != "opening-station":
            error("id", "Only the opening-station scene is supported")
        npcs = document.get("npcs")
        if not isinstance(npcs, list) or not 0 <= len(npcs) <= MAX_INSTANCES:
            error("npcs", f"Use 0–{MAX_INSTANCES} NPC instances")
        else:
            ids = set()
            for i, npc in enumerate(npcs):
                path = f"npcs.{i}"
                if not isinstance(npc, dict):
                    error(path, "Expected an NPC object")
                    continue
                ident = npc.get("id")
                if not isinstance(ident, str) or not SLUG.fullmatch(ident) or ident in ids:
                    error(path + ".id", "Use a unique lowercase ID")
                ids.add(ident if isinstance(ident, str) else "")
                character = npc.get("character")
                if not isinstance(character, str) or not SLUG.fullmatch(character):
                    error(path + ".character", "Expected a character ID")
                text = npc.get("dialogue")
                if not isinstance(text, str) or len(text) > 1000 or any(c != "\n" and not 32 <= ord(c) <= 126 for c in text):
                    error(path + ".dialogue", "Use up to 1000 printable English characters and line breaks")
                if npc.get("facing") not in FACING_ORDER:
                    error(path + ".facing", "Choose north, east, south or west")
                positions = [(path + ".position", npc.get("position"))]
                movement = npc.get("movement", {})
                if not isinstance(movement, dict):
                    movement = {}
                if movement.get("mode") not in ("stationary", "patrol"):
                    error(path + ".movement.mode", "Choose stationary or patrol")
                route = movement.get("waypoints", [])
                if not isinstance(route, list) or len(route) > 16:
                    error(path + ".movement.waypoints", "Use at most 16 waypoints")
                else:
                    if movement.get("mode") == "patrol" and len(route) < 2:
                        error(path + ".movement.waypoints", "Patrols need at least two waypoints")
                    for j, point in enumerate(route):
                        at = path + f".movement.waypoints.{j}"
                        positions.append((at, point))
                        if not isinstance(point, dict) or not integer(point.get("pause", 30), 0, 120):
                            error(at + ".pause", "Use 0–120 pause ticks")
                for field, position in positions:
                    if not isinstance(position, dict) or not integer(position.get("x"), 400, 592) or not integer(position.get("y"), 248, 320):
                        error(field, "Use the station floor: x=400–592, y=248–320")
                    elif position["x"] % 8 or position["y"] % 8:
                        error(field, "Positions snap to the 8-pixel grid")
            if len({n.get("character") for n in npcs if isinstance(n, dict) and isinstance(n.get("character"), str)}) > MAX_PALETTES:
                error("npcs", "The opening scene supports two distinct custom character palettes; additional instances may reuse those characters")
    else:
        error("$", "Unknown document kind")
    if errors:
        raise Invalid(errors)
    return document


def blank_character(ident, name=None):
    document = {"version": 1, "id": ident, "name": name or ident.replace("-", " ").title(),
                "description": "", "palette": ["transparent"] + ["#" + f"{i * 17:02x}" * 3 for i in range(1, 16)],
                "animations": {mode: {direction: [{"duration": 12 if mode == "idle" else 8,
                                                   "pixels": list(EMPTY)}] for direction in FACING_ORDER} for mode in MODES}}
    return validate(document)


def migrate_legacy(legacy, ident="cowboy", name="Cowboy"):
    document = blank_character(ident, name)
    document["description"] = legacy.get("description", "")
    document["palette"] = legacy["palette"]
    for direction in FACING_ORDER:
        pixels = legacy["frames"][direction]
        document["animations"]["idle"][direction] = [{"duration": 12, "pixels": pixels}]
        walk = []
        # A four-phase leg swing retains the original silhouette and feet anchor.
        for phase in range(4):
            rows = [list(row) for row in pixels]
            if phase in (1, 3):
                source = deepcopy(rows)
                for y in range(24, 32):
                    rows[y] = ["."] * 32
                for y in range(24, 32):
                    for x in range(32):
                        dy = (-1 if x < 16 else 0) if phase == 1 else (0 if x < 16 else -1)
                        rows[max(24, y + dy)][x] = source[y][x]
            walk.append({"duration": 8, "pixels": ["".join(row) for row in rows]})
        document["animations"]["walk"][direction] = walk
    return validate(document)


class Store:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()

    def path(self, kind, ident):
        if kind not in ("characters", "scenes") or not isinstance(ident, str) or not SLUG.fullmatch(ident):
            raise Invalid([{"field": "id", "message": "Invalid document path"}])
        path = self.root / "assets" / kind / (ident + ".json")
        if not path.resolve().is_relative_to((self.root / "assets").resolve()) or path.is_symlink():
            raise Invalid([{"field": "id", "message": "Document must remain inside assets"}])
        return path

    def get(self, kind, ident):
        data = self.path(kind, ident).read_bytes()
        document = validate(json.loads(data), kind)
        if document["id"] != ident:
            raise Invalid([{"field": "id", "message": "Document ID must match its filename"}])
        return {"document": document, "revision": revision(data)}

    def list(self, kind="characters"):
        directory = self.root / "assets" / kind
        return [self.get(kind, p.stem) for p in sorted(directory.glob("*.json"))]

    def save(self, kind, document, expected):
        validate(document, kind)
        path = self.path(kind, document["id"])
        with self.lock, project_lock(self.root):
            current = revision(path.read_bytes()) if path.exists() else None
            if expected != current:
                raise Conflict("This document changed. Reload it before saving your edits.")
            path.parent.mkdir(parents=True, exist_ok=True)
            data = canonical(document)
            descriptor, temp = tempfile.mkstemp(prefix=".edit-", suffix=".tmp", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        return {"document": document, "revision": revision(data)}

    def project(self, scene_id="opening-station"):
        scene = self.get("scenes", scene_id)["document"]
        characters = {}
        for i, npc in enumerate(scene["npcs"]):
            try:
                character = self.get("characters", npc["character"])["document"]
                if any(not 32 <= ord(c) <= 126 for c in character["name"]):
                    raise Invalid([{"field": "name", "message": "ROM speaker names require printable English characters"}])
                characters[npc["character"]] = character
            except FileNotFoundError:
                raise Invalid([{"field": f"npcs.{i}.character", "message": "Character does not exist"}])
        return scene, characters


def rgb_palette(document):
    result = [0]
    for color in document["palette"][1:]:
        r, g, b = bytes.fromhex(color[1:])
        result.append((r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10))
    return result


def export_sheet(document, mode="idle"):
    from PIL import Image
    validate(document)
    count = max(len(document["animations"][mode][d]) for d in FACING_ORDER)
    image = Image.new("P", (count * 32, 128), 0)
    colors = []
    for value in rgb_palette(document):
        colors.extend(((value & 31) * 255 // 31, ((value >> 5) & 31) * 255 // 31, ((value >> 10) & 31) * 255 // 31))
    image.putpalette(colors + [0] * (768 - len(colors)))
    for direction, facing in enumerate(FACING_ORDER):
        for frame, data in enumerate(document["animations"][mode][facing]):
            tile = Image.new("P", (32, 32))
            tile.putdata([0 if c == "." else int(c, 16) for row in data["pixels"] for c in row])
            image.paste(tile, (frame * 32, direction * 32))
    image.info["transparency"] = 0
    from PIL.PngImagePlugin import PngInfo
    metadata = PngInfo()
    metadata.add_text("evermore", json.dumps({"version": 1, "mode": mode,
                      "durations": {d: [f["duration"] for f in document["animations"][mode][d]] for d in FACING_ORDER}}))
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def import_sheet(document, png, mode="idle", mapping="exact"):
    from PIL import Image
    validate(document)
    if mode not in MODES or mapping not in ("exact", "nearest"):
        raise Invalid([{"field": "png", "message": "Unknown animation or palette mapping mode"}])
    indexed = Image.open(io.BytesIO(png))
    metadata = json.loads(indexed.info.get("evermore", "{}"))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("durations", {}), dict):
        raise Invalid([{"field": "png.metadata", "message": "Expected an animation metadata object"}])
    if indexed.height != 128 or indexed.width % 32 or not 32 <= indexed.width <= 512:
        raise Invalid([{"field": "png", "message": "Use four directional rows, 32 pixels high each, and 1–16 columns of 32 pixels"}])
    image = indexed.convert("RGBA")
    result = deepcopy(document)
    colors = [tuple(bytes.fromhex(c[1:])) for c in result["palette"][1:]]
    preserve_indices = indexed.mode == "P" and indexed.info.get("transparency") == 0
    if preserve_indices:
        source_palette = indexed.getpalette()
        preserve_indices = all(tuple(v >> 3 for v in source_palette[i * 3:i * 3 + 3]) ==
                               tuple(v >> 3 for v in colors[i - 1]) for i in range(1, 16))
    for row, facing in enumerate(FACING_ORDER):
        frames = []
        durations = metadata.get("durations", {}).get(facing, [12 if mode == "idle" else 8] * (image.width // 32))
        if not isinstance(durations, list) or not 1 <= len(durations) <= image.width // 32 or any(type(d) is not int or not 1 <= d <= 120 for d in durations):
            raise Invalid([{"field": "png.metadata", "message": "Invalid embedded animation durations"}])
        for column in range(len(durations)):
            pixels = []
            for y in range(32):
                line = ""
                for x in range(32):
                    r, g, b, a = image.getpixel((column * 32 + x, row * 32 + y))
                    if a < 128:
                        line += "."
                        continue
                    if preserve_indices:
                        index = indexed.getpixel((column * 32 + x, row * 32 + y))
                        if 1 <= index <= 15:
                            line += format(index, "x")
                            continue
                    # Compare at SNES precision; exported sheets are quantized.
                    distance = [sum(((v >> 3) - (w >> 3)) ** 2 for v, w in zip((r, g, b), c)) for c in colors]
                    index = min(range(15), key=distance.__getitem__)
                    if mapping != "nearest" and distance[index] != 0:
                        raise Invalid([{"field": "png.palette", "message": "Image uses colors outside this palette; choose explicit nearest-color mapping or edit the palette"}])
                    line += format(index + 1, "x")
                pixels.append(line)
            frames.append({"duration": durations[column], "pixels": pixels})
        result["animations"][mode][facing] = frames
    return validate(result)

#!/usr/bin/env python3
"""Character workshop CLI. Use --json for structured agent output."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from character_model import ROOT, Store, Conflict, Invalid, blank_character, validate, export_sheet, import_sheet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Print structured JSON, including errors")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    for command in ("get", "update"):
        p = commands.add_parser(command)
        p.add_argument("id")
        p.add_argument("--kind", choices=("characters", "scenes"), default="characters")
        if command == "update":
            p.add_argument("--input", type=Path, required=True)
            p.add_argument("--revision", required=True, help="Revision returned by get; prevents lost updates")
    p = commands.add_parser("create")
    p.add_argument("id")
    p.add_argument("--name")
    p = commands.add_parser("clone")
    p.add_argument("source")
    p.add_argument("id")
    p.add_argument("--name")
    p = commands.add_parser("validate")
    p.add_argument("id", nargs="?")
    p.add_argument("--kind", choices=("characters", "scenes"), default="characters")
    p = commands.add_parser("preview")
    p.add_argument("id")
    p.add_argument("--mode", choices=("idle", "walk"), default="idle")
    p.add_argument("--output", type=Path)
    p = commands.add_parser("import-png")
    p.add_argument("id")
    p.add_argument("input", type=Path)
    p.add_argument("--mode", choices=("idle", "walk"), default="idle")
    p.add_argument("--mapping", choices=("exact", "nearest"), default="exact")
    p.add_argument("--revision", required=True)
    commands.add_parser("build")
    p = commands.add_parser("serve")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    store = Store(args.root)
    try:
        if args.command == "serve":
            from editor_server import serve
            serve(args.root, args.port, not args.no_browser)
            return
        if args.command == "list":
            result = {"characters": store.list(), "scenes": store.list("scenes")}
        elif args.command == "get":
            result = store.get(args.kind, args.id)
        elif args.command == "create":
            result = store.save("characters", blank_character(args.id, args.name), None)
        elif args.command == "clone":
            document = deepcopy(store.get("characters", args.source)["document"])
            document.update(id=args.id, name=args.name or args.id.replace("-", " ").title())
            result = store.save("characters", document, None)
        elif args.command == "update":
            document = json.loads(args.input.read_text())
            if "document" in document:
                document = document["document"]
            validate(document, args.kind)
            if document.get("id") != args.id:
                raise Invalid([{"field": "id", "message": "Input ID must match command ID"}])
            result = store.save(args.kind, document, args.revision)
        elif args.command == "validate":
            if args.id:
                result = store.get(args.kind, args.id)
            else:
                for item in store.list():
                    validate(item["document"])
                scene, characters = store.project()
                result = {"scene": scene["id"], "characters": sorted(characters)}
            result["valid"] = True
        elif args.command == "preview":
            output = args.output or args.root / "build" / f"{args.id}-{args.mode}.png"
            data = export_sheet(store.get("characters", args.id)["document"], args.mode)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            result = {"output": str(output)}
        elif args.command == "import-png":
            document = import_sheet(store.get("characters", args.id)["document"], args.input.read_bytes(), args.mode, args.mapping)
            result = store.save("characters", document, args.revision)
        else:
            from build_npc import build_project
            result = build_project(args.root)
        print(json.dumps(result, indent=2) if args.json else describe(result))
    except (OSError, ValueError) as error:
        result = {"error": str(error), "errors": getattr(error, "errors", []),
                  "conflict": isinstance(error, Conflict)}
        print(json.dumps(result, indent=2) if args.json else "Error: " + str(error))
        raise SystemExit(2)


def describe(result):
    if "target" in result:
        return f"Built build/evermore-npc.sfc and .bps\nSHA-256: {result['target']['sha256']}"
    if "document" in result:
        return json.dumps(result, indent=2)
    if "characters" in result and "scenes" in result:
        return "\n".join(f"{x['document']['id']:24} {x['document']['name']}" for x in result["characters"])
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    main()

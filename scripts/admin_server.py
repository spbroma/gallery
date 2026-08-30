#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import subprocess
import tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from archive_metadata import (
    SCHEMA_VERSION,
    discover_shoots,
    image_files,
    metadata_path,
    photo_id,
    read_json,
    sha256,
    slugify,
    validate_tags,
    write_json_atomic,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADMIN_ROOT = PROJECT_ROOT / "admin"


class Library:
    def __init__(self, archive: Path) -> None:
        self.archive = archive.resolve()
        self.cache = Path(tempfile.gettempdir()) / "photo-gallery-admin-previews"
        self.cache.mkdir(parents=True, exist_ok=True)
        public = read_json(PROJECT_ROOT / "public" / "data" / "gallery.json")
        self.published = {f"{photo['albumId']}/{photo['id']}" for photo in public.get("photos", [])}

    def shoots(self) -> list[dict[str, Any]]:
        result = []
        for shoot, source in discover_shoots(self.archive):
            files = image_files(source)
            meta_count = sum(metadata_path(shoot, image).exists() for image in files)
            relative = shoot.relative_to(self.archive).as_posix()
            album_id = slugify(relative)
            published = sum(f"{album_id}/{photo_id(image)}" in self.published for image in files)
            result.append({
                "path": relative,
                "name": shoot.name,
                "year": shoot.parent.name,
                "sourceTier": source.name,
                "photoCount": len(files),
                "metadataCount": meta_count,
                "publishedCount": published,
            })
        return result

    def resolve_shoot(self, relative: str) -> tuple[Path, Path]:
        shoot = (self.archive / relative).resolve()
        shoot.relative_to(self.archive)
        source = next((item[1] for item in discover_shoots(self.archive) if item[0] == shoot), None)
        if source is None:
            raise FileNotFoundError(relative)
        return shoot, source

    def photos(self, relative: str) -> list[dict[str, Any]]:
        shoot, source = self.resolve_shoot(relative)
        album_id = slugify(relative)
        result = []
        for image in image_files(source):
            identifier = photo_id(image)
            sidecar = read_json(metadata_path(shoot, image))
            semantic = sidecar.get("analysis", {}).get("semantic", {})
            visual = sidecar.get("analysis", {}).get("visual", {})
            tags = sidecar.get("tags", {})
            generated = tags.get("generated", [])
            result.append({
                "id": identifier,
                "file": image.name,
                "sourceTier": source.name,
                "published": sidecar.get("publication", {}).get("published", f"{album_id}/{identifier}" in self.published),
                "manualTags": tags.get("manual", []),
                "generatedTags": generated,
                "description": sidecar.get("editorial", {}).get("description") or sidecar.get("analysis", {}).get("description", semantic.get("description", "")),
                "shotScale": sidecar.get("editorial", {}).get("shotScale") or semantic.get("shot_scale", semantic.get("shotScale", "unknown")),
                "peopleCount": sidecar.get("editorial", {}).get("peopleCount") if sidecar.get("editorial", {}).get("peopleCount") is not None else semantic.get("people_count", semantic.get("peopleCount", 0)),
                "brightness": visual.get("brightness"),
                "colorProfile": visual.get("colorProfile", {}),
                "hasMetadata": bool(sidecar),
                "preview": f"/api/preview?shoot={quote(relative)}&id={quote(identifier)}",
            })
        return result

    def save_photo(self, payload: dict[str, Any]) -> dict[str, Any]:
        relative = str(payload.get("shoot", ""))
        identifier = str(payload.get("id", ""))
        shoot, source = self.resolve_shoot(relative)
        image = next((path for path in image_files(source) if photo_id(path) == identifier), None)
        if image is None:
            raise FileNotFoundError(identifier)
        path = metadata_path(shoot, image)
        document = read_json(path)
        album_id = slugify(relative)
        if not document:
            semantic: dict[str, Any] = {}
            document = {
                "schemaVersion": SCHEMA_VERSION,
                "id": identifier,
                "source": {
                    "path": image.relative_to(shoot).as_posix(),
                    "sha256": sha256(image),
                    "size": image.stat().st_size,
                    "mtimeNs": image.stat().st_mtime_ns,
                },
                "analysis": {
                    "status": "missing",
                    "models": {},
                    "inputMaxEdge": None,
                    "generatedAt": None,
                    "description": semantic.get("description", ""),
                    "semantic": semantic,
                    "visual": {},
                    "embedding": [],
                },
                "tags": {"manual": [], "generated": []},
                "publication": {"published": f"{album_id}/{identifier}" in self.published},
                "editorial": {},
            }
        manual_tags = validate_tags(payload.get("manualTags", []))
        document["tags"] = {
            "manual": manual_tags,
            "generated": [tag for tag in validate_tags(payload.get("generatedTags", [])) if tag not in manual_tags],
        }
        document.setdefault("publication", {})["published"] = bool(payload.get("published", False))
        editorial = document.setdefault("editorial", {})
        editorial["description"] = str(payload.get("description", "")).strip() or None
        editorial["shotScale"] = str(payload.get("shotScale", "")).strip() or None
        people_count = payload.get("peopleCount")
        editorial["peopleCount"] = max(0, min(100, int(people_count))) if people_count not in (None, "") else None
        editorial["updatedAt"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(path, document)
        return next(photo for photo in self.photos(relative) if photo["id"] == identifier)

    def preview(self, relative: str, identifier: str) -> Path:
        _, source = self.resolve_shoot(relative)
        image = next((path for path in image_files(source) if photo_id(path) == identifier), None)
        if image is None:
            raise FileNotFoundError(identifier)
        stat = image.stat()
        key = hashlib.sha1(f"{image}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()
        destination = self.cache / f"{key}.jpg"
        if not destination.exists():
            subprocess.run(
                ["sips", "-s", "format", "jpeg", "-Z", "900", str(image), "--out", str(destination)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return destination


class Handler(BaseHTTPRequestHandler):
    library: Library

    def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str | None = None) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/shoots":
                self.send_json({"shoots": self.library.shoots()})
            elif parsed.path == "/api/photos":
                shoot = query.get("shoot", [""])[0]
                self.send_json({"shoot": shoot, "photos": self.library.photos(shoot)})
            elif parsed.path == "/api/preview":
                path = self.library.preview(query.get("shoot", [""])[0], query.get("id", [""])[0])
                self.send_file(path, "image/jpeg")
            elif parsed.path == "/":
                self.send_file(ADMIN_ROOT / "index.html", "text/html; charset=utf-8")
            elif parsed.path.startswith("/assets/"):
                asset = (ADMIN_ROOT / parsed.path.removeprefix("/assets/")).resolve()
                asset.relative_to(ADMIN_ROOT.resolve())
                self.send_file(asset)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (FileNotFoundError, ValueError, subprocess.CalledProcessError):
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/photo":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 64 * 1024)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self.send_json({"photo": self.library.save_photo(payload)})
        except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError):
            self.send_json({"error": "Invalid photo update"}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local photo archive admin")
    parser.add_argument("--archive", default="~/Pictures/PhotoArchive")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4177)
    args = parser.parse_args()
    archive = Path(args.archive).expanduser()
    if not archive.is_dir():
        raise SystemExit(f"Archive does not exist: {archive}")
    Handler.library = Library(archive)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Photo archive admin: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

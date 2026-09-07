#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import subprocess
import sys
import tempfile
import threading
import uuid
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
        draft_id = hashlib.sha1(str(self.archive).encode()).hexdigest()
        self.draft_file = Path(tempfile.gettempdir()) / "photo-gallery-admin-drafts" / f"{draft_id}.json"
        self.metadata_file = self.draft_file.with_name(f"{draft_id}-metadata.json")
        self.draft: dict[str, dict[str, Any]] = read_json(self.draft_file)
        self.metadata_dirty: dict[str, dict[str, Any]] = read_json(self.metadata_file)
        self.lock = threading.RLock()
        self.reload_public()

    def persist_draft(self) -> None:
        write_json_atomic(self.draft_file, self.draft)
        write_json_atomic(self.metadata_file, self.metadata_dirty)

    def draft_state(self) -> dict[str, Any]:
        return {
            "draft": self.draft_view(),
            "metadataDirty": sorted(self.metadata_dirty.values(), key=lambda item: (item["shoot"], item["file"])),
            "releasePending": self.repository_dirty(),
        }

    def repository_dirty(self) -> bool:
        completed = subprocess.run(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
        )
        return bool(completed.stdout.strip())

    def reload_public(self) -> None:
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

    def photos(self, relative: str, include_drafts: bool = True) -> list[dict[str, Any]]:
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
            photo = {
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
            }
            photo["actualPublished"] = photo["published"]
            draft = self.draft.get(f"{relative}/{identifier}") if include_drafts else None
            if draft:
                photo.update(draft["after"])
            photo["pending"] = bool(draft)
            photo["metadataPending"] = f"{relative}/{identifier}" in self.metadata_dirty
            result.append(photo)
        return result

    def stage(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not payloads or len(payloads) > 10000:
            raise ValueError("Invalid draft size")
        with self.lock:
            for payload in payloads:
                relative, identifier = str(payload.get("shoot", "")), str(payload.get("id", ""))
                base = next((photo for photo in self.photos(relative, False) if photo["id"] == identifier), None)
                if base is None:
                    raise FileNotFoundError(identifier)
                key = f"{relative}/{identifier}"
                before = self.draft.get(key, {}).get("before", {"published": base["published"]})
                after = {"published": bool(payload.get("published", base["published"]))}
                if before == after:
                    self.draft.pop(key, None)
                else:
                    self.draft[key] = {"key": key, "shoot": relative, "id": identifier, "file": base["file"], "preview": base["preview"], "before": before, "after": after}
            self.persist_draft()
            return self.draft_view()

    def discard(self, keys: list[str]) -> list[dict[str, Any]]:
        with self.lock:
            for key in keys:
                self.draft.pop(str(key), None)
            self.persist_draft()
            return self.draft_view()

    def draft_view(self) -> list[dict[str, Any]]:
        result = []
        for entry in self.draft.values():
            changes = {key: {"before": entry["before"][key], "after": entry["after"][key]} for key in entry["before"] if entry["before"][key] != entry["after"][key]}
            result.append({**entry, "changes": changes})
        return sorted(result, key=lambda item: (item["shoot"], item["file"]))

    def save_photo(self, payload: dict[str, Any]) -> dict[str, Any]:
        relative = str(payload.get("shoot", ""))
        identifier = str(payload.get("id", ""))
        shoot, source = self.resolve_shoot(relative)
        before = next(photo for photo in self.photos(relative, False) if photo["id"] == identifier)
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
        # Publication is changed only by apply(); ordinary editor saves stay local.
        editorial = document.setdefault("editorial", {})
        editorial["description"] = str(payload.get("description", "")).strip() or None
        editorial["shotScale"] = str(payload.get("shotScale", "")).strip() or None
        people_count = payload.get("peopleCount")
        editorial["peopleCount"] = max(0, min(100, int(people_count))) if people_count not in (None, "") else None
        editorial["updatedAt"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(path, document)
        after = next(photo for photo in self.photos(relative, False) if photo["id"] == identifier)
        fields = [field for field in ("manualTags", "generatedTags", "description", "shotScale", "peopleCount") if before[field] != after[field]]
        if fields:
            key = f"{relative}/{identifier}"
            existing = self.metadata_dirty.get(key, {})
            self.metadata_dirty[key] = {
                "key": key, "shoot": relative, "id": identifier, "file": after["file"], "preview": after["preview"],
                "fields": sorted(set(existing.get("fields", [])) | set(fields)),
            }
            self.persist_draft()
        return next(photo for photo in self.photos(relative) if photo["id"] == identifier)

    def set_publication(self, relative: str, identifier: str, published: bool) -> None:
        shoot, source = self.resolve_shoot(relative)
        image = next((path for path in image_files(source) if photo_id(path) == identifier), None)
        if image is None:
            raise FileNotFoundError(identifier)
        path = metadata_path(shoot, image)
        document = read_json(path)
        if not document:
            raise ValueError(f"Metadata must exist before publication: {identifier}")
        document.setdefault("publication", {})["published"] = published
        document["publication"]["updatedAt"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(path, document)

    def run_logged(self, command: list[str], progress: Any) -> str:
        progress(f"$ {' '.join(command)}")
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        lines: list[str] = []
        if process.stdout:
            for line in process.stdout:
                clean = line.rstrip()
                lines.append(clean)
                if clean:
                    progress(clean)
        returncode = process.wait()
        output = "\n".join(lines)
        if returncode:
            raise subprocess.CalledProcessError(returncode, command, output=output, stderr=output)
        return output

    def release(self, progress: Any) -> None:
        config = read_json(PROJECT_ROOT / "config" / "photo_publish.config.json")
        remote = str(config.get("gitRemote", "origin"))
        branch = str(config.get("gitBranch", "main"))
        message = str(config.get("adminCommitMessage", "Update photo gallery from admin"))
        current_branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
        if current_branch != branch:
            raise RuntimeError(f"Release requires branch {branch!r}; current branch is {current_branch!r}")
        remotes = subprocess.run(
            ["git", "remote"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        if remote not in remotes:
            raise RuntimeError(f"Git remote {remote!r} is not configured")

        progress("Checking repository changes…")
        self.run_logged(["git", "diff", "--check"], progress)
        self.run_logged(["git", "add", "--all"], progress)
        self.run_logged(["git", "diff", "--cached", "--check"], progress)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=PROJECT_ROOT)
        if staged.returncode == 1:
            progress("Creating commit…")
            self.run_logged(["git", "commit", "-m", message], progress)
        elif staged.returncode == 0:
            progress("No new repository changes to commit.")
        else:
            raise RuntimeError("Unable to inspect staged Git changes")
        progress(f"Pushing {branch} to {remote}…")
        self.run_logged(["git", "push", remote, branch], progress)

    def apply(self, progress: Any | None = None, release: bool = True) -> dict[str, Any]:
        progress = progress or (lambda _message: None)
        with self.lock:
            if not self.draft and not self.metadata_dirty and not (release and self.repository_dirty()):
                raise ValueError("Nothing to apply")
            entries = list(self.draft.values())
            metadata_count = len(self.metadata_dirty)
            backups: list[tuple[Path, bytes | None]] = []
            try:
                for entry in entries:
                    shoot, source = self.resolve_shoot(entry["shoot"])
                    image = next(path for path in image_files(source) if photo_id(path) == entry["id"])
                    path = metadata_path(shoot, image)
                    backups.append((path, path.read_bytes() if path.exists() else None))
                    self.set_publication(entry["shoot"], entry["id"], entry["after"]["published"])
                progress("Rebuilding site files…")
                output = self.run_logged([sys.executable, str(PROJECT_ROOT / "scripts" / "publish.py")], progress)
            except Exception:
                for path, content in backups:
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(content)
                raise
            if release:
                self.release(progress)
            self.draft.clear()
            self.metadata_dirty.clear()
            self.persist_draft()
            self.reload_public()
            progress("Published successfully. GitHub Pages deployment has been triggered.")
            return {"appliedCount": len(entries), "metadataCount": metadata_count, "output": output.strip(), "releasePending": False}

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

    def send_event(self, value: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
        self.wfile.flush()

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
            elif parsed.path == "/api/draft":
                self.send_json(self.library.draft_state())
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
        path = urlparse(self.path).path
        if path not in {"/api/photo", "/api/draft", "/api/draft/discard", "/api/apply"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 2 * 1024 * 1024)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if path == "/api/photo":
                self.send_json({"photo": self.library.save_photo(payload), **self.library.draft_state()})
            elif path == "/api/draft":
                self.library.stage(payload.get("updates", []))
                self.send_json(self.library.draft_state())
            elif path == "/api/draft/discard":
                self.library.discard(payload.get("keys", []))
                self.send_json(self.library.draft_state())
            else:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                operation_id = uuid.uuid4().hex[:8]
                self.send_event({"type": "start", "message": f"Publication {operation_id} started."})
                try:
                    result = self.library.apply(lambda message: self.send_event({"type": "status", "message": message}))
                    self.send_event({"type": "complete", "message": "Done.", "result": result})
                except Exception as error:
                    message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
                    self.send_event({"type": "error", "message": f"Publication failed: {message}"})
                self.close_connection = True
        except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error) or "Invalid update"}, HTTPStatus.BAD_REQUEST)
        except subprocess.CalledProcessError as error:
            message = error.stderr.strip() if error.stderr else str(error)
            self.send_json({"error": f"Publication failed: {message}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

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

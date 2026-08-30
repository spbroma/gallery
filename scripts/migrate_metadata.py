#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_metadata import (
    SCHEMA_VERSION,
    discover_shoots,
    image_files,
    metadata_path,
    photo_id,
    read_json,
    sha256,
    slugify,
    write_json_atomic,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_document(
    shoot: Path,
    source: Path,
    image: Path,
    record: dict[str, Any],
    published: bool,
) -> dict[str, Any]:
    semantic = record.get("semantic", {})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": photo_id(image),
        "source": {
            "path": image.relative_to(shoot).as_posix(),
            "tier": int(source.name),
            "sha256": sha256(image),
            "size": image.stat().st_size,
            "mtimeNs": image.stat().st_mtime_ns,
        },
        "analysis": {
            "status": "ready" if record else "missing",
            "models": record.get("models", {}),
            "inputMaxEdge": None,
            "generatedAt": None,
            "description": semantic.get("description", ""),
            "semantic": semantic,
            "visual": record.get("visual", {}),
            "embedding": record.get("embedding", []),
        },
        "tags": {"manual": [], "generated": record.get("tags", [])},
        "publication": {"published": published},
        "editorial": {"description": None, "shotScale": None, "peopleCount": None, "updatedAt": None},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create per-photo _meta sidecars from the current aggregate library")
    parser.add_argument("--archive", default="~/Pictures/PhotoArchive")
    parser.add_argument("--library", default=str(PROJECT_ROOT / "data" / "photo-library.json"))
    parser.add_argument("--gallery", default=str(PROJECT_ROOT / "public" / "data" / "gallery.json"))
    parser.add_argument("--write", action="store_true", help="Write files; otherwise report a dry run")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    archive = Path(args.archive).expanduser().resolve()
    records = {record["key"]: record for record in read_json(Path(args.library)).get("photos", [])}
    gallery = read_json(Path(args.gallery))
    published = {f"{photo['albumId']}/{photo['id']}" for photo in gallery.get("photos", [])}
    created = skipped = missing_analysis = 0

    for shoot, source in discover_shoots(archive):
        relative = shoot.relative_to(archive).as_posix()
        album_id = slugify(relative)
        album_document = {
            "schemaVersion": SCHEMA_VERSION,
            "id": album_id,
            "archivePath": relative,
            "sourceTier": int(source.name),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        album_path = shoot / "_meta" / "album.json"
        if args.write and (args.overwrite or not album_path.exists()):
            write_json_atomic(album_path, album_document)
        for image in image_files(source):
            path = metadata_path(shoot, image)
            if path.exists() and not args.overwrite:
                skipped += 1
                continue
            identifier = photo_id(image)
            key = f"{album_id}/{identifier}"
            record = records.get(key, {})
            missing_analysis += not bool(record)
            if args.write:
                write_json_atomic(path, make_document(shoot, source, image, record, key in published))
            created += 1

    action = "Created" if args.write else "Would create"
    print(f"{action} {created} photo sidecars; {missing_analysis} need analysis; skipped {skipped} existing files")


if __name__ == "__main__":
    main()

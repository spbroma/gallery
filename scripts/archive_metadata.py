from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower() or "photo"


def image_files(folder: Path, extensions: set[str] = IMAGE_EXTENSIONS) -> list[Path]:
    return sorted(
        (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in extensions),
        key=lambda path: path.name.casefold(),
    )


def highest_source_folder(shoot: Path, extensions: set[str] = IMAGE_EXTENSIONS) -> Path | None:
    candidates = [
        folder for folder in shoot.iterdir()
        if folder.is_dir() and folder.name.isdigit() and image_files(folder, extensions)
    ]
    return max(candidates, key=lambda folder: int(folder.name), default=None)


def discover_shoots(archive: Path, extensions: set[str] = IMAGE_EXTENSIONS) -> list[tuple[Path, Path]]:
    result: list[tuple[Path, Path]] = []
    for year in sorted((path for path in archive.iterdir() if path.is_dir() and path.name.isdigit()), reverse=True):
        for shoot in sorted((path for path in year.iterdir() if path.is_dir()), reverse=True):
            source = highest_source_folder(shoot, extensions)
            if source:
                result.append((shoot, source))
    return result


def photo_id(path: Path) -> str:
    return slugify(path.stem)


def metadata_path(shoot: Path, image: Path) -> Path:
    return shoot / "_meta" / "photos" / f"{photo_id(image)}.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def effective_tags(document: dict[str, Any]) -> list[str]:
    tags = document.get("tags", {})
    manual = tags.get("manual", [])
    generated = tags.get("generated", [])
    return list(dict.fromkeys([*manual, *generated]))


def validate_tags(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        tag = str(value).strip().lower()
        if tag and len(tag) <= 64 and tag not in result:
            result.append(tag)
    return result

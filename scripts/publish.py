#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_metadata import highest_source_folder, image_files, metadata_path, photo_id, validate_tags
from storage import GoogleDriveStorage, LocalStorage

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        result[key] = deep_merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def load_config(path: Path, overlay: Path | None) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    return deep_merge(config, json.loads(overlay.read_text(encoding="utf-8"))) if overlay else config


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower() or "album"


def parse_folder(shoot: Path) -> tuple[str, str, int]:
    match = re.match(r"(?P<date>\d{2}-\d{2})\s*-?\s*(?P<title>.*)", shoot.name)
    year = int(shoot.parent.name) if shoot.parent.name.isdigit() else 0
    if not match:
        return shoot.name, str(year), year
    date = f"{year}-{match.group('date')}" if year else match.group("date")
    title = match.group("title").strip(" ,-–") or datetime.strptime(date, "%Y-%m-%d").strftime("%d %B")
    return title, date, year


def infer_city(title: str) -> str | None:
    cities = ["Munich", "Bonn", "Florence", "Berlin", "Augsburg", "Dusseldorf", "Milan", "Regensburg"]
    return next((item for item in cities if item.lower() in title.lower()), None)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_exclusions(config: dict[str, Any], archive: Path) -> list[dict[str, Any]]:
    value = config["publishing"].get("exclusionsFile")
    if not value:
        return []
    path = resolve_project_path(value)
    document = read_json(path)
    rules: list[dict[str, Any]] = []
    archive_resolved = archive.resolve()
    for entry in document.get("exclude", []):
        folder = (archive / entry["folder"]).resolve()
        try:
            folder.relative_to(archive_resolved)
        except ValueError as error:
            raise ValueError(f"Exclusion escapes archive root: {entry['folder']}") from error
        files = entry.get("files")
        rules.append({"folder": folder, "files": {item.casefold() for item in files} if files else None})
    return rules


def is_within(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder)
        return True
    except ValueError:
        return False


def folder_is_excluded(path: Path, exclusions: list[dict[str, Any]]) -> bool:
    return any(rule["files"] is None and is_within(path, rule["folder"]) for rule in exclusions)


def file_is_excluded(path: Path, exclusions: list[dict[str, Any]]) -> bool:
    for rule in exclusions:
        files = rule["files"]
        if files is None or not is_within(path, rule["folder"]):
            continue
        relative = path.resolve().relative_to(rule["folder"]).as_posix().casefold()
        if relative in files or path.name.casefold() in files:
            return True
    return folder_is_excluded(path, exclusions)


def select_source(shoot: Path, config: dict[str, Any], exclusions: list[dict[str, Any]]) -> tuple[Path, Path | None, int] | None:
    publishing = config["publishing"]
    suffix = publishing["blackFolderSuffix"]
    extensions = {item.lower() for item in config["processing"]["formats"]}
    source = highest_source_folder(shoot, extensions)
    if source and (shoot / "_meta" / "photos").is_dir() and not folder_is_excluded(source, exclusions):
        return source, None, int(source.name)
    selected = sorted(
        (int(path.name), path, shoot / f"{path.name}{suffix}")
        for path in shoot.iterdir()
        if path.is_dir()
        and path.name.isdigit()
        and (shoot / f"{path.name}{suffix}").is_dir()
        and not folder_is_excluded(path, exclusions)
        and not folder_is_excluded(shoot / f"{path.name}{suffix}", exclusions)
        and any(item.is_file() and item.suffix.lower() in extensions for item in (shoot / f"{path.name}{suffix}").iterdir())
    )
    if not selected:
        return None
    rating, source, black = selected[-1]
    return source, black, rating


def discover_shoots(archive: Path, config: dict[str, Any], exclusions: list[dict[str, Any]]) -> list[tuple[Path, Path, Path | None, int]]:
    allowlist = set(config["publishing"].get("albumAllowlist") or [])
    result: list[tuple[Path, Path, Path | None, int]] = []
    for year in sorted((path for path in archive.iterdir() if path.is_dir()), reverse=True):
        for shoot in sorted((path for path in year.iterdir() if path.is_dir()), reverse=True):
            relative = shoot.relative_to(archive).as_posix()
            has_sidecars = (shoot / "_meta" / "photos").is_dir()
            if (allowlist and relative not in allowlist) or (folder_is_excluded(shoot, exclusions) and not has_sidecars):
                continue
            selected = select_source(shoot, config, exclusions)
            if selected:
                result.append((shoot, selected[0], selected[1], selected[2]))
    return result


def convert_image(source: Path, destination: Path, max_edge: int, quality: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        resized = Path(handle.name)
    try:
        subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(max_edge), str(source), "--out", str(resized)], check=True, stdout=subprocess.DEVNULL)
        if not resized.exists() or resized.stat().st_size == 0:
            raise ValueError(f"Image decoder returned no data for {source.name}")
        subprocess.run(["cwebp", "-quiet", "-q", str(quality), "-metadata", "none", str(resized), "-o", str(destination)], check=True)
    finally:
        resized.unlink(missing_ok=True)


def build_storage(config: dict[str, Any], output_root: Path):
    storage = config["storage"]
    if storage["provider"] == "local":
        return LocalStorage(output_root)
    if storage["provider"] == "googleDrive":
        drive = storage["googleDrive"]
        if not drive.get("enabled"):
            raise RuntimeError("Set storage.googleDrive.enabled=true before selecting Google Drive.")
        return GoogleDriveStorage(drive["publicFolderId"], drive["credentialsEnv"])
    raise ValueError(f"Unknown storage provider: {storage['provider']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build safe web derivatives and gallery.json")
    parser.add_argument("--config", default="config/gallery.config.json")
    parser.add_argument("--overlay", help="Optional JSON config merged over the main config")
    parser.add_argument("--source", help="Publish only this exact numeric source folder")
    parser.add_argument("--merge", action="store_true", help="Merge a targeted publish into the existing manifests")
    args = parser.parse_args()
    config = load_config(resolve_project_path(args.config), resolve_project_path(args.overlay) if args.overlay else None)
    archive = resolve_project_path(config["archiveRoot"])
    output_root = resolve_project_path(config["outputRoot"])
    data_file = resolve_project_path(config["dataFile"])
    filters_file = resolve_project_path(config["filtersFile"])
    if not archive.is_dir():
        raise SystemExit(f"Archive does not exist: {archive}")
    if not shutil.which("sips") or not shutil.which("cwebp"):
        raise SystemExit("sips and cwebp are required to generate WebP derivatives")

    storage = build_storage(config, output_root)
    processing = config["processing"]
    extensions = {item.lower() for item in processing["formats"]}
    limit = config["publishing"].get("maxPhotosPerAlbum")
    exclusions = load_exclusions(config, archive)
    albums: list[dict[str, Any]] = []
    photos: list[dict[str, Any]] = []
    filter_photos: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    if args.source:
        source = Path(args.source).expanduser().resolve()
        if not source.is_dir() or not source.name.isdigit():
            raise SystemExit("--source must point to a numeric photo folder such as .../shoot/2")
        shoot = source.parent
        try:
            shoot.relative_to(archive.resolve())
        except ValueError as error:
            raise SystemExit(f"Source folder is outside archiveRoot: {source}") from error
        shoot_entries = [(shoot, source, None, int(source.name))]
        targeted_album_ids = {slugify(shoot.relative_to(archive).as_posix())}
    else:
        shoot_entries = discover_shoots(archive, config, exclusions)
        targeted_album_ids = set()

    previous_manifest = read_json(data_file) if args.merge else {}
    previous_filters = read_json(filters_file) if args.merge else {}

    with tempfile.TemporaryDirectory(prefix="gallery-publish-") as temp:
        staging = Path(temp)
        for shoot, source_dir, black_dir, rating in shoot_entries:
            title, date, year = parse_folder(shoot)
            metadata = read_json(shoot / "metadata" / "album.json")
            relative = shoot.relative_to(archive).as_posix()
            album_id = metadata.get("id") or slugify(relative)
            title = metadata.get("title") or title
            city = metadata.get("location", {}).get("city") or infer_city(title)
            album_stage = staging / album_id
            if black_dir is None:
                images = [
                    path for path in image_files(source_dir, extensions)
                    if read_json(metadata_path(shoot, path)).get("publication", {}).get("published", False)
                ]
            else:
                selected_names = {
                    path.stem.casefold() for path in black_dir.iterdir()
                    if path.is_file() and path.suffix.lower() in extensions and not file_is_excluded(path, exclusions)
                }
                images = sorted(
                    path for path in source_dir.iterdir()
                    if path.is_file()
                    and path.suffix.lower() in extensions
                    and path.stem.casefold() in selected_names
                    and not file_is_excluded(path, exclusions)
                )
            if limit:
                images = images[:int(limit)]
            for image in images:
                identifier = photo_id(image)
                web_name = f"{identifier}.webp"
                web_path = album_stage / "web" / web_name
                thumb_path = album_stage / "thumbs" / web_name
                try:
                    convert_image(image, web_path, processing["webMaxEdge"], processing["webQuality"])
                    convert_image(image, thumb_path, processing["thumbMaxEdge"], processing["thumbQuality"])
                except (subprocess.CalledProcessError, ValueError) as error:
                    web_path.unlink(missing_ok=True)
                    thumb_path.unlink(missing_ok=True)
                    skipped.append({"album": relative, "file": image.name, "reason": type(error).__name__})
                    print(f"Skipped unreadable image: {relative}/{image.name}")
                    continue
                base_url = config["publicBaseUrl"].rstrip("/")
                photo_metadata = read_json(metadata_path(shoot, image)) or read_json(shoot / "metadata" / "photos" / f"{image.stem}.json")
                analysis = photo_metadata.get("analysis", {})
                semantic = dict(analysis.get("semantic", {}))
                editorial = photo_metadata.get("editorial", {})
                if editorial.get("shotScale"):
                    semantic["shot_scale"] = editorial["shotScale"]
                if editorial.get("peopleCount") is not None:
                    semantic["people_count"] = editorial["peopleCount"]
                tag_data = photo_metadata.get("tags", {})
                effective_tags = validate_tags([*tag_data.get("manual", []), *tag_data.get("generated", [])]) if isinstance(tag_data, dict) else validate_tags(tag_data)
                photos.append({
                    "id": identifier, "albumId": album_id,
                    "src": f"{base_url}/{album_id}/web/{web_name}", "thumb": f"{base_url}/{album_id}/thumbs/{web_name}",
                    "title": title, "date": date, "year": year, "city": city, "rating": rating,
                    "genres": photo_metadata.get("genres", metadata.get("genres", [])),
                    "subjects": photo_metadata.get("subjects", metadata.get("subjects", [])),
                    "tags": effective_tags or metadata.get("tags", []),
                    "featured": bool(photo_metadata.get("featured", False)),
                })
                visual = analysis.get("visual", {})
                filter_photos.append({
                    "key": f"{album_id}/{identifier}",
                    "id": identifier,
                    "albumId": album_id,
                    "date": date,
                    "visual": {
                        "brightness": visual.get("brightness", 0.5),
                        "colorfulness": visual.get("colorfulness", 0),
                        "colorProfile": visual.get("colorProfile", {}),
                        "dominantAverageColor": visual.get("dominantAverageColor", {"hsv": {"h": 0, "s": 0, "v": 0}}),
                    },
                    "semantic": {
                        "shot_scale": semantic.get("shot_scale", "unknown"),
                        "people_count": semantic.get("people_count", 0),
                        "semantic_tags": semantic.get("semantic_tags", []),
                        "composition_tags": semantic.get("composition_tags", []),
                    },
                    "tags": effective_tags,
                })
            if images:
                storage.sync_album(album_id, album_stage)
                albums.append({
                    "id": album_id, "title": title, "date": date, "year": year, "city": city,
                    "genres": metadata.get("genres", []), "subjects": metadata.get("subjects", []),
                    "tags": metadata.get("tags", []), "photoCount": len([photo for photo in photos if photo["albumId"] == album_id]),
                })

    new_album_ids = {album["id"] for album in albums}
    if args.merge:
        albums = [album for album in previous_manifest.get("albums", []) if album.get("id") not in targeted_album_ids] + albums
        photos = [photo for photo in previous_manifest.get("photos", []) if photo.get("albumId") not in targeted_album_ids] + photos
        filter_photos = [photo for photo in previous_filters.get("photos", []) if photo.get("albumId") not in targeted_album_ids] + filter_photos
        albums.sort(key=lambda album: (album.get("date", ""), album.get("id", "")), reverse=True)
        photos.sort(key=lambda photo: (photo.get("date", ""), photo.get("albumId", ""), photo.get("id", "")), reverse=True)
        filter_photos.sort(key=lambda photo: (photo.get("date", ""), photo.get("albumId", ""), photo.get("id", "")), reverse=True)
        if config["storage"]["provider"] == "local" and not skipped:
            for album_id in targeted_album_ids - new_album_ids:
                destination = (output_root / album_id).resolve()
                destination.relative_to(output_root.resolve())
                if destination.is_dir():
                    shutil.rmtree(destination)

    active_ids = {album["id"] for album in albums}
    if not config["publishing"].get("albumAllowlist") and output_root.exists():
        for existing in output_root.iterdir():
            if existing.is_dir() and existing.name not in active_ids:
                shutil.rmtree(existing)

    manifest = {"version": 1, "generatedAt": datetime.now(timezone.utc).isoformat(), "source": config["storage"]["provider"], "albums": albums, "photos": photos, "skipped": skipped}
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    filters_file.parent.mkdir(parents=True, exist_ok=True)
    filters_file.write_text(json.dumps({"version": 1, "generatedAt": manifest["generatedAt"], "photos": filter_photos}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    if photos and config["storage"]["provider"] == "local":
        first_web = output_root / photos[0]["albumId"] / "web" / f"{photos[0]['id']}.webp"
        if first_web.exists():
            shutil.copy2(first_web, PROJECT_ROOT / "public" / "og.webp")
    print(f"Published {len(photos)} photos from {len(albums)} albums; skipped {len(skipped)} → {data_file}")


if __name__ == "__main__":
    main()

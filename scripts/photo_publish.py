#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


STAGES = [
    (1, "square", "Generate the sibling N_black folder with square black-border images"),
    (2, "metadata", "Create missing _meta sidecars and mark new photos for publication"),
    (3, "analyze", "Run local Gemma tags, OpenCV metrics, and SigLIP embeddings"),
    (4, "publish-local", "Build web copies and merge this shoot into the local site repository"),
    (5, "verify", "Verify manifests and generated web files for this shoot"),
    (6, "git-handoff", "Show repository changes and suggest commit/push commands without running them"),
    (7, "release", "Commit repository changes and push them to trigger the site deployment"),
]
DEFAULT_LAST_STAGE = 6
STAGE_BY_NAME = {name: number for number, name, _ in STAGES}
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_config(explicit: str | None) -> tuple[dict[str, Any], Path]:
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    environment = os.environ.get("PHOTO_PUBLISH_CONFIG")
    if environment:
        candidates.append(Path(environment).expanduser())
    candidates.extend([
        Path(__file__).resolve().with_name("photo_publish.config.json"),
        Path("~/work/photo-gallery-site/config/photo_publish.config.json").expanduser(),
    ])
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise SystemExit("No photo_publish.config.json found; pass --config or set PHOTO_PUBLISH_CONFIG")
    return read_json(path), path


def resolve_config_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def parse_stage(value: str) -> int:
    if value.isdigit() and 1 <= int(value) <= len(STAGES):
        return int(value)
    if value in STAGE_BY_NAME:
        return STAGE_BY_NAME[value]
    names = ", ".join(f"{number}:{name}" for number, name, _ in STAGES)
    raise argparse.ArgumentTypeError(f"Unknown stage {value!r}; use {names}")


def validate_source(source: Path, archive: Path) -> tuple[Path, str]:
    source = source.resolve()
    archive = archive.resolve()
    if not source.is_dir() or not source.name.isdigit():
        raise SystemExit("Run photo_publish from a numeric folder such as .../08-30 - Regensburg/2")
    shoot = source.parent
    try:
        relative = shoot.relative_to(archive).as_posix()
    except ValueError as error:
        raise SystemExit(f"Current folder is outside the configured archive: {source}") from error
    if not shoot.parent.name.isdigit():
        raise SystemExit("Expected archive layout: PhotoArchive/YYYY/shoot/N")
    return shoot, relative


def source_fingerprint(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        (item for item in source.iterdir() if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda item: item.name.casefold(),
    ):
        stat = path.stat()
        digest.update(f"{path.name}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def run(command: list[str], cwd: Path | None = None) -> None:
    print("$ " + " ".join(shlex.quote(item) for item in command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def ensure_metadata(project: Path, source: Path, shoot: Path, relative: str) -> None:
    sys.path.insert(0, str(project / "scripts"))
    from archive_metadata import SCHEMA_VERSION, image_files, metadata_path, photo_id, slugify, write_json_atomic as write_sidecar

    album_path = shoot / "_meta" / "album.json"
    album = read_json(album_path)
    album.update({
        "schemaVersion": SCHEMA_VERSION,
        "id": slugify(relative),
        "archivePath": relative,
        "sourceTier": int(source.name),
        "updatedAt": now(),
    })
    write_sidecar(album_path, album)
    created = preserved = 0
    for image in image_files(source):
        path = metadata_path(shoot, image)
        if path.exists():
            preserved += 1
            continue
        stat = image.stat()
        document = {
            "schemaVersion": SCHEMA_VERSION,
            "id": photo_id(image),
            "source": {
                "path": image.relative_to(shoot).as_posix(),
                "tier": int(source.name),
                "sha256": None,
                "size": stat.st_size,
                "mtimeNs": stat.st_mtime_ns,
            },
            "analysis": {
                "status": "missing",
                "models": {},
                "inputMaxEdge": None,
                "generatedAt": None,
                "description": "",
                "semantic": {},
                "visual": {},
                "embedding": [],
            },
            "tags": {"manual": [], "generated": []},
            "publication": {"published": True},
            "editorial": {"description": None, "shotScale": None, "peopleCount": None, "updatedAt": None},
        }
        write_sidecar(path, document)
        created += 1
    print(f"Metadata: created {created}, preserved {preserved}")


def verify_publish(project: Path, source: Path, shoot: Path, relative: str) -> None:
    sys.path.insert(0, str(project / "scripts"))
    from archive_metadata import image_files, metadata_path, photo_id, read_json as read_sidecar, slugify

    album_id = slugify(relative)
    gallery = read_json(project / "public" / "data" / "gallery.json")
    filters = read_json(project / "public" / "data" / "photo-filters.json")
    expected = {
        photo_id(image) for image in image_files(source)
        if read_sidecar(metadata_path(shoot, image)).get("publication", {}).get("published", False)
    }
    gallery_ids = {photo["id"] for photo in gallery.get("photos", []) if photo.get("albumId") == album_id}
    filter_ids = {photo["id"] for photo in filters.get("photos", []) if photo.get("albumId") == album_id}
    if gallery_ids != expected or filter_ids != expected:
        raise RuntimeError(
            f"Manifest mismatch for {album_id}: expected {len(expected)}, gallery {len(gallery_ids)}, filters {len(filter_ids)}"
        )
    missing = []
    for identifier in expected:
        for variant in ("web", "thumbs"):
            path = project / "public" / "gallery" / album_id / variant / f"{identifier}.webp"
            if not path.is_file() or path.stat().st_size == 0:
                missing.append(str(path))
    if missing:
        raise RuntimeError("Missing generated files:\n" + "\n".join(missing))
    print(f"Verified {len(expected)} published photos for {relative}")


def release_message(relative: str, config: dict[str, Any]) -> str:
    template = str(config.get("commitMessageTemplate", "Publish {shoot}"))
    shoot_name = Path(relative).name.strip(" -")
    try:
        return template.format(shoot=shoot_name, archive_path=relative)
    except (KeyError, ValueError) as error:
        raise RuntimeError(f"Invalid commitMessageTemplate: {template!r}") from error


def show_git_handoff(project: Path, relative: str, config: dict[str, Any]) -> None:
    result = subprocess.run(["git", "status", "--short"], cwd=project, text=True, capture_output=True, check=True)
    print("\nRepository changes:")
    print(result.stdout.rstrip() or "(none)")
    message = release_message(relative, config)
    print("\nNothing was committed or pushed.")
    print("When the local result is approved, review and run separately:")
    print(f"  cd {shlex.quote(str(project))}")
    print("  git status --short")
    print("  git add <reviewed files>")
    print(f"  git commit -m {shlex.quote(message)}")
    print(f"  git push {shlex.quote(str(config.get('gitRemote', 'origin')))} {shlex.quote(str(config.get('gitBranch', 'main')))}")
    print("Or run the explicit release stage:")
    print("  photo_publish --stage release")


def release_site(project: Path, relative: str, config: dict[str, Any]) -> None:
    remote = str(config.get("gitRemote", "origin"))
    branch = str(config.get("gitBranch", "main"))
    message = release_message(relative, config)

    current_branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=project, text=True, capture_output=True, check=True
    ).stdout.strip()
    if current_branch != branch:
        raise RuntimeError(f"Release requires branch {branch!r}; current branch is {current_branch!r}")

    remotes = subprocess.run(
        ["git", "remote"], cwd=project, text=True, capture_output=True, check=True
    ).stdout.splitlines()
    if remote not in remotes:
        raise RuntimeError(f"Git remote {remote!r} is not configured")

    run(["git", "diff", "--check"], cwd=project)
    run(["git", "add", "--all"], cwd=project)
    run(["git", "diff", "--cached", "--check"], cwd=project)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=project)
    if staged.returncode == 1:
        run(["git", "commit", "-m", message], cwd=project)
    elif staged.returncode == 0:
        print("No repository changes to commit.")
    else:
        raise RuntimeError("Unable to inspect staged Git changes")

    run(["git", "push", remote, branch], cwd=project)
    revision = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=project, text=True, capture_output=True, check=True
    ).stdout.strip()
    print(f"Released commit {revision}. The push triggers the GitHub Pages workflow.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resumable local photo publication pipeline. Run it from a numeric source folder.",
        epilog="Default: resume through stage 6. Stage 7 (release) must be selected explicitly.",
    )
    parser.add_argument("--config", help="Path to photo_publish.config.json")
    parser.add_argument("--source", default=".", help="Numeric source folder; defaults to the current directory")
    parser.add_argument("--from-stage", type=parse_stage, help="Run this stage and every following stage")
    parser.add_argument("--stage", type=parse_stage, help="Run only one stage")
    parser.add_argument("--force", action="store_true", help="Run selected stages even if their checkpoint is complete")
    parser.add_argument("--list-stages", action="store_true")
    args = parser.parse_args()

    if args.list_stages:
        for number, name, description in STAGES:
            print(f"{number}. {name:<14} {description}")
        return
    if args.stage and args.from_stage:
        parser.error("Use either --stage or --from-stage, not both")

    config, config_path = load_config(args.config)
    project = resolve_config_path(config["galleryRepo"], config_path.parent)
    archive = resolve_config_path(config["archiveRoot"], config_path.parent)
    source = Path(args.source).expanduser().resolve()
    shoot, relative = validate_source(source, archive)
    if not project.is_dir():
        raise SystemExit(f"Gallery repository does not exist: {project}")
    analysis_python_value = Path(config["analysisPython"]).expanduser()
    analysis_python = analysis_python_value if analysis_python_value.is_absolute() else project / analysis_python_value
    analysis_python = analysis_python.absolute()
    if not analysis_python.is_file():
        raise SystemExit(f"Analysis Python does not exist: {analysis_python}")
    make_square = shutil.which(config.get("makeSquareCommand", "make_square"))
    if not make_square:
        raise SystemExit("make_square is not available on PATH")

    checkpoint_path = shoot / "_meta" / "pipeline.json"
    checkpoint = read_json(checkpoint_path)
    fingerprint = source_fingerprint(source)
    if checkpoint.get("sourcePath") != str(source) or checkpoint.get("sourceFingerprint") != fingerprint:
        checkpoint = {
            "version": 1,
            "sourcePath": str(source),
            "sourceFingerprint": fingerprint,
            "shoot": relative,
            "stages": {},
        }

    functions: dict[int, Callable[[], None]] = {
        1: lambda: run([make_square, str(source)]),
        2: lambda: ensure_metadata(project, source, shoot, relative),
        3: lambda: run([
            str(analysis_python),
            str(project / "scripts" / "analyze_library.py"),
            "--config", str(project / "config" / "analysis.config.json"),
            "--source", str(source),
        ], cwd=source),
        4: lambda: run([sys.executable, str(project / "scripts" / "publish.py"), "--source", str(source), "--merge"], cwd=project),
        5: lambda: verify_publish(project, source, shoot, relative),
        6: lambda: show_git_handoff(project, relative, config),
        7: lambda: release_site(project, relative, config),
    }

    if args.stage:
        stage_numbers = [args.stage]
    elif args.from_stage:
        last_stage = len(STAGES) if args.from_stage == len(STAGES) else DEFAULT_LAST_STAGE
        stage_numbers = list(range(args.from_stage, last_stage + 1))
    elif args.force:
        stage_numbers = list(range(1, DEFAULT_LAST_STAGE + 1))
    else:
        first_unfinished = next(
            (
                number
                for number, _, _ in STAGES[:DEFAULT_LAST_STAGE]
                if checkpoint.get("stages", {}).get(str(number), {}).get("status") != "completed"
            ),
            None,
        )
        if first_unfinished is None:
            print("Local stages 1-6 are complete. Use --stage release to commit, push, and deploy.")
            return
        stage_numbers = list(range(first_unfinished, DEFAULT_LAST_STAGE + 1))

    print(f"Source: {source}")
    print(f"Shoot:  {relative}")
    print(f"Stages: {', '.join(str(number) for number in stage_numbers)}")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    for number in stage_numbers:
        _, name, description = STAGES[number - 1]
        status = checkpoint.setdefault("stages", {}).get(str(number), {})
        if status.get("status") == "completed" and not (args.force or args.stage or args.from_stage):
            print(f"\n[{number}/{len(STAGES)}] {name}: already complete")
            continue
        print(f"\n[{number}/{len(STAGES)}] {name}: {description}", flush=True)
        checkpoint["stages"][str(number)] = {"name": name, "status": "running", "startedAt": now()}
        checkpoint["updatedAt"] = now()
        write_json_atomic(checkpoint_path, checkpoint)
        try:
            functions[number]()
        except KeyboardInterrupt:
            checkpoint["stages"][str(number)].update({"status": "interrupted", "stoppedAt": now()})
            checkpoint["updatedAt"] = now()
            write_json_atomic(checkpoint_path, checkpoint)
            print(f"\nInterrupted during stage {number} ({name}). Run photo_publish again to resume here.")
            raise SystemExit(130)
        except Exception as error:
            checkpoint["stages"][str(number)].update({"status": "failed", "failedAt": now(), "error": str(error)})
            checkpoint["updatedAt"] = now()
            write_json_atomic(checkpoint_path, checkpoint)
            raise
        checkpoint["stages"][str(number)].update({"status": "completed", "completedAt": now()})
        checkpoint["updatedAt"] = now()
        write_json_atomic(checkpoint_path, checkpoint)

    if len(STAGES) in stage_numbers:
        print("\nRelease finished: changes were committed and pushed; GitHub Pages deployment was triggered.")
    else:
        print("\nLocal pipeline finished. No commit or push was performed. Run --stage release explicitly to deploy.")


if __name__ == "__main__":
    main()

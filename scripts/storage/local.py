from __future__ import annotations
import shutil
from pathlib import Path

class LocalStorage:
    """Mirrors each published album into the configured local web directory."""
    def __init__(self, output_root: Path): self.output_root = output_root
    def sync_album(self, album_id: str, staged_album: Path) -> Path:
        destination = self.output_root / album_id
        if destination.exists(): shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged_album, destination)
        return destination

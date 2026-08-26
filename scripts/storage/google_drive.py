from __future__ import annotations
from pathlib import Path

class GoogleDriveStorage:
    """Stable adapter boundary for the future Google Drive public web area."""
    def __init__(self, public_folder_id: str, credentials_env: str):
        self.public_folder_id = public_folder_id
        self.credentials_env = credentials_env
    def sync_album(self, album_id: str, staged_album: Path) -> Path:
        raise RuntimeError("Google Drive storage is configured but not connected yet. Implement upload + mirror deletion here, using the folder ID and credentials from " + self.credentials_env + ".")

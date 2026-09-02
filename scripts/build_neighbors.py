#!/usr/bin/env python3
"""Build public neighbor IDs from private archive embeddings; never copy vectors."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from archive_metadata import read_json, write_json_atomic
from publish import load_config, resolve_project_path, slugify


def nearest_neighbors(vectors: dict[str, list[float]], count: int) -> dict[str, list[str]]:
    keys = sorted(vectors)
    if not keys:
        return {}
    matrix = np.asarray([vectors[key] for key in keys], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    result = {}
    # Bounded memory, even for larger libraries. Stable ties follow the photo key.
    for start in range(0, len(keys), 256):
        scores = matrix[start:start + 256] @ matrix.T
        for offset, row in enumerate(scores):
            index = start + offset
            row[index] = -np.inf
            ranked = np.argsort(-row, kind="stable")[:min(count, len(keys) - 1)]
            result[keys[index]] = [keys[int(other)] for other in ranked]
    return result


def build_index(archive: Path, photos: list[dict], count: int) -> dict:
    published = {f"{photo['albumId']}/{photo['id']}" for photo in photos}
    groups = defaultdict(dict)
    seen = set()
    for shoot in sorted(archive.glob('*/*')):
        if not shoot.is_dir():
            continue
        album_id = read_json(shoot / 'metadata' / 'album.json').get('id') or slugify(shoot.relative_to(archive).as_posix())
        for sidecar in sorted((shoot / '_meta' / 'photos').glob('*.json')):
            document = read_json(sidecar)
            key = f"{album_id}/{document.get('id', sidecar.stem)}"
            if key not in published:
                continue
            analysis = document.get('analysis', {})
            model = analysis.get('models', {}).get('embedding')
            embedding = analysis.get('embedding')
            if not isinstance(model, str) or not model or not isinstance(embedding, list) or not embedding:
                continue
            try:
                vector = np.asarray(embedding, dtype=np.float32)
            except (ValueError, TypeError):
                continue
            if vector.ndim != 1 or not np.isfinite(vector).all() or not 0 < np.linalg.norm(vector) < np.inf:
                continue
            if key in seen:
                raise ValueError(f'Duplicate archive photo key: {key}')
            seen.add(key)
            # Never compare different embedding spaces, even if dimensions match.
            groups[(model, len(vector))][key] = embedding
    neighbors = {key: [] for key in sorted(published)}
    for vectors in groups.values():
        neighbors.update(nearest_neighbors(vectors, count))
    return {
        'version': 1, 'generatedAt': datetime.now(timezone.utc).isoformat(),
        'metric': 'cosine', 'neighborCount': count,
        'photoCount': len(published), 'embeddingCount': len(seen),
        'missingEmbeddingCount': len(published - seen), 'neighbors': neighbors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/gallery.config.json')
    parser.add_argument('--overlay')
    args = parser.parse_args()
    config = load_config(resolve_project_path(args.config), resolve_project_path(args.overlay) if args.overlay else None)
    settings = config['neighbors']
    count = int(settings.get('count', 10))
    if count < 2:
        raise SystemExit('neighbors.count must be at least 2')
    archive = resolve_project_path(config['archiveRoot'])
    if not archive.is_dir():
        raise SystemExit(f'Archive does not exist: {archive}')
    manifest = json.loads(resolve_project_path(config['dataFile']).read_text(encoding='utf-8'))
    index = build_index(archive, manifest['photos'], count)
    destination = resolve_project_path(settings['file'])
    write_json_atomic(destination, index)
    print(f"Neighbors: {index['embeddingCount']}/{index['photoCount']} embeddings, {index['missingEmbeddingCount']} missing → {destination}")


if __name__ == '__main__':
    main()

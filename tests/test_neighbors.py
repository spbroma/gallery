import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_neighbors import build_index, nearest_neighbors


class NeighborTests(unittest.TestCase):
    def test_cosine_normalization_and_self_exclusion(self):
        result = nearest_neighbors({'a': [10, 0], 'b': [2, 1], 'c': [-1, 0], 'd': [0, 2]}, 10)
        self.assertEqual(result['a'], ['b', 'd', 'c'])
        for key, neighbors in result.items():
            self.assertNotIn(key, neighbors)
            self.assertEqual(len(neighbors), 3)
        self.assertEqual(nearest_neighbors({'a': [1, 0]}, 10), {'a': []})
        self.assertEqual(nearest_neighbors({}, 10), {})

    def test_model_spaces_missing_vectors_and_publication_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            folder = archive / '2026' / 'shoot' / '_meta' / 'photos'
            folder.mkdir(parents=True)
            values = {
                'a': ('first', [1, 0]), 'b': ('first', [1, 1]),
                'private': ('first', [1, 0]), 'other-model': ('second', [1, 0]),
                'other-size': ('first', [1, 0, 0]), 'zero': ('first', [0, 0]),
                'invalid': ('first', [float('nan'), 0]),
            }
            for key, (model, embedding) in values.items():
                (folder / f'{key}.json').write_text(json.dumps({'id': key, 'analysis': {'models': {'embedding': model}, 'embedding': embedding}}))
            photos = [{'id': key, 'albumId': '2026-shoot'} for key in [*values, 'missing'] if key != 'private']
            result = build_index(archive, photos, 10)
            self.assertEqual(result['embeddingCount'], 4)
            self.assertEqual(result['missingEmbeddingCount'], 3)
            self.assertEqual(result['neighbors']['2026-shoot/a'], ['2026-shoot/b'])
            self.assertEqual(result['neighbors']['2026-shoot/other-model'], [])
            self.assertNotIn('2026-shoot/private', result['neighbors'])
            self.assertNotIn('embedding', result)


if __name__ == '__main__':
    unittest.main()

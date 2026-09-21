import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from publish import assign_link_ids  # noqa: E402


class PublishLinkIdsTest(unittest.TestCase):
    def test_uses_capture_timestamp_without_exposing_filename(self):
        photos = [{
            'id': 'dsc00394', 'albumId': 'berlin', 'date': '2026-09-15',
            'capturedAt': '2026-09-15T18:42:07',
        }]

        assign_link_ids(photos)

        self.assertEqual(photos[0]['linkId'], '20260915-184207')

    def test_resolves_same_second_collisions_stably(self):
        photos = [
            {'id': 'a', 'albumId': 'shoot', 'date': '2026-09-15', 'capturedAt': '2026-09-15T18:42:07'},
            {'id': 'b', 'albumId': 'shoot', 'date': '2026-09-15', 'capturedAt': '2026-09-15T18:42:07'},
        ]

        assign_link_ids(photos)

        self.assertEqual(photos[0]['linkId'], '20260915-184207')
        self.assertRegex(photos[1]['linkId'], r'^20260915-184207-[0-9a-f]{6}$')
        self.assertNotIn('b', photos[1]['linkId'])


if __name__ == '__main__':
    unittest.main()

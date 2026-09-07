import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from admin_server import Library
from archive_metadata import metadata_path


class AdminDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.archive = Path(self.temp.name)
        self.shoot = self.archive / '2026' / 'shoot'
        self.source = self.shoot / '1'
        self.source.mkdir(parents=True)
        self.image = self.source / 'a.jpg'
        self.image.write_bytes(b'image')
        self.sidecar = metadata_path(self.shoot, self.image)
        self.sidecar.parent.mkdir(parents=True)
        self.sidecar.write_text(json.dumps({
            'id': 'a', 'analysis': {'semantic': {}, 'visual': {}},
            'tags': {'manual': ['old'], 'generated': ['model']},
            'publication': {'published': False}, 'editorial': {},
        }))
        self.library = Library(self.archive)

    def tearDown(self):
        self.library.draft_file.unlink(missing_ok=True)
        self.library.metadata_file.unlink(missing_ok=True)
        self.temp.cleanup()

    def test_metadata_saves_immediately_while_publication_stays_draft(self):
        before = self.sidecar.read_bytes()
        draft = self.library.stage([{'shoot': '2026/shoot', 'id': 'a', 'published': True}])
        self.assertEqual(self.sidecar.read_bytes(), before)
        self.assertTrue(self.library.photos('2026/shoot')[0]['published'])
        self.assertFalse(self.library.photos('2026/shoot')[0]['actualPublished'])
        self.assertTrue(self.library.photos('2026/shoot')[0]['pending'])
        self.assertEqual(len(draft), 1)

        self.library.save_photo({'shoot': '2026/shoot', 'id': 'a', 'manualTags': ['new'], 'generatedTags': ['model'], 'description': 'local', 'shotScale': 'wide', 'peopleCount': 2})
        saved = json.loads(self.sidecar.read_text())
        self.assertEqual(saved['tags']['manual'], ['new'])
        self.assertEqual(saved['editorial']['description'], 'local')
        self.assertFalse(saved['publication']['published'])
        self.assertEqual(len(self.library.draft_view()), 1)
        self.assertEqual(self.library.draft_state()['metadataDirty'][0]['fields'], ['description', 'manualTags', 'peopleCount', 'shotScale'])
        self.assertTrue(self.library.photos('2026/shoot')[0]['metadataPending'])

    def test_apply_publishes_and_rebuilds_then_clears_draft(self):
        self.library.stage([{'shoot': '2026/shoot', 'id': 'a', 'published': True}])
        with patch.object(self.library, 'run_logged', return_value='Published 1 photo') as run:
            result = self.library.apply(release=False)
        self.assertTrue(json.loads(self.sidecar.read_text())['publication']['published'])
        self.assertEqual(result['appliedCount'], 1)
        self.assertEqual(result['metadataCount'], 0)
        self.assertEqual(self.library.draft_view(), [])
        self.assertEqual(run.call_count, 2)
        analysis_command = run.call_args_list[0].args[0]
        self.assertIn('analyze_library.py', analysis_command[1])
        self.assertEqual(analysis_command[-2:], ['--photo-id', 'a'])

    def test_failed_rebuild_restores_sidecar_and_keeps_draft(self):
        original = self.sidecar.read_bytes()
        self.library.stage([{'shoot': '2026/shoot', 'id': 'a', 'published': True}])
        with patch.object(self.library, 'run_logged', side_effect=subprocess.CalledProcessError(1, 'publish', stderr='broken')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.library.apply(release=False)
        self.assertEqual(self.sidecar.read_bytes(), original)
        self.assertEqual(len(self.library.draft_view()), 1)

    def test_metadata_only_apply_rebuilds_site(self):
        self.library.save_photo({'shoot': '2026/shoot', 'id': 'a', 'manualTags': ['new'], 'generatedTags': ['model'], 'description': '', 'shotScale': 'unknown', 'peopleCount': 0})
        with patch.object(self.library, 'run_logged', return_value='rebuilt'):
            result = self.library.apply(release=False)
        self.assertEqual(result, {'appliedCount': 0, 'metadataCount': 1, 'output': 'rebuilt', 'releasePending': False})
        state = self.library.draft_state()
        self.assertEqual(state['draft'], [])
        self.assertEqual(state['metadataDirty'], [])

    def test_problem_view_reports_missing_analysis_fields(self):
        photo = self.library.photos('2026/shoot')[0]
        self.assertEqual(photo['shoot'], '2026/shoot')
        self.assertIn('analysis incomplete', photo['issues'])
        self.assertIn('embedding missing', photo['issues'])
        self.assertIn('description missing', photo['issues'])
        self.assertEqual(self.library.all_photos(True), [])
        self.library.stage([{'shoot': '2026/shoot', 'id': 'a', 'published': True}])
        self.assertEqual([item['id'] for item in self.library.all_photos(True)], ['a'])


if __name__ == '__main__':
    unittest.main()

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import backup
import pipeline

ROOT = Path(__file__).resolve().parent.parent


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)/'workspace'
        app = self.ws/'apps'/'demo'
        for rel, data in {'app.json': b'{}', 'jobs/a.json': b'{"id": "a"}', 'plans/plan.md': b'# plan',
                          'exports/a/video.mp4': b'v' * 10, 'raw/a.mp4': b'r', 'review/a/sheet.png': b's',
                          'assets/icon.png': b'icon', '.queue.lock': b'1', 'jobs/b.json.tmp': b'x'}.items():
            (app/rel).parent.mkdir(parents=True, exist_ok=True)
            (app/rel).write_bytes(data)
        self.drive = Path(self.tmp.name)/'drive'
        self.cfg = pipeline.config(ROOT/'config.example.json')
        self.cfg['workspace'] = str(self.ws)
        self.cfg['backup'] = {'dir': str(Path(self.tmp.name)/'ikinci-disk'), 'keep': 2}
        self.cfg['mcp'].update(transport='stdio', command=sys.executable, args=[str(ROOT/'tests'/'mock_mcp.py')],
                               env={'TEST_BACKUP_DIR': str(self.drive)}, timeout_seconds=30)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zip_skips_media_and_lock_files(self):
        path, count, big = backup.make(self.cfg, 'x')
        with zipfile.ZipFile(path) as z:
            names = sorted(z.namelist())
        self.assertEqual(names, ['demo/app.json', 'demo/assets/icon.png', 'demo/jobs/a.json', 'demo/plans/plan.md'])
        self.assertEqual((count, big), (4, []))
        self.cfg['backup']['max_file_mb'] = 0  # every non-empty file is now "too big"
        _, count, big = backup.make(self.cfg, 'y')
        self.assertEqual((count, len(big)), (0, 4))

    def test_backup_sends_to_drive_keeps_copies_and_restores(self):
        for _ in range(3):
            summary = backup.backup(self.cfg)
            self.assertIsNone(summary['drive_error'])
        self.assertLessEqual(len(list((self.ws/'backups').glob('apps-*.zip'))), 2)  # backup.keep = 2
        self.assertTrue(Path(summary['copy']).is_file())
        self.assertTrue((self.drive/Path(summary['zip']).name).is_file())
        (self.ws/'apps'/'demo'/'jobs'/'a.json').write_text('{"id": "changed"}', encoding='utf-8')
        staged = backup.restore(self.cfg, 'drive')
        self.assertFalse(staged['applied'])
        self.assertIn('changed', (self.ws/'apps'/'demo'/'jobs'/'a.json').read_text(encoding='utf-8'))
        applied = backup.restore(self.cfg, 'drive', apply=True)
        self.assertTrue(applied['applied'] and Path(applied['before']).is_file())
        self.assertEqual((self.ws/'apps'/'demo'/'jobs'/'a.json').read_text(encoding='utf-8'), '{"id": "a"}')
        self.assertTrue((self.ws/'apps'/'demo'/'exports'/'a'/'video.mp4').is_file())  # media is left alone

    def test_drive_failure_keeps_local_zip(self):
        self.cfg['mcp'].update(transport='http', url='http://127.0.0.1:9/mcp', timeout_seconds=2)
        summary = backup.backup(self.cfg)
        self.assertTrue(Path(summary['zip']).is_file())
        self.assertIsNone(summary['drive'])
        self.assertTrue(summary['drive_error'])

    def test_restore_rejects_unsafe_paths(self):
        bad = Path(self.tmp.name)/'bad.zip'
        with zipfile.ZipFile(bad, 'w') as z:
            z.writestr('../evil.txt', 'x')
        with self.assertRaisesRegex(ValueError, 'güvensiz'):
            backup.restore(self.cfg, str(bad))
        self.assertFalse((self.ws/'evil.txt').exists())


if __name__ == '__main__':
    unittest.main()

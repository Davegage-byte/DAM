"""Lokale DAM-Versionen: Schutz, Bereinigung und Wiederherstellung."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import dam_updater as updater


class VersionBackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.home_patch = patch.object(Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.root = updater.data_dir()
        self.versions = self.root / 'versions'
        self.versions.mkdir(parents=True)
        self.add_version('0.6.1')
        self.add_version('0.6.2')
        self.add_version('0.6.3')
        (self.root / 'current').symlink_to('versions/0.6.3')
        updater.state_dir().mkdir(parents=True)
        (updater.state_dir() / 'previous-version.txt').write_text('0.6.2\n', 'utf-8')

    def add_version(self, version, is_old=False):
        folder = self.versions / version
        folder.mkdir()
        (folder / 'dam.py').write_text("VERSION = %r\n" % version, 'utf-8')
        if not is_old:
            (folder / 'dam_updater.py').write_text('def update():\n    pass\n', 'utf-8')
        (folder / 'version.json').write_text(
            json.dumps({'schema': 1, 'version': version}), 'utf-8')
        return folder

    def rows(self):
        return {row['version']: row for row in updater.stored_versions()}

    def test_summary_protects_current_and_previous(self):
        rows = self.rows()
        self.assertTrue(rows['0.6.3']['active'])
        self.assertFalse(rows['0.6.3']['deletable'])
        self.assertTrue(rows['0.6.2']['rollback'])
        self.assertFalse(rows['0.6.2']['deletable'])
        self.assertTrue(rows['0.6.1']['deletable'])
        self.assertGreater(rows['0.6.1']['size_bytes'], 0)

    def test_manual_backup_protects_old_version(self):
        updater.protect_version('0.6.1')
        self.assertTrue(self.rows()['0.6.1']['pinned'])
        self.assertFalse(self.rows()['0.6.1']['deletable'])
        with self.assertRaises(updater.UpdateError):
            updater.delete_stored_versions(['0.6.1'])
        updater.protect_version('0.6.1', False)
        self.assertTrue(self.rows()['0.6.1']['deletable'])

    def test_backup_protects_current_after_future_update(self):
        updater.protect_version('0.6.3')
        self.add_version('0.6.4')
        updater._switch_current(self.root, '0.6.4')
        (updater.state_dir() / 'previous-version.txt').write_text('0.6.2\n')
        self.assertFalse(self.rows()['0.6.3']['deletable'])

    def test_deletion_frees_space_only_for_selected(self):
        size = self.rows()['0.6.1']['size_bytes']
        freed = updater.delete_stored_versions(['0.6.1'])
        self.assertEqual(freed, size)
        self.assertFalse((self.versions / '0.6.1').exists())
        self.assertTrue((self.versions / '0.6.2').exists())
        self.assertEqual(updater._current_version(self.root), '0.6.3')

    def test_protected_mixed_selection_is_atomic(self):
        with self.assertRaises(updater.UpdateError):
            updater.delete_stored_versions(['0.6.1', '0.6.3'])
        self.assertTrue((self.versions / '0.6.1').exists())

    def test_missing_or_corrupt_pin_registry_blocks_cleanup(self):
        pins = updater.state_dir() / 'backup-pins.json'
        pins.write_text('not-json', 'utf-8')
        with self.assertRaises(updater.UpdateError):
            updater.delete_stored_versions(['0.6.1'])
        self.assertTrue((self.versions / '0.6.1').exists())

    def test_symlinked_version_cannot_be_deleted(self):
        external = self.home / 'important'
        external.mkdir()
        (external / 'document.txt').write_text('keep', 'utf-8')
        (self.versions / '0.6.9').symlink_to(external, target_is_directory=True)
        with self.assertRaises(updater.UpdateError):
            updater.delete_stored_versions(['0.6.9'])
        self.assertTrue((external / 'document.txt').exists())

    def test_invalid_version_rejected(self):
        with self.assertRaises(updater.UpdateError):
            updater.delete_stored_versions(['../other'])
        with self.assertRaises(updater.UpdateError):
            updater.protect_version('../other')

    def test_restore_older_version(self):
        with patch.object(updater, '_wait_for_pid'):
            with patch.object(updater, '_launch_and_wait'):
                updater.restore(123, '0.6.1')
        self.assertEqual(updater._current_version(self.root), '0.6.1')
        self.assertEqual(updater._previous_version(), '0.6.3')

    def test_restore_rolls_back_after_failure(self):
        with patch.object(updater, '_wait_for_pid'):
            with patch.object(updater, '_launch_and_wait', side_effect=updater.UpdateError('Crash')):
                with patch.object(updater.subprocess, 'Popen'):
                    with self.assertRaises(updater.UpdateError):
                        updater.restore(123, '0.6.1')
        self.assertEqual(updater._current_version(self.root), '0.6.3')
        self.assertEqual(updater._previous_version(), '0.6.2')

    def test_legacy_version_cannot_be_restored(self):
        self.add_version('0.5.25', is_old=True)
        self.assertFalse(self.rows()['0.5.25']['restorable'])
        with self.assertRaises(updater.UpdateError):
            updater.validate_restoration('0.5.25')


if __name__ == '__main__':
    unittest.main()

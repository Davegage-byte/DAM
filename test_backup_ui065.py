"""DAM backup status and legacy/custom descriptions migration tests."""
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def extract_function(name):
    source = (Path(__file__).parent / 'dam.py').read_text(encoding='utf-8')
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    globals_ = {'os': os, 'json': json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<dam-extracted>', 'exec'), globals_)
    return globals_[name]


class BackupProtectionLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.action = staticmethod(extract_function('backup_protection_action'))

    def test_current_version_never_offers_unpin(self):
        for pinned in (False, True):
            label, enabled = self.action(
                {'active': True, 'rollback': False, 'pinned': pinned})
            self.assertEqual(label, 'Aktiv 🔒')
            self.assertFalse(enabled)

    def test_previous_version_never_offers_unpin(self):
        for pinned in (False, True):
            label, enabled = self.action(
                {'active': False, 'rollback': True, 'pinned': pinned})
            self.assertEqual(label, 'Rückfallversion 🔒')
            self.assertFalse(enabled)

    def test_older_version_can_be_saved_and_unpinned(self):
        base = {'active': False, 'rollback': False}
        self.assertEqual(self.action({**base, 'pinned': False}), ('Behalten', True))
        self.assertEqual(self.action({**base, 'pinned': True}), ('Schutz aufheben', True))


class DescriptionLocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.load = staticmethod(extract_function('custom_descriptions'))

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = patch.dict(os.environ, {'HOME': str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, file, values):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')

    def test_new_config_location(self):
        self.save(self.root / '.config/dam/app_beschreibungen.json',
                  {' GIMP ': ' Eigener Text '})
        self.assertEqual(self.load(), {'gimp': 'Eigener Text'})

    def test_legacy_location_remains_readable(self):
        self.save(self.root / 'DAM/app_beschreibungen.json',
                  {'firefox': 'Meine Beschreibung'})
        self.assertEqual(self.load(), {'firefox': 'Meine Beschreibung'})

    def test_new_location_has_priority(self):
        self.save(self.root / 'DAM/app_beschreibungen.json', {'firefox': 'Alt'})
        self.save(self.root / '.config/dam/app_beschreibungen.json',
                  {'firefox': 'Neu'})
        self.assertEqual(self.load(), {'firefox': 'Neu'})

    def test_no_file_returns_empty_dict_without_creation(self):
        self.assertEqual(self.load(), {})
        self.assertFalse((self.root / '.config/dam').exists())


if __name__ == '__main__':
    unittest.main()

"""DAM 0.6.2: benutzerlokales DAM wird auch ohne Gio-AppInfo gefunden."""
import ast
from pathlib import Path
import os
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import package_updates

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
APP_CLASS = next(node for node in ast.parse(SOURCE).body
                 if isinstance(node, ast.ClassDef) and node.name == 'DAM')


def method(name, globals_):
    node = next(node for node in APP_CLASS.body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<dam-extracted>', 'exec'), globals_)
    return globals_[name]


class LocalDAMCatalogTests(unittest.TestCase):
    def make_catalog(self, installed):
        fake = types.SimpleNamespace(get_apps=Mock(return_value=installed))
        method_fn = method('make_app_lists', {
            'os': os,
            'VERSION': '0.6.2',
            'CATALOG': [('DAM', 'dam', 'de.davegage.dam')],
            'Gio': Mock(),
            'describe_app': lambda *_: 'DAM-App-Manager',
        })
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            starter = home / '.local/share/applications/de.davegage.dam.desktop'
            starter.parent.mkdir(parents=True)
            starter.write_text('[Desktop Entry]\nName=DAM\n')
            icon = home / '.local/share/icons/hicolor/256x256/apps/de.davegage.dam.png'
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b'PNG')
            with patch.dict(os.environ, {'HOME': directory}):
                return method_fn(fake, {}, {}, {}, {}, {})

    def test_dam_is_available_for_updates_without_gio_entry(self):
        installed, available = self.make_catalog([])
        self.assertEqual([item['name'] for item in installed], ['DAM'])
        self.assertEqual(installed[0]['version'], '0.6.2')
        self.assertFalse(installed[0]['is_removable'])
        self.assertEqual(installed[0]['package'], 'dam')
        self.assertEqual([x['name'] for x in available], ['DAM'])

    def test_no_duplicate_when_gio_reports_dam(self):
        existing = {'name': 'DAM', 'package': 'dam', 'version': '0.6.2'}
        installed, _ = self.make_catalog([existing])
        self.assertEqual(len(installed), 1)
        self.assertIs(installed[0], existing)


class DAMUpdatePresentationTests(unittest.TestCase):
    def make_fake(self):
        row = {'name': 'DAM', 'beschreibung': 'DAM-App-Manager',
               'version': '0.6.0', 'tile_widget': Mock(),
               'caption_widget': Mock(), 'update': None}
        return types.SimpleNamespace(
            _update_scan_generation=2, set_list_loading=Mock(), update_ui_lock=Mock(),
            update_check_button=Mock(), rustdesk_release=None, dam_release=None,
            update_rows={object(): row}, update_flow=Mock(),
            update_selection_info=Mock(), update_select_all=Mock(),
            update_select_button=Mock(), update_all_button=Mock(),
            update_empty_label=Mock(), update_check_info=Mock(), update_status=Mock()), row

    def finish(self, fake, errors=(), release=None):
        fn = method('finish_update_check', {
            'package_updates': package_updates,
            'VERSION': '0.6.0',
        })
        return fn(fake, [], list(errors), 1, None, 2, release)

    def test_detected_dam_release_reaches_visible_tile(self):
        fake, row = self.make_fake()
        self.finish(fake, release=types.SimpleNamespace(version='0.6.2'))
        self.assertEqual(row['update'].source, 'dam')
        row['caption_widget'].set_text.assert_called_once_with('0.6.0 → 0.6.2')
        fake.update_select_button.set_sensitive.assert_called_with(True)
        fake.update_check_info.set_text.assert_called_with('1 App-Update(s) verfügbar')

    def test_partial_failure_has_visible_reason(self):
        fake, row = self.make_fake()
        self.finish(fake, errors=['GitHub/RustDesk: HTTP 429'])
        self.assertIsNone(row['update'])
        last = fake.update_status.set_text.call_args.args[0]
        self.assertIn('GitHub/RustDesk: HTTP 429', last)


if __name__ == '__main__':
    unittest.main()

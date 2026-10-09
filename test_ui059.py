"""Regressionstest für stabile Ladeansicht und DAM-Eintrag im Installieren-Katalog."""
import ast
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import unittest

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
DAM = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')

def method_text(name):
    node = next(n for n in DAM.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SOURCE, node)

class DAM059Tests(unittest.TestCase):
    def test_dam_is_in_catalog(self):
        self.assertIn("('DAM', 'dam', 'de.davegage.dam')", SOURCE)
        self.assertIn("'dam': 'Programme installieren, aktualisieren und deinstallieren.'", SOURCE)

    def test_dam_uses_its_desktop_entry_for_context_menu(self):
        segment = method_text('make_app_lists')
        self.assertIn('~/.local/share/applications/de.davegage.dam.desktop', segment)
        self.assertIn("is_installed = os.path.isfile(launcher)", segment)
        self.assertIn('desktop_file=launcher if is_installed else None', segment)
        self.assertIn('version=VERSION if is_installed else None', segment)
        self.assertIn('apt_candidate=None', segment)

    def test_spinner_is_native_and_not_bound_to_removed_page(self):
        self.assertIn('self.list_spinner.start()', method_text('set_list_loading'))
        self.assertIn('self.list_spinner.stop()', method_text('set_list_loading'))
        self.assertIn('self._refresh_plan = {', method_text('finish_app_list_refresh'))
        self.assertIn('GLib.timeout_add(35, self._rebuild_refresh_step)', method_text('_rebuild_refresh_step'))

    def test_loading_overlay_does_not_resize_window(self):
        segment = method_text('start')
        self.assertIn('app_area.set_measure_overlay(panel, False)', segment)
        self.assertIn('panel.set_size_request(330, 132)', segment)
        self.assertIn('caption.set_size_request(294, 26)', segment)

    def test_no_password_saved_in_dam(self):
        self.assertNotIn('sudo -S', SOURCE)
        self.assertNotIn('password_entry', SOURCE)

if __name__ == '__main__':
    unittest.main()

"""DAM v0.5.5 UI tests, executable without the GTK stack."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock

src = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
tree = ast.parse(src)
dam = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')
methods = {n.name: ast.get_source_segment(src, n) for n in dam.body if isinstance(n, ast.FunctionDef)}

class UI055Tests(unittest.TestCase):
    def test_button_starts_neutral_not_suggested(self):
        self.assertIn("selection_button.add_css_class('dam-selection-button')", methods['add_page'])
        self.assertNotIn("selection_button.add_css_class('suggested-action')", methods['add_page'])

    def test_button_orange_only_after_selection(self):
        self.assertIn("selection_button.add_css_class('dam-has-selection')", methods['add_page'])
        self.assertIn("selection_button.remove_css_class('dam-has-selection')", methods['add_page'])
        self.assertIn('button.dam-selection-button.dam-has-selection', methods['add_style'])
        self.assertIn('background-color: @accent_bg_color;', methods['add_style'])
        self.assertIn("tile.connect('toggled', refresh_count)", methods['add_page'])

    def test_native_spinner_instead_of_text_frames(self):
        self.assertIn('Gtk.Spinner()', methods['start'])
        self.assertIn('self.list_spinner.start()', methods['set_list_loading'])
        self.assertIn('self.list_spinner.stop()', methods['set_list_loading'])
        self.assertNotIn('DAMActivityRing', src)

    def test_refresh_is_staggered_and_global_loader_survives(self):
        method = methods['finish_app_list_refresh']
        step = methods['_rebuild_refresh_step']
        self.assertIn('GLib.timeout_add(35, self._rebuild_refresh_step)', method)
        self.assertIn('self.add_page(self.stack, key, title, apps, verb)', step)
        self.assertIn('self.set_list_loading(False)', step)
        self.assertNotIn('list_loading_widgets.clear()', step)

if __name__ == '__main__':
    unittest.main()

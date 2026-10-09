"""Static UI regression tests; keep runnable without GTK installed."""
import ast
from pathlib import Path
import unittest

src = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
tree = ast.parse(src)
dam = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'DAM')
methods = {node.name: ast.get_source_segment(src, node) for node in dam.body
           if isinstance(node, ast.FunctionDef)}

class Ui054Tests(unittest.TestCase):
    def test_selection_has_solid_accent_background(self):
        self.assertIn('background-color: @accent_bg_color;', methods['add_style'])
        self.assertIn('color: @accent_fg_color;', methods['add_style'])
        self.assertIn('.dam-tile.dam-installed:checked', methods['add_style'])

    def test_large_loader_above_app_list(self):
        start = methods['start']
        self.assertIn('app_area = Gtk.Overlay()', start)
        self.assertIn('spinner = Gtk.Spinner()', start)
        self.assertIn("spinner.add_css_class('dam-loading-spinner')", start)
        self.assertIn('app_area.set_measure_overlay(panel, False)', start)
        self.assertIn('self.list_spinner = spinner', start)

    def test_loader_entire_refresh_lifecycle(self):
        self.assertIn('self.set_list_loading(True)', methods['refresh_app_lists'])
        self.assertIn('self.set_list_loading(False)', methods['finish_app_list_refresh'])

if __name__ == '__main__':
    unittest.main()

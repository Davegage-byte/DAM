"""DAM v0.5.11: Startfenster ist kompakter, Scrollansicht bleibt flexibel."""
import ast
from pathlib import Path
import unittest
SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
APP = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')

def method(name):
    return ast.get_source_segment(SOURCE, next(n for n in APP.body if isinstance(n, ast.FunctionDef) and n.name == name))

class WindowSizeTest(unittest.TestCase):
    def test_default_height(self):
        self.assertIn('self.window.set_default_size(1000, 640)', method('start'))
    def test_scroll_areas_remain_expandable(self):
        self.assertIn('scroll.set_vexpand(True)', method('add_page'))
    def test_spinner_unmodified(self):
        self.assertIn('spinner = Gtk.Spinner()', method('start'))
        self.assertIn('app_area.set_measure_overlay(panel, False)', method('start'))

if __name__ == '__main__':
    unittest.main()

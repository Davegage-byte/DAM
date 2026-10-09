"""DAM v0.5.7 – Layout-Regressionstests für Buttons."""
from pathlib import Path
import ast
import unittest

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
APP = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')
ADD_PAGE = next(n for n in APP.body if isinstance(n, ast.FunctionDef) and n.name == 'add_page')
ADD_STYLE = next(n for n in APP.body if isinstance(n, ast.FunctionDef) and n.name == 'add_style')

class ButtonLayoutTests(unittest.TestCase):
    def test_select_all_width_does_not_change_with_text(self):
        code = ast.get_source_segment(SOURCE, ADD_PAGE)
        self.assertIn("select_all.set_size_request(190, 48)", code)
        self.assertIn("select_all.set_label('Alle abwählen'", code)
        self.assertIn("else 'Alle auswählen'", code)
        self.assertEqual(code.count('select_all.set_size_request('), 1)
    def test_action_buttons_are_larger(self):
        code = ast.get_source_segment(SOURCE, ADD_PAGE)
        self.assertIn('selection_button.set_size_request(285, 48)', code)
        self.assertIn('all_button.set_size_request(205, 48)', code)
        self.assertEqual(code.count("add_css_class('dam-main-action')"), 3)
    def test_style_is_legible_and_applies_to_tabs(self):
        code = ast.get_source_segment(SOURCE, ADD_STYLE)
        self.assertIn('button.dam-main-action', code)
        self.assertIn('font-size: 15px', code)
        self.assertIn('.dam-navigation button', code)
        self.assertIn('button.dam-check-updates', code)
    def test_default_window_compact_but_resizable(self):
        self.assertIn('self.window.set_default_size(1000, 640)', SOURCE)

if __name__ == '__main__':
    unittest.main()

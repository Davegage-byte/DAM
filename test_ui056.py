"""DAM v0.5.6: checks for the toggle behavior in all tabs."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
APP = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')
ADD_PAGE = next(n for n in APP.body if isinstance(n, ast.FunctionDef) and n.name == 'add_page')

class SelectAllTests(unittest.TestCase):
    def test_refresh_updates_label_for_complete_selection(self):
        func = next(n for n in ast.walk(ADD_PAGE) if isinstance(n, ast.FunctionDef) and n.name == 'refresh_count')
        body = ast.get_source_segment(SOURCE, func)
        self.assertIn("select_all.set_label('Alle abwählen'", body)
        self.assertIn("else 'Alle auswählen'", body)
        self.assertIn('row.get_child_visible()', body)
        self.assertIn('row.get_child().get_sensitive()', body)
    def test_toggle_all_can_mark_and_unmark(self):
        func = next(n for n in ast.walk(ADD_PAGE) if isinstance(n, ast.FunctionDef) and n.name == 'toggle_all')
        body = ast.get_source_segment(SOURCE, func)
        self.assertIn('not all(tile.get_active() for tile in relevant)', body)
        self.assertIn('tile.set_active(mark)', body)
        self.assertIn('refresh_count()', body)
    def test_manual_selection_and_search_refresh_label(self):
        body = ast.get_source_segment(SOURCE, ADD_PAGE)
        self.assertIn("tile.connect('toggled', refresh_count)", body)
        search = next(n for n in ast.walk(ADD_PAGE) if isinstance(n, ast.FunctionDef) and n.name == 'on_search')
        self.assertIn('refresh_count()', ast.get_source_segment(SOURCE, search))
    def test_update_scan_resets_label(self):
        finish = next(n for n in APP.body if isinstance(n, ast.FunctionDef) and n.name == 'finish_update_check')
        self.assertIn("self.update_select_all.set_label('Alle auswählen')", ast.get_source_segment(SOURCE, finish))

if __name__ == '__main__':
    unittest.main()

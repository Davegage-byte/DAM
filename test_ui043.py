"""Statische Regressionstests für die neuen GTK-Oberflächen-Funktionen."""
from pathlib import Path
import ast
import unittest

class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).with_name('dam.py').read_text()
        cls.tree = ast.parse(cls.source)
        cls.dam = next(node for node in cls.tree.body if isinstance(node, ast.ClassDef) and node.name == 'DAM')

    def test_quit_action_is_registered(self):
        method = next(n for n in self.dam.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        body = ast.get_source_segment(self.source, method)
        self.assertIn("Gio.SimpleAction.new('quit', None)", body)
        self.assertIn("self.set_accels_for_action('app.quit', ['<Primary>q'])", body)
        self.assertIn('self.quit()', body)

    def test_installed_tile_style_only_on_install_page(self):
        method = next(n for n in self.dam.body if isinstance(n, ast.FunctionDef) and n.name == 'add_page')
        body = ast.get_source_segment(self.source, method)
        self.assertIn("if key == 'install' and item.get('is_installed'):", body)
        self.assertIn("tile.add_css_class('dam-installed')", body)
        self.assertIn('detail.set_text(f"Installiert', body)

    def test_installed_caption_uses_two_lines(self):
        method = next(n for n in self.dam.body if isinstance(n, ast.FunctionDef) and n.name == 'add_page')
        body = ast.get_source_segment(self.source, method)
        self.assertIn(r'Installiert\n', body)
        self.assertNotIn('Bereits installiert:', body)

    def test_css_selection_border_has_priority(self):
        method = next(n for n in self.dam.body if isinstance(n, ast.FunctionDef) and n.name == 'add_style')
        body = ast.get_source_segment(self.source, method)
        self.assertIn('.dam-tile.dam-installed', body)
        self.assertIn('.dam-tile.dam-installed:checked', body)
        self.assertIn('border: 2px solid transparent;', body)

if __name__ == '__main__':
    unittest.main()

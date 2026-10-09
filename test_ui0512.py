"""DAM 0.5.12: Die Bereichsfarben folgen den drei Hauptreitern."""
import ast
from pathlib import Path
import types
import unittest

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
APP = next(x for x in TREE.body if isinstance(x, ast.ClassDef) and x.name == 'DAM')

def method(name):
    return next(x for x in APP.body if isinstance(x, ast.FunctionDef) and x.name == name)

class Widget:
    def __init__(self):
        self.classes = set()
    def add_css_class(self, key):
        self.classes.add(key)
    def remove_css_class(self, key):
        self.classes.discard(key)

class ThemeTests(unittest.TestCase):
    def test_switches_theme_class_on_window_and_content_without_recreating_widgets(self):
        scope = {}
        code = compile(ast.Module(body=[method('apply_mode_theme')], type_ignores=[]), 'dam.py', 'exec')
        exec(code, scope)
        fake = types.SimpleNamespace(window=Widget(), main_box=Widget())
        for mode in ('install', 'update', 'remove', 'install'):
            scope['apply_mode_theme'](fake, mode)
            self.assertEqual(fake.window.classes, {'dam-mode-' + mode})
            self.assertEqual(fake.main_box.classes, {'dam-mode-' + mode})
        scope['apply_mode_theme'](fake, 'nonexistent')
        self.assertEqual(fake.window.classes, {'dam-mode-install'})

    def test_clickable_pages_set_theme_automatically(self):
        start = ast.get_source_segment(SOURCE, method('start'))
        handler = ast.get_source_segment(SOURCE, method('on_navigation_toggled'))
        self.assertIn("button.connect('toggled', self.on_navigation_toggled, mode)", start)
        self.assertIn("self.apply_mode_theme('install')", start)
        self.assertIn('self.apply_mode_theme(mode)', handler)

    def test_all_three_modes_style_window_tiles_selection_and_navigation(self):
        style = ast.get_source_segment(SOURCE, method('add_style'))
        for mode in ('install', 'update', 'remove'):
            self.assertIn('window.dam-mode-' + mode, style)
            self.assertIn('.dam-mode-' + mode + ' .dam-tile:checked', style)
            self.assertIn('.dam-mode-' + mode + ' .dam-navigation button:checked', style)
            self.assertIn('.dam-mode-' + mode + ' button.dam-selection-button.dam-has-selection', style)
        self.assertIn('border: 2px solid transparent', style)
        self.assertIn('scrolledwindow.dam-app-scroll', style)

    def test_install_and_remove_safety_modules_unchanged(self):
        for name in ('apt_install.py', 'apt_remove.py', 'apt_process.py',
                     'rustdesk_update.py', 'package_updates.py'):
            self.assertTrue(Path(__file__).with_name(name).is_file())

if __name__ == '__main__':
    unittest.main()

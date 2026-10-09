"""DAM 0.5.18: schnelleres RGB und markierter Info-Button."""
import ast
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

SRC = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
CLS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'DAM')

def method(name):
    node = next(node for node in CLS.body if isinstance(node, ast.FunctionDef) and node.name == name)
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'dam.py', 'exec'), scope)
    return scope[name]

class InfoAnimationTests(TestCase):
    def test_faster_colorful_keyframes(self):
        self.assertIn('animation-duration: 15s;', SRC)
        for color in ('#69341d', '#583078', '#185778', '#21624a', '#74344d'):
            self.assertIn(color, SRC)
        self.assertIn('prefers-reduced-motion: reduce', SRC)

    def test_info_button_selected_and_unselected(self):
        info = Mock()
        install = Mock()
        fake = Mock(_current_nav_mode='install', _last_main_mode='install',
                    info_button=info, nav_buttons={'install': install})
        toggle = method('toggle_info')
        toggle(fake, None)
        info.set_active.assert_called_once_with(True)
        fake._current_nav_mode = 'info'
        toggle(fake, None)
        install.set_active.assert_called_once_with(True)

    def test_nav_switch_clears_info_selection(self):
        fake = Mock()
        button = Mock()
        button.get_active.return_value = True
        method('on_navigation_toggled')(fake, button, 'remove')
        fake.stack.set_visible_child_name.assert_called_with('remove')
        fake.content_stack.set_visible_child_name.assert_called_with('apps')
        fake.apply_mode_theme.assert_called_with('remove')

    def test_active_info_highlight_css(self):
        self.assertIn('.dam-mode-info button.dam-info-toggle:checked', SRC)
        self.assertIn('.dam-navigation button:not(:checked)', SRC)

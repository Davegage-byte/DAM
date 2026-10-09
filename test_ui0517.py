"""DAM v0.5.17: Info-Trennlinie, animiertes Theme und einheitliche Toolbars."""
from pathlib import Path
import ast
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
CLS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')


def code(name):
    node = next(n for n in CLS.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SOURCE, node)


def method(name):
    node = next(n for n in CLS.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'dam.py', 'exec'), scope)
    return scope[name]


class InfoModeTests(unittest.TestCase):
    def test_info_theme_applied_and_restored_on_toggle(self):
        content = Mock()
        content.get_visible_child_name.side_effect = ['apps', 'info']
        stack = Mock()
        stack.get_visible_child_name.return_value = 'remove'
        info = Mock()
        remove = Mock()
        fake = Mock(_current_nav_mode='remove', _last_main_mode='remove',
                    info_button=info, nav_buttons={'remove': remove})
        method('toggle_info')(fake, None)
        info.set_active.assert_called_once_with(True)
        fake._current_nav_mode = 'info'
        method('toggle_info')(fake, None)
        remove.set_active.assert_called_once_with(True)

    def test_four_css_classes_are_swapped(self):
        fake = Mock()
        fake.window = Mock()
        fake.main_box = Mock()
        method('apply_mode_theme')(fake, 'info')
        for node in (fake.window, fake.main_box):
            node.add_css_class.assert_called_once_with('dam-mode-info')
            self.assertEqual(node.remove_css_class.call_count, 4)

    def test_info_button_keeps_separator_and_neutral_background(self):
        css = code('add_style')
        self.assertIn('border-left-width: 1px;', css)
        self.assertIn('button.dam-info-toggle {', css)
        self.assertIn('.dam-navigation button:not(:checked)', css)
        self.assertIn('.dam-navigation button:not(:checked)', css)
        self.assertIn('background-color: transparent;', css)

    def test_info_color_animation_and_reduced_motion(self):
        css = code('add_style')
        self.assertIn('@keyframes dam-info-ambient', css)
        self.assertIn('animation-duration: 15s;', css)
        self.assertIn('@media (prefers-reduced-motion: reduce)', css)

    def test_search_fields_and_update_button_share_height_group(self):
        self.assertIn('self.search_size_group = Gtk.SizeGroup', code('__init__'))
        page = code('add_page')
        self.assertIn("self.search_size_group.add_widget(search)", page)
        self.assertIn("self.search_size_group.add_widget(self.update_check_button)", page)
        self.assertIn('search.set_size_request(-1, 48)', page)
        self.assertIn('self.update_check_button.set_size_request(-1, 48)', page)

    def test_loader_keeps_outer_size_and_moves_only_content(self):
        self.assertIn('panel.set_size_request(330, 132)', code('start'))
        self.assertIn('padding: 18px 24px 6px 24px;', code('add_style'))


if __name__ == '__main__':
    unittest.main()

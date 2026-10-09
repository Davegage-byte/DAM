"""DAM 0.5.21: einheitliche Footer-Position, RGB 15s und Info-Ruecknavigation."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
CLASS = next(x for x in TREE.body if isinstance(x, ast.ClassDef) and x.name == 'DAM')


def source(name):
    node = next(x for x in CLASS.body if isinstance(x, ast.FunctionDef) and x.name == name)
    return ast.get_source_segment(SOURCE, node)


def method(name):
    node = next(x for x in CLASS.body if isinstance(x, ast.FunctionDef) and x.name == name)
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'dam.py', 'exec'), scope)
    return scope[name]


class FooterTests(TestCase):
    def test_all_tabs_share_a_fixed_height_footer(self):
        page = source('add_page')
        self.assertIn("footer.add_css_class('dam-actions-footer')", page)
        self.assertIn('footer.append(actions)', page)
        self.assertIn('footer.append(progress_row)', page)
        self.assertIn('page.append(footer)', page)
        self.assertIn('progress_row.set_size_request(-1, 28)', page)
        self.assertNotIn('page.append(actions)', page)
        self.assertNotIn('page.append(status)', page)
        self.assertNotIn('page.append(progress_row)', page)
        self.assertIn('status.set_ellipsize(Pango.EllipsizeMode.END)', page)

    def test_existing_progress_indicators_stay_for_install_and_remove(self):
        page = source('add_page')
        self.assertIn("if key in ('install', 'remove'):", page)
        self.assertIn('self.operation_spinners[key] = spinner', page)
        self.assertIn('self.operation_statuses[key] = status', page)


class InfoNavigationTests(TestCase):
    def test_four_buttons_share_one_group(self):
        start = source('start')
        self.assertIn("('install', '📦 Installieren')", start)
        self.assertIn("('update', '🔄 Aktualisieren')", start)
        self.assertIn("('remove', '🗑️ Deinstallieren')", start)
        self.assertIn("('info', 'ⓘ')", start)
        self.assertIn('button.set_group(first_button)', start)
        self.assertIn("button.connect('toggled', self.on_navigation_toggled, mode)", start)
        self.assertNotIn('Gtk.StackSwitcher(', start)
        self.assertNotIn('Gtk.GestureClick', start)

    def test_info_to_different_tab_changes_target_without_old_tab(self):
        fake = SimpleNamespace(content_stack=Mock(), stack=Mock(),
                               info_button=Mock(), _current_nav_mode='info',
                               _last_main_mode='install', _update_tab_visited=False,
                               maybe_start_first_update_check=Mock(),
                               apply_mode_theme=Mock())
        b = Mock(); b.get_active.return_value = True
        method('on_navigation_toggled')(fake, b, 'remove')
        fake.stack.set_visible_child_name.assert_called_once_with('remove')
        fake.content_stack.set_visible_child_name.assert_called_once_with('apps')
        fake.apply_mode_theme.assert_called_once_with('remove')
        self.assertEqual(fake._last_main_mode, 'remove')
        fake.maybe_start_first_update_check.assert_not_called()

    def test_info_does_not_reveal_previous_app_tab(self):
        fake = SimpleNamespace(content_stack=Mock(), stack=Mock(),
                               info_button=Mock(), _current_nav_mode='install',
                               _last_main_mode='install', apply_mode_theme=Mock())
        b = Mock(); b.get_active.return_value = True
        method('on_navigation_toggled')(fake, b, 'info')
        fake.content_stack.set_visible_child_name.assert_called_once_with('info')
        fake.stack.set_visible_child_name.assert_not_called()
        fake.apply_mode_theme.assert_called_once_with('info')

    def test_back_button_uses_same_group(self):
        install = Mock(); info = Mock()
        fake = SimpleNamespace(_current_nav_mode='info', _last_main_mode='install',
                               nav_buttons={'install': install}, info_button=info)
        method('toggle_info')(fake, None)
        install.set_active.assert_called_once_with(True)

class AnimationTests(TestCase):
    def test_same_fifteen_second_cycle_background_and_info_button(self):
        css = source('add_style')
        self.assertEqual(css.count('animation-duration: 15s;'), 2)
        self.assertNotIn('animation-duration: 8s;', css)
        self.assertIn('animation-timing-function: linear;', css)
        self.assertIn('animation-iteration-count: infinite;', css)

if __name__ == '__main__':
    import unittest
    unittest.main()

"""DAM v0.5.24: gruppierte Navigation, Hover und Footer-Anordnung."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

SRC = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')


def source(name):
    node = next(n for n in CLASS.body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, node)


def methods():
    scope = {'GLib': SimpleNamespace(idle_add=lambda fn: pending.append(fn))}
    for name in ('on_navigation_toggled', 'ensure_navigation_selected', 'toggle_info'):
        node = next(n for n in CLASS.body
                    if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'dam.py', 'exec'), scope)
    return scope


pending = []


class NavButton:
    def __init__(self, owner, mode):
        self.owner, self.mode, self.active = owner, mode, False
        self.tooltip = ''

    def get_active(self):
        return self.active

    def set_tooltip_text(self, message):
        self.tooltip = message

    def set_active(self, active):
        if active == self.active:
            return
        if active:
            for other in self.owner.nav_buttons.values():
                if other is not self and other.active:
                    other.active = False
                    self.owner.on_navigation_toggled(other, other.mode)
        self.active = active
        self.owner.on_navigation_toggled(self, self.mode)


class NavigationTests(TestCase):
    def setUp(self):
        pending.clear()
        self.log = []
        self.fake = SimpleNamespace(
            _current_nav_mode='install', _last_main_mode='install',
            _update_tab_visited=False, maybe_start_first_update_check=Mock(),
            stack=Mock(), content_stack=Mock(), apply_mode_theme=Mock())
        scope = methods()
        self.fake.on_navigation_toggled = lambda btn, mode: scope['on_navigation_toggled'](self.fake, btn, mode)
        self.fake.ensure_navigation_selected = lambda: scope['ensure_navigation_selected'](self.fake)
        self.fake.toggle_info = lambda b=None: scope['toggle_info'](self.fake, b)
        self.fake.nav_buttons = {mode: NavButton(self.fake, mode)
                                 for mode in ('install', 'update', 'remove', 'info')}
        self.fake.info_button = self.fake.nav_buttons['info']
        self.fake.nav_buttons['install'].set_active(True)
        self.fake.stack.reset_mock()
        self.fake.content_stack.reset_mock()
        self.fake.apply_mode_theme.reset_mock()

    def flush(self):
        while pending:
            pending.pop(0)()

    def test_switching_info_returns_to_same_previous_tab(self):
        self.fake.nav_buttons['info'].set_active(True)
        self.flush()
        self.assertFalse(self.fake.nav_buttons['install'].active)
        self.assertTrue(self.fake.nav_buttons['info'].active)
        self.fake.nav_buttons['install'].set_active(True)
        self.flush()
        self.assertTrue(self.fake.nav_buttons['install'].active)
        self.assertFalse(self.fake.nav_buttons['info'].active)
        self.fake.content_stack.set_visible_child_name.assert_called_with('apps')
        self.fake.apply_mode_theme.assert_called_with('install')

    def test_info_to_different_tab_does_not_flash_old_tab(self):
        self.fake.nav_buttons['info'].set_active(True)
        self.fake.stack.reset_mock()
        self.fake.nav_buttons['remove'].set_active(True)
        self.flush()
        self.fake.stack.set_visible_child_name.assert_called_once_with('remove')
        self.fake.apply_mode_theme.assert_called_with('remove')
        self.assertTrue(self.fake.nav_buttons['remove'].active)

    def test_update_scan_only_on_update_tab(self):
        self.fake.nav_buttons['info'].set_active(True)
        self.fake.nav_buttons['remove'].set_active(True)
        self.assertFalse(self.fake._update_tab_visited)
        self.fake.maybe_start_first_update_check.assert_not_called()
        self.fake.nav_buttons['update'].set_active(True)
        self.assertTrue(self.fake._update_tab_visited)
        self.fake.maybe_start_first_update_check.assert_called_once()

    def test_clicking_already_active_button_restores_selection(self):
        self.fake.nav_buttons['install'].set_active(False)
        self.flush()
        self.assertTrue(self.fake.nav_buttons['install'].active)

    def test_info_back_button_uses_same_navigation_group(self):
        self.fake.nav_buttons['remove'].set_active(True)
        self.fake.nav_buttons['info'].set_active(True)
        self.fake.toggle_info()
        self.assertTrue(self.fake.nav_buttons['remove'].active)
        self.assertFalse(self.fake.nav_buttons['info'].active)


class LayoutTests(TestCase):
    def test_navigation_has_one_css_for_all_inactive_and_hover(self):
        css = source('add_style')
        self.assertIn('.dam-navigation button:not(:checked):hover', css)
        self.assertIn('.dam-mode-info button.dam-info-toggle:checked', css)
        self.assertNotIn('dam-info-active', SRC)
        self.assertIn('button.set_group(first_button)', source('start'))

    def test_center_messages_move_up(self):
        self.assertIn('panel.set_margin_bottom(168)', source('start'))
        self.assertIn('self.update_empty_label.set_margin_bottom(76)', source('add_page'))

    def test_status_over_actions_and_buttons_lower(self):
        page = source('add_page')
        self.assertLess(page.index('footer.append(progress_row)'),
                        page.index('footer.append(actions)'))
        self.assertIn('page.set_margin_bottom(20)', page)
        self.assertIn('progress_row.set_size_request(-1, 28)', page)

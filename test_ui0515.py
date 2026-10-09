"""DAM v0.5.15 regression tests: lazy updates, info page and button count."""
import ast
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace
import unittest

SRC = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
CLS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')

def source(name):
    node = next(n for n in CLS.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, node)

class FakeGLib:
    idle_add = Mock()

class UpdatesTests(unittest.TestCase):
    def test_does_not_scan_on_startup_or_page_creation(self):
        self.assertNotIn('check_updates)', source('start'))
        self.assertNotIn('GLib.idle_add(self.check_updates)', source('add_page'))
        self.assertIn("if self.stack.get_visible_child_name() == 'update':", source('_rebuild_refresh_step'))

    def test_first_visit_once_even_after_revisits(self):
        node = next(n for n in CLS.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'maybe_start_first_update_check')
        scope = {'GLib': FakeGLib}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'dam.py', 'exec'), scope)
        fn = scope['maybe_start_first_update_check']
        FakeGLib.idle_add.reset_mock()
        fake = SimpleNamespace(_update_tab_visited=False, _first_update_check_done=False,
                               _initial_loading=False, list_refresh_running=False,
                               _catalog_ready=True,
                               check_updates=Mock())
        fn(fake)
        FakeGLib.idle_add.assert_not_called()
        fake._update_tab_visited=True
        fake.list_refresh_running=True
        fn(fake)
        FakeGLib.idle_add.assert_not_called()
        fake.list_refresh_running=False
        fn(fake)
        FakeGLib.idle_add.assert_called_once_with(fake.check_updates)
        fn(fake)
        FakeGLib.idle_add.assert_called_once()

    def test_update_scan_shows_shared_loader_with_correct_color(self):
        check = source('check_updates')
        self.assertIn("self.apply_mode_theme('update')", check)
        self.assertIn("self.set_list_loading(True, 'Updates werden geprüft …')", check)
        self.assertIn('self.set_list_loading(False)', source('finish_update_check'))

    def test_info_button_is_next_to_three_tabs_and_opens_info_page(self):
        start=source('start')
        self.assertIn("('info', 'ⓘ')", start)
        self.assertIn('Gtk.ToggleButton(label=label)', start)
        self.assertIn('button.set_group(first_button)', start)
        self.assertIn("self.content_stack.add_named(self.create_info_page(), 'info')", start)
        self.assertIn('navigation.append(button)', start)
        self.assertIn("self.nav_buttons[self._last_main_mode].set_active(True)", source('toggle_info'))
        self.assertIn("box.append(self.update_check_info)", source('create_info_page'))
        self.assertNotIn('footer =', start)

    def test_selection_count_is_on_button_not_underneath(self):
        page=source('add_page')
        self.assertIn("selection_button.set_label(f'Auswahl {verb.capitalize()} ({selected})')", page)
        self.assertIn("Gtk.Button(label=f'Auswahl {verb.capitalize()} (0)')", page)
        self.assertNotIn('page.append(selection_info)', page)
        self.assertIn("status = Gtk.Label(label='')", page)
        self.assertNotIn('page.append(update_bar)', page)

if __name__ == '__main__':
    unittest.main()

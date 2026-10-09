"""DAM v0.5.15: schneller Start und erst nach Reiterbesuch prüfen."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
APP = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')

def method(name):
    node = next(n for n in APP.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SOURCE, node)


class StartupAndToolbarTests(unittest.TestCase):
    def test_window_before_package_scan(self):
        start = method('start')
        self.assertNotIn('packages = package_info()', start)
        self.assertNotIn('dates = package_dates()', start)
        self.assertNotIn('external = external_package_versions()', start)
        self.assertNotIn('self.make_app_lists(', start)
        self.assertLess(start.index('self.window.present()'), start.index('GLib.timeout_add(80, self._begin_startup_scan)'))
        self.assertIn("self.refresh_app_lists(0, operation='startup')", method('_begin_startup_scan'))

    def test_background_refresh_collects_package_information(self):
        refresh = method('refresh_app_lists')
        self.assertIn('def worker():', refresh)
        for expected in ('package_info()', 'package_dates()', 'external_package_versions()', 'apt_install.candidate(package)'):
            self.assertIn(expected, refresh)
        self.assertIn('threading.Thread(target=worker, daemon=True).start()', refresh)

    def test_update_button_is_in_search_toolbar_after_sort(self):
        add_page = method('add_page')
        self.assertIn("Gtk.Button(label='Nach Updates suchen')", add_page)
        self.assertIn('toolbar.append(self.update_check_button)', add_page)
        self.assertNotIn('update_bar.append(self.update_check_button)', add_page)
        self.assertLess(add_page.index('toolbar.append(sort)'), add_page.index('toolbar.append(self.update_check_button)'))

    def test_update_check_waits_until_data_is_loaded(self):
        check = method('check_updates')
        self.assertIn('self._initial_loading or self.list_refresh_running', check)
        rebuild = method('_rebuild_refresh_step')
        self.assertIn('self._initial_loading = False', rebuild)
        self.assertIn('self.maybe_start_first_update_check()', rebuild)
        self.assertNotIn('GLib.idle_add(self.check_updates)', method('add_page'))
        self.assertIn('self._update_tab_visited = True', method('on_navigation_toggled'))
        self.assertIn('GLib.idle_add(self.check_updates)', method('maybe_start_first_update_check'))
        self.assertIn("if operation == 'startup':", rebuild)

if __name__ == '__main__':
    unittest.main()

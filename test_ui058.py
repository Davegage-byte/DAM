"""Regression checks for GTK native spinner and responsive refresh."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
DAM = next(x for x in TREE.body if isinstance(x, ast.ClassDef) and x.name == 'DAM')

def method(name):
    node = next(x for x in DAM.body if isinstance(x, ast.FunctionDef) and x.name == name)
    return ast.get_source_segment(SOURCE, node)

class SpinnerTests(unittest.TestCase):
    def test_loader_is_native_gtk_spinner(self):
        self.assertIn('spinner = Gtk.Spinner()', method('start'))
        self.assertIn("spinner.set_size_request(56, 56)", method('start'))
        self.assertIn("spinner.dam-loading-spinner", method('add_style'))
        self.assertIn('self.list_spinner.start()', method('set_list_loading'))
        self.assertIn('self.list_spinner.stop()', method('set_list_loading'))

    def test_global_overlay_avoids_window_resize(self):
        self.assertIn('app_area.set_measure_overlay(panel, False)', method('start'))
        self.assertIn('panel.set_size_request(330, 132)', method('start'))
        self.assertIn('caption.set_size_request(294, 26)', method('start'))
        # Ein lokales Overlay für mittige Update-Hinweise ist erlaubt,
        # solange es nicht in die Größenmessung einbezogen wird.
        self.assertIn('message_overlay.set_measure_overlay(self.update_empty_label, False)', method('add_page'))

    def test_expensive_candidates_get_prefetched(self):
        self.assertIn('candidates = {package: apt_install.candidate(package)', method('refresh_app_lists'))
        self.assertIn('candidates.get(package)', method('make_app_lists'))

    def test_rebuild_yields_between_tabs(self):
        self.assertIn('GLib.timeout_add(35, self._rebuild_refresh_step)', method('finish_app_list_refresh'))
        self.assertIn('GLib.timeout_add(35, self._rebuild_refresh_step)', method('_rebuild_refresh_step'))
        self.assertIn('self.set_list_loading(False)', method('_rebuild_refresh_step'))

if __name__ == '__main__': unittest.main()

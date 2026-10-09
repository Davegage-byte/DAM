"""DAM v0.5.23: Meldungen auf gleicher horizontaler und vertikaler Achse."""
import ast
from pathlib import Path
from unittest import TestCase

SRC = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
APP = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')

def method(name):
    return ast.get_source_segment(SRC, next(n for n in APP.body
                                  if isinstance(n, ast.FunctionDef) and n.name == name))

class CenteredMessageTests(TestCase):
    def test_loader_uses_list_area_not_full_page(self):
        start = method('start')
        self.assertIn('panel.set_halign(Gtk.Align.CENTER)', start)
        self.assertIn('panel.set_valign(Gtk.Align.CENTER)', start)
        self.assertIn('panel.set_margin_top(58)', start)
        self.assertIn('panel.set_margin_bottom(168)', start)
        self.assertIn('app_area.set_measure_overlay(panel, False)', start)

    def test_results_center_in_scroll_region(self):
        page = method('add_page')
        self.assertIn('message_overlay.set_child(scroll)', page)
        self.assertIn('self.update_empty_label.set_halign(Gtk.Align.CENTER)', page)
        self.assertIn('self.update_empty_label.set_valign(Gtk.Align.CENTER)', page)

    def test_no_double_loading_messages(self):
        check = method('check_updates')
        self.assertIn("self.set_list_loading(True, 'Updates werden geprüft …')", check)
        self.assertIn('self.update_empty_label.set_visible(False)', check)
        self.assertNotIn("self.update_empty_label.set_visible(True)\n        self.update_empty_label.set_text('Updates werden geprüft …')", check)

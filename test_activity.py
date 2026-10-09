"""Prüfung, dass Paketaktionen eine laufende Statusanzeige besitzen."""
import ast
from pathlib import Path
import unittest

source = Path(__file__).with_name('dam.py').read_text()
tree = ast.parse(source)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')
methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

class StatusTests(unittest.TestCase):
    def test_progress_indicator_mounted_on_install_and_remove_pages(self):
        add_page = ast.get_source_segment(source, methods['add_page'])
        self.assertIn("key in ('install', 'remove')", add_page)
        self.assertIn('Gtk.Spinner()', add_page)
        self.assertIn('self.operation_spinners[key] = spinner', add_page)

    def test_remove_operation_starts_and_stops_spinner(self):
        for method, expected in (
            ('confirm_remove', "self.start_operation_indicator('remove'"),
            ('finish_remove_preview', "self.stop_operation_indicator('remove')"),
            ('start_remove', "self.start_operation_indicator('remove'"),
            ('finish_remove', "self.stop_operation_indicator('remove')"),
        ):
            self.assertIn(expected, ast.get_source_segment(source, methods[method]))

    def test_install_operation_starts_and_stops_spinner(self):
        self.assertIn("self.start_operation_indicator('install'", ast.get_source_segment(source, methods['install_apt']))
        self.assertIn("self.stop_operation_indicator('install')", ast.get_source_segment(source, methods['finish_apt_install']))

    def test_time_indication_not_percentage(self):
        status_code = ast.get_source_segment(source, methods['tick_operation_indicator'])
        self.assertIn('time.monotonic()', status_code)
        self.assertIn(' s', status_code)

if __name__ == '__main__':
    unittest.main()

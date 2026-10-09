"""DAM v0.5.16: Abbruch, Navigationssperre und kompaktere Oberfläche."""
import ast
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import package_updates

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


class ScanCancelTests(unittest.TestCase):
    def test_cancelled_subprocess_terminates_quickly(self):
        stop = threading.Event()
        thread = threading.Thread(target=lambda: (time.sleep(0.3), stop.set()), daemon=True)
        thread.start()
        start = time.monotonic()
        with self.assertRaises(package_updates.UpdateScanCancelled):
            package_updates.run([sys.executable, '-c', 'import time; time.sleep(8)'],
                                12, cancel_event=stop)
        self.assertLess(time.monotonic() - start, 3)
        thread.join(timeout=2)

    def test_precancel_prevents_process_start(self):
        stop = threading.Event()
        stop.set()
        with patch.object(package_updates.subprocess, 'Popen') as popen:
            with self.assertRaises(package_updates.UpdateScanCancelled):
                package_updates.run(['/bin/true'], 5, cancel_event=stop)
            popen.assert_not_called()

    def test_cancelled_check_does_not_change_packages(self):
        stop = threading.Event()
        stop.set()
        with patch.object(package_updates, 'run') as run:
            with self.assertRaises(package_updates.UpdateScanCancelled):
                package_updates.probe_updates(stop)
            run.assert_not_called()

    def test_escape_unlocks_and_discards_late_update_results(self):
        fake = SimpleNamespace(
            install_running=False, remove_running=False, update_install_running=False,
            update_check_running=True, list_refresh_running=False,
            _update_cancel_event=threading.Event(), _update_scan_generation=12,
            update_check_button=Mock(), update_empty_label=Mock(), update_check_info=Mock(),
            update_select_button=Mock(), update_all_button=Mock(), update_select_all=Mock(),
            set_list_loading=Mock(), update_ui_lock=Mock())
        cancellation = fake._update_cancel_event
        self.assertFalse(method('cancel_scan')(fake))
        self.assertTrue(cancellation.is_set())
        self.assertIsNone(fake._update_cancel_event)
        self.assertEqual(fake._update_scan_generation, 13)
        self.assertFalse(fake.update_check_running)
        fake.update_ui_lock.assert_called_once()
        late = method('finish_update_check')(fake, [], [], 1, None, 12)
        self.assertFalse(late)
        fake.update_ui_lock.assert_called_once()  # keine zweite Meldung

    def test_escape_never_cancels_package_installation(self):
        fake = SimpleNamespace(install_running=True, remove_running=False,
                               update_install_running=False, update_check_running=True,
                               _update_cancel_event=threading.Event())
        method('cancel_scan')(fake)
        self.assertFalse(fake._update_cancel_event.is_set())
        self.assertTrue(fake.update_check_running)

    def test_cancelled_refresh_result_is_ignored(self):
        fake = SimpleNamespace(_refresh_generation=9)
        result = method('finish_app_list_refresh')(fake, None, 0, None, 'startup', 8)
        self.assertFalse(result)

    def test_ui_is_locked_for_scans_and_package_operations(self):
        fake = SimpleNamespace(_initial_loading=False, list_refresh_running=False,
                               update_check_running=True, install_running=False,
                               remove_running=False, update_install_running=False,
                               stack=Mock(), switcher=Mock(), info_button=Mock())
        method('update_ui_lock')(fake)
        for name in ('stack', 'switcher', 'info_button'):
            getattr(fake, name).set_sensitive.assert_called_with(False)
        fake.update_check_running = False
        method('update_ui_lock')(fake)
        for name in ('stack', 'switcher', 'info_button'):
            getattr(fake, name).set_sensitive.assert_called_with(True)

    def test_equally_sized_search_and_joined_info_button(self):
        self.assertIn("search.add_css_class('dam-search-field')", code('add_page'))
        self.assertIn('search.set_size_request(-1, 48)', code('add_page'))
        self.assertIn('spacing=0', code('start'))
        self.assertIn('navigation.append(button)', code('start'))
        self.assertIn('button.set_valign(Gtk.Align.FILL)', code('start'))
        self.assertIn('panel.set_size_request(330, 132)', code('start'))
        self.assertIn('self.set_accels_for_action(\'app.cancel_scan\', [\'Escape\'])', code('__init__'))


if __name__ == '__main__':
    unittest.main()

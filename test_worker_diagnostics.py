"""Check watchdog and error-reporting guardrails without requiring GTK installed."""
import ast
from pathlib import Path
import unittest

SRC = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
CLS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'DAM')
METHODS = {node.name: node for node in CLS.body if isinstance(node, ast.FunctionDef)}

class WorkerDiagnosticsTests(unittest.TestCase):
    def test_worker_guarantees_completion_notification_in_finally(self):
        start = ast.get_source_segment(SRC, METHODS['start_remove'])
        self.assertIn('finally:', start)
        self.assertIn('GLib.idle_add(self.finish_remove, removed, status, error)', start)
        self.assertIn('except BaseException as exc:', start)

    def test_watchdog_detects_gone_worker_and_reconciles_list(self):
        wd = ast.get_source_segment(SRC, METHODS['watch_remove_completion'])
        self.assertIn('worker.is_alive()', wd)
        self.assertIn('self.stop_operation_indicator', wd)
        self.assertIn("self.refresh_app_lists(0, operation='remove_error')", wd)

    def test_logs_uncaught_exceptions_and_rotates(self):
        self.assertIn('RotatingFileHandler', SRC)
        self.assertIn('sys.excepthook = _log_uncaught', SRC)
        self.assertIn('~/.local/state/dam', SRC)

if __name__ == '__main__':
    unittest.main()

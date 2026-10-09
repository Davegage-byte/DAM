"""No desktop dependencies needed; tests for safe package and shortcut operations."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import app_shortcuts
import apt_install
import apt_remove
import apt_process
import subprocess
import sys
import time

class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.launcher = self.root / 'rustdesk.desktop'
        self.launcher.write_text('[Desktop Entry]\nType=Application\nName=RustDesk\nExec=rustdesk\nIcon=rustdesk\n', encoding='utf-8')
        self.app = {'desktop_id': 'rustdesk.desktop', 'desktop_file': str(self.launcher)}

    def test_desktop_id_sanitized(self):
        self.assertEqual(app_shortcuts.desktop_id(self.app), 'rustdesk.desktop')
        with self.assertRaises(ValueError):
            app_shortcuts.desktop_id({**self.app, 'desktop_id': '../../evil.desktop'})

    def test_desktop_shortcut_keeps_original(self):
        desktop = self.root / 'Desktop'; desktop.mkdir()
        with patch.object(app_shortcuts, 'desktop_folder', return_value=desktop):
            with patch.object(app_shortcuts.subprocess, 'run', return_value=Mock(returncode=0)):
                msg = app_shortcuts.create_desktop_shortcut(self.app)
                self.assertIn('erstellt', msg)
                self.assertEqual((desktop / 'rustdesk.desktop').read_text(), self.launcher.read_text())
                self.assertIn('bereits', app_shortcuts.create_desktop_shortcut(self.app))

    def test_autostart_safe_add_remove_and_preserve_foreign(self):
        with patch.object(Path, 'home', return_value=self.root):
            self.assertEqual(app_shortcuts.autostart_state(self.app), 'none')
            self.assertIn('hinzugefügt', app_shortcuts.add_autostart(self.app))
            self.assertEqual(app_shortcuts.autostart_state(self.app), 'managed')
            self.assertIn('entfernt', app_shortcuts.remove_autostart(self.app))
            self.assertEqual(app_shortcuts.autostart_state(self.app), 'none')
            path = app_shortcuts.autostart_file(self.app)
            path.write_text('[Desktop Entry]\nName=Custom\n', encoding='utf-8')
            self.assertEqual(app_shortcuts.autostart_state(self.app), 'foreign')
            with self.assertRaises(RuntimeError):
                app_shortcuts.remove_autostart(self.app)
            self.assertIn('Custom', path.read_text())

class AptTests(unittest.TestCase):
    def test_restricted_allowlist(self):
        apt_install.validate_packages(['vlc','gimp'])
        for invalid in (['rustdesk'], ['bash'], ['vlc','vlc'], ['vlc;touch foo'], []):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                apt_install.validate_packages(invalid)

    def test_candidate_parsing(self):
        with patch.object(apt_install, 'run', return_value=Mock(returncode=0, stdout='vlc:\n  Installed: (none)\n  Candidate: 3.0.20\n')):
            self.assertEqual(apt_install.candidate('vlc'), '3.0.20')
        self.assertIsNone(apt_install.candidate('rustdesk'))

    def test_simulate_reject_removals(self):
        with patch.object(apt_install, 'candidate', return_value='3.0'):
            with patch.object(apt_install, 'installed_version', return_value=None):
                with patch.object(apt_install, 'run', return_value=Mock(returncode=0, stdout='Remv bash [1.0]\n')):
                    with self.assertRaisesRegex(RuntimeError, 'entfernen'):
                        apt_install.simulate(['vlc'])

    def test_install_not_called_when_plan_bad(self):
        with patch.object(apt_install, 'simulate', side_effect=RuntimeError('plan fail')):
            with patch.object(apt_install, 'run') as exec_command:
                with self.assertRaisesRegex(RuntimeError,'plan fail'):
                    apt_install.install(['vlc'])
                exec_command.assert_not_called()

class AptProcessTests(unittest.TestCase):
    def test_reject_unapproved_command(self):
        with self.assertRaises(ValueError):
            apt_process.elevated_apt(['bash', '-c', 'true'])

    def test_no_wait_for_grandchild_open_output(self):
        # An orphan holds inherited stdout open briefly after the parent exits.
        # A pipe-based subprocess.run would wait for that child as well.
        real_popen = subprocess.Popen
        def redirect_exec(_args, **kwargs):
            child = ('import subprocess,sys; '
                     'subprocess.Popen([sys.executable,"-c","import time; time.sleep(2)"],'
                     'stdout=sys.stdout,stderr=sys.stderr, start_new_session=True); '
                     'print("success")')
            return real_popen([sys.executable, '-c', child], **kwargs)
        with patch.object(apt_process.subprocess, 'Popen', side_effect=redirect_exec):
            started = time.monotonic()
            result = apt_process.elevated_apt(['pkexec', '/usr/bin/apt-get'])
            elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 0)
        self.assertIn('success', result.stdout)
        self.assertLess(elapsed, 1.2)

    def test_removal_still_requires_simulated_plan(self):
        with patch.object(apt_remove, 'simulate', side_effect=RuntimeError('Plan falsch')):
            with patch.object(apt_process, 'elevated_apt') as elevated:
                with self.assertRaisesRegex(RuntimeError, 'Plan falsch'):
                    apt_remove.remove(['vlc'])
                elevated.assert_not_called()


if __name__ == '__main__':
    unittest.main()

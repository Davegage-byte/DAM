"""Removal protection tests. No real packages changed."""
import unittest
from unittest.mock import Mock, patch
import apt_remove


class RemoveTests(unittest.TestCase):
    def test_allowlisted(self):
        apt_remove.validate_packages(['vlc', 'rustdesk'])
        for names in ([], ['bash'], ['libreoffice'], ['vlc', 'vlc'],
                      ['vlc;rm -rf /'], ['vlc', 'coreutils']):
            with self.subTest(names=names), self.assertRaises(RuntimeError):
                apt_remove.validate_packages(names)

    def test_plan_exact(self):
        with patch.object(apt_remove, 'installed_version', return_value='3.0'):
            with patch.object(apt_remove, 'run', return_value=Mock(
                returncode=0, stdout='Reading package lists...\nRemv vlc [3.0]\n')) as run:
                self.assertEqual(apt_remove.simulate(['vlc']), {'vlc'})
                args = run.call_args[0][0]
                self.assertEqual(args[:4], ['/usr/bin/apt-get', '-s', 'remove', '--'])
                self.assertEqual(args[-1], 'vlc')

    def test_extra_removals_blocked(self):
        with patch.object(apt_remove, 'installed_version', return_value='1'):
            with patch.object(apt_remove, 'run', return_value=Mock(
                    returncode=0, stdout='Remv vlc [3.0]\nRemv other [1.0]\n')):
                with self.assertRaisesRegex(RuntimeError, 'weitere Pakete'):
                    apt_remove.simulate(['vlc'])

    def test_side_effects_blocked(self):
        with patch.object(apt_remove, 'installed_version', return_value='1'):
            for extra in ['Inst other [1]', 'Conf other (1)', 'Purg other [1]']:
                with self.subTest(extra=extra), patch.object(apt_remove, 'run', return_value=Mock(
                        returncode=0, stdout='Remv vlc [3.0]\n' + extra + '\n')):
                    with self.assertRaisesRegex(RuntimeError, 'zusätzliche'):
                        apt_remove.simulate(['vlc'])

    def test_missing_or_absent_not_removed(self):
        with patch.object(apt_remove, 'installed_version', return_value=None):
            with patch.object(apt_remove, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'nicht als DEB'):
                    apt_remove.simulate(['vlc'])
                run.assert_not_called()

    def test_missing_package_from_simulation_blocked(self):
        with patch.object(apt_remove, 'installed_version', return_value='1'):
            with patch.object(apt_remove, 'run', return_value=Mock(returncode=0, stdout='0 to remove')):
                with self.assertRaisesRegex(RuntimeError, 'nicht genau'):
                    apt_remove.simulate(['vlc'])

    def test_simulation_failure_prevents_elevation(self):
        with patch.object(apt_remove, 'simulate', side_effect=RuntimeError('unsafe')):
            with patch.object(apt_remove.apt_process, 'elevated_apt') as run:
                with self.assertRaisesRegex(RuntimeError, 'unsafe'):
                    apt_remove.remove(['vlc'])
                run.assert_not_called()

    def test_remove_command_and_verification(self):
        with patch.object(apt_remove, 'simulate', return_value={'vlc'}):
            with patch.object(apt_remove, 'installed_version', return_value=None):
                with patch.object(apt_remove.apt_process, 'elevated_apt', return_value=Mock(returncode=0, stdout='')) as run:
                    self.assertEqual(apt_remove.remove(['vlc']), ['vlc'])
                    self.assertEqual(run.call_args[0][0],
                                     ['pkexec', '/usr/bin/apt-get', 'remove', '-y', '--', 'vlc'])

    def test_remove_not_reported_success_if_still_installed(self):
        with patch.object(apt_remove, 'simulate', return_value={'vlc'}):
            with patch.object(apt_remove, 'installed_version', return_value='3.0'):
                with patch.object(apt_remove.apt_process, 'elevated_apt', return_value=Mock(returncode=0, stdout='')):
                    with self.assertRaisesRegex(RuntimeError, 'Noch installiert'):
                        apt_remove.remove(['vlc'])

    def test_installed_version_handles_removed_package_without_version(self):
        # Real user log: dpkg-query prints a status followed by an empty
        # version field; stripping whitespace before splitting raised ValueError.
        for output in ('not-installed\t', 'not-installed\t\n', 'config-files\t',
                       'unknown\t', '', 'un\n', 'not-installed'):
            with self.subTest(output=output):
                with patch.object(apt_remove, 'run', return_value=Mock(returncode=0, stdout=output)):
                    self.assertIsNone(apt_remove.installed_version('vlc'))

    def test_installed_version_keeps_valid_tab_separator(self):
        with patch.object(apt_remove, 'run', return_value=Mock(
                returncode=0, stdout='installed\t3.0.23-1\n')):
            self.assertEqual(apt_remove.installed_version('vlc'), '3.0.23-1')

    def test_post_remove_verification_handles_empty_version(self):
        with patch.object(apt_remove, 'simulate', return_value={'vlc'}):
            with patch.object(apt_remove.apt_process, 'elevated_apt',
                              return_value=Mock(returncode=0, stdout='')):
                with patch.object(apt_remove, 'run', return_value=Mock(
                        returncode=0, stdout='not-installed\t')):
                    self.assertEqual(apt_remove.remove(['vlc']), ['vlc'])

    def test_authentication_aborted(self):
        with patch.object(apt_remove, 'simulate', return_value={'vlc'}):
            with patch.object(apt_remove.apt_process, 'elevated_apt', return_value=Mock(returncode=126, stderr='Authentication failed')):
                with self.assertRaisesRegex(RuntimeError, 'abgebrochen'):
                    apt_remove.remove(['vlc'])


if __name__ == '__main__':
    unittest.main()

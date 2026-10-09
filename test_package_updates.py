import unittest
from unittest.mock import patch
import subprocess
import package_updates as m


class UpdateDetectionTests(unittest.TestCase):
    def test_apt_parsing_only_available_packages(self):
        output = ('Listing...\nfirefox/noble-updates 3.0 amd64 [upgradable from: 2.0]\n'
                  'libc6/noble-updates 9.1 amd64 [upgradable from: 8.1]\n')
        records = m.parse_apt_list(output)
        self.assertEqual(records[0], m.UpdateRecord('apt','firefox','2.0','3.0'))
        self.assertEqual(len(records), 2)

    def test_snap_parsing_with_name_and_revision(self):
        records = m.parse_snap_refresh('Name Version Rev Publisher Notes\nfirefox 150 123 mozilla -\n', {'firefox': '149'})
        self.assertEqual(records[0].available, '150')
        self.assertEqual(records[0].installed, '149')

    def test_flatpak_parsing_scopes_and_ids(self):
        installed = m.parse_flatpak_list('org.gimp.GIMP\tGIMP\t3.0.0\n')
        records = m.parse_flatpak_updates('org.gimp.GIMP\t3.0.1\n', 'user', installed)
        self.assertEqual(records[0].scope, 'user')
        self.assertEqual(records[0].identifier, 'org.gimp.GIMP')

    def test_only_desktop_apps_eligible(self):
        apps = [{'name':'Firefox', 'package':'firefox', 'desktop_id':'firefox.desktop'},
                {'name':'GIMP', 'package':None, 'desktop_id':'org.gimp.GIMP.desktop'}]
        records = [m.UpdateRecord('apt','firefox','1','2'),
                   m.UpdateRecord('apt','libc6','1','2'),
                   m.UpdateRecord('flatpak','org.gimp.GIMP','1','2','user','GIMP')]
        mapped = m.updates_for_apps(records, apps)
        self.assertEqual(set(mapped), {'firefox','gimp'})
        self.assertNotIn('libc6', mapped)

    def test_no_prefix_package_matching(self):
        item={'name':'Firefox', 'package':'firefox', 'desktop_id':'firefox.desktop'}
        self.assertFalse(m.record_matches_app(m.UpdateRecord('apt','firefox-esr','1','2'), item))

    @patch.object(m, 'run')
    def test_reject_apt_removals(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='Remv ubuntu-desktop [1]\n')
        with self.assertRaisesRegex(RuntimeError, 'entfernen'):
            m.do_update(m.UpdateRecord('apt','firefox','1','2'))
        mock_run.assert_called_once()

    @patch.object(m, 'run')
    def test_apt_updates_use_pkexec_for_exact_package(self, mock_run):
        mock_run.side_effect = [subprocess.CompletedProcess([], 0, stdout='Inst firefox [1] (2)\n'),
                                subprocess.CompletedProcess([], 0, stdout='OK')]
        self.assertTrue(m.do_update(m.UpdateRecord('apt','firefox','1','2')))
        self.assertEqual(mock_run.call_args_list[-1].args[0][-2:], ['--','firefox'])
        self.assertEqual(mock_run.call_args_list[-1].args[0][0], 'pkexec')

    def test_reject_malicious_package_name(self):
        with self.assertRaisesRegex(RuntimeError, 'Ungültiger Paketname'):
            m.do_update(m.UpdateRecord('apt','firefox; rm -rf /','1','2'))

    @patch.object(m, 'run')
    @patch.object(m.shutil, 'which', return_value='/usr/bin/flatpak')
    def test_user_flatpak_does_not_use_pkexec(self, mock_which, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout='OK')
        self.assertTrue(m.do_update(m.UpdateRecord('flatpak','org.gimp.GIMP','1','2','user')))
        self.assertEqual(mock_run.call_args.args[0][0], '/usr/bin/flatpak')

if __name__ == '__main__':
    unittest.main()

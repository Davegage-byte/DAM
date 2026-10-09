"""Offline update security and rollback regression tests."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import dam_updater as updater


class ReleaseParsingTests(unittest.TestCase):
    def release(self, version='0.6.1', digest=None, url=None):
        name = f'DAM-v{version}.zip'
        return {
            'tag_name': 'v' + version, 'draft': False, 'prerelease': False,
            'assets': [{'name': name, 'size': 700,
                        'digest': digest or 'sha256:' + 'a' * 64,
                        'browser_download_url': url or
                        f'https://github.com/Davegage-byte/DAM/releases/download/v{version}/{name}'}]}

    def test_valid_version(self):
        release = updater._release_from_json(self.release(), '0.6.0')
        self.assertEqual(release.version, '0.6.1')
        self.assertEqual(release.sha256, 'a' * 64)

    def test_older_and_equal_ignored(self):
        self.assertIsNone(updater._release_from_json(self.release(), '0.6.1'))
        self.assertIsNone(updater._release_from_json(self.release('0.5.25'), '0.6.0'))

    def test_prerelease_ignored(self):
        x = self.release()
        x['prerelease'] = True
        self.assertIsNone(updater._release_from_json(x, '0.6.0'))

    def test_missing_digest_refused(self):
        x = self.release()
        x['assets'][0]['digest'] = None
        with self.assertRaises(updater.UpdateError):
            updater._release_from_json(x, '0.6.0')

    def test_third_party_url_refused(self):
        x = self.release(url='https://evil.example.org/file.zip')
        with self.assertRaises(updater.UpdateError):
            updater._release_from_json(x, '0.6.0')

    def test_arbitrary_github_path_refused(self):
        x = self.release(url='https://github.com/hacker/DAM/releases/download/v0.6.1/DAM-v0.6.1.zip')
        with self.assertRaises(updater.UpdateError):
            updater._release_from_json(x, '0.6.0')

    def test_no_release_yet(self):
        from urllib.error import HTTPError
        with patch.object(updater, '_read_url', side_effect=HTTPError(updater.API_URL, 404, 'not found', {}, None)):
            self.assertIsNone(updater.check_latest('0.6.0'))

    def test_network_error_displays_explanation(self):
        import urllib.error
        with patch.object(updater, '_read_url', side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(updater.UpdateError):
                updater.check_latest('0.6.0')


class ArchiveTests(unittest.TestCase):
    def make_package(self, overrides=None, extra=None):
        data = {'version.json': b'{"schema":1,"version":"0.6.1"}',
                'dam.png': b'\x89PNG\r\n\x1a\n' + b'pngdata'}
        for name in updater.APP_FILES:
            if name.endswith('.py'):
                data[name] = b'print("start")\n'
        if overrides:
            data.update(overrides)
        if extra:
            data.update(extra)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, contents in data.items():
                archive.writestr(name, contents)
        return output.getvalue()

    def test_good_archive(self):
        with tempfile.TemporaryDirectory() as base:
            updater._safe_archive(self.make_package(), '0.6.1', Path(base))
            self.assertEqual((Path(base) / 'version.json').read_text(), '{"schema":1,"version":"0.6.1"}')

    def test_traversal_refused(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(updater.UpdateError):
                updater._safe_archive(self.make_package(extra={'../malware.py': b'x'}), '0.6.1', Path(base))

    def test_unknown_file_refused(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(updater.UpdateError):
                updater._safe_archive(self.make_package(extra={'install.sh': b'echo hacked'}), '0.6.1', Path(base))

    def test_mismatched_manifest_refused(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(updater.UpdateError):
                updater._safe_archive(self.make_package({'version.json': b'{"schema":1,"version":"0.7.0"}'}), '0.6.1', Path(base))

    def test_invalid_python_refused(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(updater.UpdateError):
                updater._safe_archive(self.make_package({'dam.py': b'def :' }), '0.6.1', Path(base))

    def test_symlink_refused(self):
        content = io.BytesIO()
        data = {name: b'print("works")\n' for name in updater.APP_FILES}
        data['version.json'] = b'{"schema":1,"version":"0.6.1"}'
        data['dam.png'] = b'\x89PNG\r\n\x1a\nxxx'
        with zipfile.ZipFile(content, 'w') as archive:
            for name, payload in data.items():
                info = zipfile.ZipInfo(name)
                if name == 'dam.py':
                    info.create_system = 3
                    info.external_attr = (0o120777 << 16)
                archive.writestr(info, payload)
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(updater.UpdateError):
                updater._safe_archive(content.getvalue(), '0.6.1', Path(base))

    def test_checksum_rejected_without_current_change(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base) / '.local' / 'share' / 'dam'
            (root / 'versions' / '0.6.0').mkdir(parents=True)
            (root / 'current').symlink_to('versions/0.6.0')
            archive = self.make_package()
            release = updater.Release('0.6.1', 'https://github.com/Davegage-byte/DAM/releases/download/v0.6.1/DAM-v0.6.1.zip', '0' * 64)
            with patch.object(Path, 'home', return_value=Path(base)):
                with patch.object(updater, '_read_url', return_value=archive):
                    with self.assertRaises(updater.UpdateError):
                        updater.stage(release)
            self.assertEqual(updater._current_version(root), '0.6.0')
            self.assertFalse((root / 'versions' / '0.6.1').exists())

    def test_stage_atomic(self):
        with tempfile.TemporaryDirectory() as base:
            archive = self.make_package()
            release = updater.Release('0.6.1', 'https://github.com/Davegage-byte/DAM/releases/download/v0.6.1/DAM-v0.6.1.zip', hashlib.sha256(archive).hexdigest())
            with patch.object(Path, 'home', return_value=Path(base)):
                with patch.object(updater, '_read_url', return_value=archive):
                    staged = updater.stage(release)
            self.assertTrue((staged / 'dam_updater.py').exists())
            self.assertTrue((staged / 'dam.py').exists())
            self.assertFalse(any(staged.parent.glob('.staging-*')))


class ActivationTests(unittest.TestCase):
    def test_symlink_switch_and_rollback_on_failed_launch(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base) / '.local' / 'share' / 'dam'
            versions = root / 'versions'
            (versions / '0.6.0').mkdir(parents=True)
            (versions / '0.6.1').mkdir(parents=True)
            (root / 'current').symlink_to('versions/0.6.0')
            with patch.object(Path, 'home', return_value=Path(base)):
                with patch.object(updater, '_wait_for_pid'):
                    with patch.object(updater, '_launch_and_wait', side_effect=updater.UpdateError('Crash')):
                        with patch.object(updater.subprocess, 'Popen'):
                            with self.assertRaises(updater.UpdateError):
                                updater.activate(123456, '0.6.1')
            self.assertEqual(updater._current_version(root), '0.6.0')
            failure = json.loads((Path(base) / '.local' / 'state' / 'dam' / 'updater-error.json').read_text())
            self.assertIn('Crash', failure['error'])

    def test_previous_version_remembered_on_success(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base) / '.local' / 'share' / 'dam'
            versions = root / 'versions'
            (versions / '0.6.0').mkdir(parents=True)
            (versions / '0.6.1').mkdir(parents=True)
            (root / 'current').symlink_to('versions/0.6.0')
            with patch.object(Path, 'home', return_value=Path(base)):
                with patch.object(updater, '_wait_for_pid'):
                    with patch.object(updater, '_launch_and_wait'):
                        updater.activate(123456, '0.6.1')
            self.assertEqual(updater._current_version(root), '0.6.1')
            self.assertEqual((Path(base) / '.local' / 'state' / 'dam' / 'previous-version.txt').read_text().strip(), '0.6.0')


if __name__ == '__main__':
    unittest.main()

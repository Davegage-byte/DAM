"""Prevent releasing a DAM asset with mismatched version or file layout."""
import ast
import json
from pathlib import Path
import unittest

import build_release
import dam_updater

ROOT = Path(__file__).resolve().parent


class ReleaseConsistencyTests(unittest.TestCase):
    def test_version_matches_application(self):
        manifest = json.loads((ROOT / 'version.json').read_text('utf-8'))
        tree = ast.parse((ROOT / 'dam.py').read_text('utf-8'))
        versions = [node.value.value for node in tree.body
                    if isinstance(node, ast.Assign)
                    for target in node.targets
                    if isinstance(target, ast.Name) and target.id == 'VERSION'
                    and isinstance(node.value, ast.Constant)]
        self.assertEqual(versions, [manifest['version']])
        self.assertEqual(manifest['schema'], 1)
        dam_updater.version_tuple(manifest['version'])

    def test_release_file_list_matches_updater(self):
        self.assertEqual(set(build_release.FILES), set(dam_updater.APP_FILES))
        self.assertEqual(len(build_release.FILES), len(set(build_release.FILES)))
        for name in build_release.FILES:
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == '__main__':
    unittest.main()

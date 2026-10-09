#!/usr/bin/env python3
"""Create a strict, reproducible, self-updater-compatible DAM release asset.

Release assets are **not** the GitHub-generated source ZIP. Package the exact
files allowed by the self-updater, and upload as DAM-v<version>.zip.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import zipfile

FILES = (
    'dam.py', 'dam_updater.py', 'package_updates.py', 'rustdesk_update.py',
    'app_shortcuts.py', 'apt_install.py', 'apt_remove.py', 'apt_process.py',
    'dam.png', 'version.json',
)


def build(directory, output_dir, tag=None):
    manifest = json.loads((directory / 'version.json').read_text('utf-8'))
    if manifest.get('schema') != 1 or not isinstance(manifest.get('version'), str):
        raise ValueError('Release-Manifest ungültig')
    version = manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Release-Version ungültig')
    if tag is not None and tag != 'v' + version:
        raise ValueError('Release-Tag muss zur Version passen')
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f'DAM-v{version}.zip'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for filename in FILES:
            content = (directory / filename).read_bytes()
            if filename.endswith('.py'):
                compile(content, filename, 'exec')
            entry = zipfile.ZipInfo(filename, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = (0o100644 << 16)
            archive.writestr(entry, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(f'Asset: {destination} | SHA256: {checksum}')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='dist')
    parser.add_argument('--tag')
    args = parser.parse_args()
    build(Path(__file__).resolve().parent, Path(args.output).resolve(), args.tag)

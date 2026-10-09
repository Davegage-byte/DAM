"""DAM: kontrollierte Aktualisierung offizieller RustDesk-DEB-Pakete."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass

API = 'https://api.github.com/repos/rustdesk/rustdesk/releases/latest'
RELEASE_PREFIX = 'https://github.com/rustdesk/rustdesk/releases/download/'
MAX_BYTES = 200 * 1024 * 1024


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    name: str
    url: str
    sha256: str
    size: int


def installed_version():
    proc = subprocess.run(
        ['dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}', 'rustdesk'],
        capture_output=True, text=True, timeout=10)
    if proc.returncode != 0 or '\t' not in proc.stdout:
        return None
    status, version = proc.stdout.strip().split('\t', 1)
    return version.strip() if status.strip() == 'installed' else None


def is_newer(installed, available):
    if not installed:
        raise UpdateError('RustDesk ist nicht als DEB-Paket installiert.')
    return subprocess.run(
        ['dpkg', '--compare-versions', installed, 'lt', available],
        timeout=5, check=False).returncode == 0


def fetch_latest():
    request = urllib.request.Request(API, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'DAM-Ubuntu-App-Manager',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
    except (OSError, ValueError) as exc:
        raise UpdateError(f'GitHub konnte nicht abgefragt werden: {exc}') from exc
    if data.get('prerelease') or data.get('draft'):
        raise UpdateError('GitHub liefert keine stabile Veröffentlichung.')
    version = str(data.get('tag_name', '')).removeprefix('v')
    if not re.fullmatch(r'[0-9][0-9A-Za-z.+:~\-]*', version):
        raise UpdateError('Die Versionsnummer von GitHub ist ungültig.')
    matches = []
    for asset in data.get('assets', []):
        name = asset.get('name', '')
        url = asset.get('browser_download_url', '')
        if not re.fullmatch(r'rustdesk-[0-9][0-9A-Za-z.+~\-]*-(?:x86_64|amd64)\.deb', name):
            continue
        if not url.startswith(RELEASE_PREFIX) or not url.endswith('/' + name):
            continue
        size = int(asset.get('size', 0))
        if size <= 0 or size > MAX_BYTES:
            continue
        digest = asset.get('digest') or ''
        # Keine Installation ohne Prüfsumme aus der offiziellen GitHub-Release-API.
        if not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
            continue
        matches.append(Release(version, name, url, digest[7:].lower(), size))
    if len(matches) != 1:
        raise UpdateError('Kein eindeutiges, prüfbares AMD64-DEB-Paket auf GitHub gefunden.')
    return matches[0]


def download_checked(release, destination, progress=lambda count, total: None):
    """Download in ein temporäres Verzeichnis; verifiziere SHA-256 und Paketmetadata."""
    request = urllib.request.Request(release.url, headers={
        'User-Agent': 'DAM-Ubuntu-App-Manager',
    })
    digest = hashlib.sha256()
    count = 0
    try:
        with urllib.request.urlopen(request, timeout=35) as response, open(destination, 'wb') as stream:
            # Die endgültige Downloadadresse darf nur von GitHub/GitHub-Assets stammen.
            final_url = response.geturl()
            from urllib.parse import urlparse
            hostname = urlparse(final_url).hostname or ''
            if hostname not in ('github.com', 'release-assets.githubusercontent.com',
                                'objects.githubusercontent.com'):
                raise UpdateError('Der Download wurde an eine fremde Domain umgeleitet.')
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                count += len(block)
                if count > MAX_BYTES or count > release.size:
                    raise UpdateError('Die Datei ist größer als laut GitHub erwartet.')
                digest.update(block)
                stream.write(block)
                progress(count, release.size)
    except (OSError, ValueError) as exc:
        raise UpdateError(f'Download fehlgeschlagen: {exc}') from exc
    if count != release.size or digest.hexdigest() != release.sha256:
        raise UpdateError('Die SHA-256-Prüfung oder Dateigröße stimmt nicht überein.')
    # dpkg-deb -f with *multiple* fields prints labeled lines such as
    # "Package: rustdesk", not plain values. Request each field separately.
    # This avoids the DAM v0.2.0 false rejection of valid DEB packages.
    metadata = {}
    for field in ('Package', 'Version', 'Architecture'):
        try:
            proc = subprocess.run(
                ['dpkg-deb', '-f', str(destination), field],
                capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f'DEB-Metadaten konnten nicht gelesen werden: {exc}') from exc
        if proc.returncode != 0:
            raise UpdateError('Die heruntergeladene Datei ist kein gültiges DEB-Paket.')
        metadata[field] = proc.stdout.strip()

    if metadata['Package'] != 'rustdesk' or metadata['Architecture'] != 'amd64':
        raise UpdateError('Paketname oder Architektur passen nicht zu RustDesk/AMD64.')
    if metadata['Version'] != release.version:
        raise UpdateError('Die Paketversion stimmt nicht mit der GitHub-Version überein.')
    return destination


def install(release, status=lambda msg: None):
    """Wird ausschließlich nach bewusster Bestätigung im GUI aufgerufen."""
    current = installed_version()
    if not is_newer(current, release.version):
        raise UpdateError('Es ist keine neuere RustDesk-Version vorhanden.')
    with tempfile.TemporaryDirectory(prefix='dam-rustdesk-') as directory:
        target = Path(directory) / release.name
        status('RustDesk wird heruntergeladen …')
        download_checked(release, target)
        status('Paket geprüft. Installationsplan wird kontrolliert …')
        plan = subprocess.run(
            ['apt-get', '-s', 'install', str(target)],
            capture_output=True, text=True, timeout=45)
        if plan.returncode != 0:
            raise UpdateError('APT-Vorabprüfung fehlgeschlagen:\n' + plan.stderr[-900:])
        if any(line.startswith(('Remv ', 'Purg ')) for line in plan.stdout.splitlines()):
            raise UpdateError('APT würde Pakete entfernen. Das Update wurde aus Sicherheitsgründen gestoppt.')
        status('Administratorfreigabe wird angefordert …')
        proc = subprocess.run(
            ['pkexec', '/usr/bin/apt-get', 'install', '-y', str(target)],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise UpdateError('Installation fehlgeschlagen oder abgebrochen:\n'
                              + (proc.stderr or proc.stdout)[-900:])
    installed = installed_version()
    if not installed or is_newer(installed, release.version):
        raise UpdateError('Die installierte Version konnte nach dem Update nicht bestätigt werden.')
    return installed

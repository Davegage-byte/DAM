"""Vorsichtige APT-Installation einer kleinen, festen Auswahl regulärer Desktop-Apps."""
import os
import re
import subprocess

import apt_process

# Firefox/Thunderbird sind je nach Ubuntu-System Snap-Übergangspakete;
# RustDesk wird bewusst separat durch die geprüfte GitHub-Integration verwaltet.
ALLOWED = frozenset({'vlc', 'gimp', 'krita', 'kdenlive', 'obs-studio', 'libreoffice'})
VERSION_RE = re.compile(r'^\s*Candidate:\s*(\S+)\s*$', re.M)


def run(args, timeout=35):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, 'LC_ALL': 'C'})


def candidate(name):
    if name not in ALLOWED:
        return None
    try:
        process = run(['/usr/bin/apt-cache', 'policy', name], 8)
    except (OSError, subprocess.SubprocessError):
        return None
    if process.returncode != 0:
        return None
    match = VERSION_RE.search(process.stdout)
    if match and match.group(1) != '(none)':
        return match.group(1)
    return None


def installed_version(name):
    if name not in ALLOWED:
        return None
    try:
        proc = run(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}', name], 8)
        if proc.returncode == 0 and '\t' in proc.stdout:
            status, version = proc.stdout.strip().split('\t', 1)
            if status == 'installed':
                return version
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def validate_packages(packages):
    if not packages or len(packages) > len(ALLOWED):
        raise RuntimeError('Keine gültigen Programme ausgewählt.')
    if len(set(packages)) != len(packages) or any(name not in ALLOWED for name in packages):
        raise RuntimeError('Nicht freigegebener oder doppelter Paketname.')


def simulate(packages):
    validate_packages(packages)
    for name in packages:
        if installed_version(name):
            raise RuntimeError(f'{name} ist bereits installiert.')
        if not candidate(name):
            raise RuntimeError(f'Für {name} ist keine APT-Paketquelle vorhanden.')
    proc = run(['/usr/bin/apt-get', '-s', '--no-remove', 'install', '--', *packages], 90)
    if proc.returncode != 0:
        raise RuntimeError('APT-Vorabprüfung fehlgeschlagen: ' + (proc.stderr or proc.stdout)[-350:])
    if any(line.startswith(('Remv ', 'Purg ')) for line in proc.stdout.splitlines()):
        raise RuntimeError('APT würde Pakete entfernen; Vorgang wird abgebrochen.')
    return proc.stdout


def install(packages, report=lambda message: None):
    validate_packages(packages)
    report('APT-Installationsplan wird geprüft …')
    simulate(packages)
    report('Administratorfreigabe / APT-Installation läuft …')
    proc = apt_process.elevated_apt(['pkexec', '/usr/bin/apt-get', '--no-remove', 'install', '-y', '--', *packages], 1800)
    if proc.returncode != 0:
        raise RuntimeError('Installation abgebrochen: ' + (proc.stderr or proc.stdout)[-350:])
    versions = {name: installed_version(name) for name in packages}
    if any(not version for version in versions.values()):
        raise RuntimeError('Die Installation konnte nicht für alle Pakete bestätigt werden.')
    return versions

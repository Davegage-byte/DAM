"""DAM: cautious APT removal of a small, explicitly approved set of desktop apps.

The user chooses exact package names and confirms a simulated removal plan.
Never purge settings, never autoremove, never remove additional dependencies.
"""
import os
import re
import subprocess

import apt_process

# Do NOT add meta packages (e.g. libreoffice) or core Ubuntu components here.
# RustDesk is deliberately included as an optionally removable direct DEB package.
ALLOWED = frozenset({'vlc', 'gimp', 'krita', 'kdenlive', 'obs-studio', 'rustdesk'})
REMOVAL = re.compile(r'^Remv\s+([^\s\[]+)(?:\s|$)')
SIDE_EFFECT = re.compile(r'^(?:Purg|Inst|Conf)\s+')


def run(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, 'LC_ALL': 'C'})


def validate_packages(packages):
    if not isinstance(packages, (list, tuple)) or not packages or len(packages) > len(ALLOWED):
        raise RuntimeError('Keine gültigen Programme ausgewählt.')
    if any(not isinstance(name, str) or name not in ALLOWED for name in packages):
        raise RuntimeError('Dieses Paket ist nicht zur Deinstallation freigegeben.')
    if len(set(packages)) != len(packages):
        raise RuntimeError('Ein Programm wurde mehrfach ausgewählt.')


def installed_version(package):
    if package not in ALLOWED:
        return None
    try:
        proc = run(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}', package], 10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'Paketstatus konnte nicht geprüft werden: {exc}') from exc
    if proc.returncode != 0 or not proc.stdout:
        return None
    # Do not use .strip() before splitting: after removal dpkg-query can
    # return `not-installed\t` with an empty version. strip() discards that
    # trailing tab and previously raised ValueError after successful removal.
    line = proc.stdout.splitlines()[0]
    status, separator, version = line.partition('\t')
    if not separator or status.strip() != 'installed':
        return None
    return version.strip() or None


def parse_removals(output):
    """Reject plans we cannot parse reliably, including upgrades or dependency removal."""
    removes = set()
    for line in output.splitlines():
        if SIDE_EFFECT.match(line):
            raise RuntimeError('APT plant zusätzliche Paketänderungen. Deinstallation abgebrochen.')
        match = REMOVAL.match(line)
        if match:
            package = match.group(1).split(':')[0]
            if package in removes:
                raise RuntimeError('Der APT-Plan enthält doppelte Paketentfernungen.')
            removes.add(package)
    return removes


def simulate(packages):
    validate_packages(packages)
    for package in packages:
        if not installed_version(package):
            raise RuntimeError(f'{package} ist nicht als DEB-Paket installiert.')
    try:
        proc = run(['/usr/bin/apt-get', '-s', 'remove', '--', *packages], 90)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'APT-Vorabprüfung nicht möglich: {exc}') from exc
    if proc.returncode != 0:
        raise RuntimeError('APT-Vorabprüfung fehlgeschlagen: ' + (proc.stderr or proc.stdout)[-350:])
    planned = parse_removals(proc.stdout)
    if planned != set(packages):
        extras = sorted(planned - set(packages))
        if extras:
            raise RuntimeError('APT würde weitere Pakete entfernen: ' + ', '.join(extras))
        raise RuntimeError('Der APT-Plan entfernt nicht genau die ausgewählten Programme.')
    return planned


def remove(packages, report=lambda message: None):
    """Only run after UI confirmation; recheck the plan directly before elevation."""
    validate_packages(packages)
    report('Entfernungsplan wird erneut geprüft …')
    simulate(packages)
    report('Administratorfreigabe / APT-Deinstallation läuft …')
    try:
        proc = apt_process.elevated_apt(['pkexec', '/usr/bin/apt-get', 'remove', '-y', '--', *packages], 1800)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'Deinstallation konnte nicht gestartet werden: {exc}') from exc
    if proc.returncode != 0:
        raise RuntimeError('Deinstallation abgebrochen oder fehlgeschlagen: ' + (proc.stderr or proc.stdout)[-400:])
    still_installed = [p for p in packages if installed_version(p)]
    if still_installed:
        raise RuntimeError('Noch installiert: ' + ', '.join(still_installed))
    return list(packages)

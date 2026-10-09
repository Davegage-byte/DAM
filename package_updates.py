"""Nur tatsächlich gemeldete Anwendungs-Updates via APT/Snap/Flatpak.

Kein Paket wird durch die Prüfung installiert oder entfernt.
APT berücksichtigt die lokal vorhandenen Paketlisten. Die App-Filterung
findet in dam.py anhand realer Ubuntu-Anwendungsstarter statt.
"""
from dataclasses import dataclass
import os
import re
import shutil
import subprocess
import time
import signal


@dataclass(frozen=True)
class UpdateRecord:
    source: str           # apt / snap / flatpak
    identifier: str       # tatsächlicher Paketname bzw. Flatpak-App-ID
    installed: str
    available: str
    scope: str = ''        # Flatpak: user oder system
    display_name: str = ''


PACKAGE_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9+_.:@-]*$')
FLATPAK_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')


class UpdateScanCancelled(Exception):
    """Eine nur lesende Paketquellenprüfung wurde mit Esc beendet."""


def run(args, timeout, cancel_event=None):
    """Nur Scan-Befehle sind abbrechbar; Update-Installationen bleiben atomar.

    Bei cancel_event werden ausschließlich schreibfreie Paketlisten-Abfragen
    gestartet. Ein Abbruch beendet ihre eigene Prozessgruppe; keine APT/dpkg
    Installation oder Systemwartung wird hier angehalten.
    """
    env = {**os.environ, 'LC_ALL': 'C'}
    if cancel_event is None:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              env=env)
    if cancel_event.is_set():
        raise UpdateScanCancelled()
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, start_new_session=True)
    started = time.monotonic()
    try:
        while True:
            if cancel_event.is_set():
                raise UpdateScanCancelled()
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                stdout, stderr = proc.communicate(timeout=min(0.2, remaining))
                return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    except (UpdateScanCancelled, subprocess.TimeoutExpired):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            proc.communicate(timeout=1.5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
        raise


def parse_apt_list(output):
    found = []
    pattern = re.compile(r'^([^/\s]+)/\S+\s+(\S+)\s+\S+\s+\[upgradable from:\s*([^\]]+)\]', re.I)
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match and PACKAGE_RE.fullmatch(match[1]):
            found.append(UpdateRecord('apt', match[1], match[3].strip(), match[2].strip()))
    return found


def parse_snap_refresh(output, installed_versions=None):
    installed_versions = installed_versions or {}
    found = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[0].casefold() in ('name', 'no'):
            continue
        if not PACKAGE_RE.fullmatch(fields[0]):
            continue
        # snap refresh --list listet lediglich Updates; die Revision kann sich
        # bei gleichem sichtbaren Versionsstring geändert haben.
        found.append(UpdateRecord('snap', fields[0], installed_versions.get(fields[0], '–'), fields[1]))
    return found


def parse_snap_list(output):
    found = {}
    for line in output.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and PACKAGE_RE.fullmatch(fields[0]):
            found[fields[0]] = fields[1]
    return found


def parse_flatpak_list(output):
    # flatpak --user/--system list --app --columns=application,name,version
    installed = {}
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) >= 3 and FLATPAK_RE.fullmatch(fields[0]):
            installed[fields[0]] = (fields[1], fields[2])
    return installed


def parse_flatpak_updates(output, scope, installed):
    found = []
    # --columns=application,version (kein Header)
    for line in output.splitlines():
        fields = line.split('\t')
        if len(fields) < 2 or not FLATPAK_RE.fullmatch(fields[0]):
            continue
        app_id, version = fields[:2]
        if app_id not in installed:
            continue
        display_name, old = installed[app_id]
        found.append(UpdateRecord('flatpak', app_id, old or '–', version or '–', scope, display_name))
    return found


def probe_updates(cancel_event=None):
    """Updates und verständliche Prüffehler zurückgeben, niemals Pakete ändern."""
    found = []
    errors = []
    checked = 0
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateScanCancelled()
    if shutil.which('apt'):
        try:
            process = run(['apt', 'list', '--upgradable'], 25, cancel_event=cancel_event)
            if process.returncode == 0:
                found.extend(parse_apt_list(process.stdout))
                checked += 1
            else:
                errors.append('APT konnte nicht geprüft werden')
        except (OSError, subprocess.SubprocessError):
            errors.append('APT-Prüfung fehlgeschlagen')
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateScanCancelled()
    if shutil.which('snap'):
        try:
            current = run(['snap', 'list'], 20, cancel_event=cancel_event)
            available = run(['snap', 'refresh', '--list'], 45, cancel_event=cancel_event)
            if available.returncode == 0:
                installed = parse_snap_list(current.stdout) if current.returncode == 0 else {}
                found.extend(parse_snap_refresh(available.stdout, installed))
                checked += 1
            else:
                errors.append('Snap konnte nicht geprüft werden')
        except (OSError, subprocess.SubprocessError):
            errors.append('Snap-Prüfung fehlgeschlagen')
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateScanCancelled()
    if shutil.which('flatpak'):
        for scope in ('user', 'system'):
            if cancel_event is not None and cancel_event.is_set():
                raise UpdateScanCancelled()
            try:
                installed_proc = run(['flatpak', f'--{scope}', 'list', '--app',
                                      '--columns=application,name,version'], 20, cancel_event=cancel_event)
                available = run(['flatpak', f'--{scope}', 'remote-ls', '--updates', '--app',
                                 '--columns=application,version'], 45, cancel_event=cancel_event)
                if installed_proc.returncode == 0 and available.returncode == 0:
                    found.extend(parse_flatpak_updates(
                        available.stdout, scope, parse_flatpak_list(installed_proc.stdout)))
                    checked += 1
                elif installed_proc.returncode == 0 and installed_proc.stdout.strip():
                    errors.append(f'Flatpak ({scope}) konnte nicht geprüft werden')
            except (OSError, subprocess.SubprocessError):
                errors.append(f'Flatpak ({scope}) konnte nicht geprüft werden')
    return found, errors, checked


def record_matches_app(record, item):
    """Nur zu einem sichtbaren Desktop-Starter gehörende Updates anzeigen."""
    package = (item.get('package') or '').casefold()
    name = (item.get('name') or '').casefold()
    desktop = (item.get('desktop_id') or '').casefold().removesuffix('.desktop')
    ident = record.identifier.casefold()
    if record.source == 'apt':
        return bool(package) and ident == package
    if record.source == 'snap':
        return (ident == package or ident == name.replace(' ', '-') or
                desktop == ident or desktop.startswith(ident + '_'))
    if record.source == 'flatpak':
        return (desktop == ident or desktop.startswith(ident + '.') or
                (record.display_name and record.display_name.casefold() == name))
    return False


def updates_for_apps(records, apps):
    """Zuordnung ohne unscharfe Teilstringtreffer (gefährliche Fehlzuordnung)."""
    matched = {}
    for item in apps:
        matches = [record for record in records if record_matches_app(record, item)]
        if matches:
            # Falls gleiche App mehrfach installiert: genau eine Quelle bevorzugen.
            matched[item['name'].casefold()] = matches[0]
    return matched


def do_update(record):
    """Exakt ein angefragtes Anwendungsupdate durchführen. Keine Shell-Aufrufe."""
    if record.source not in ('apt', 'snap', 'flatpak'):
        raise RuntimeError('Unbekannte Updatequelle')
    if not PACKAGE_RE.fullmatch(record.identifier):
        raise RuntimeError('Ungültiger Paketname')
    if record.source == 'apt':
        simulate = run(['/usr/bin/apt-get', '-s', 'install', '--only-upgrade', '--', record.identifier], 45)
        if simulate.returncode != 0:
            raise RuntimeError('APT-Vorabprüfung fehlgeschlagen: ' + simulate.stderr[-300:])
        if any(line.startswith(('Remv ', 'Purg ')) for line in simulate.stdout.splitlines()):
            raise RuntimeError('APT würde Pakete entfernen; Update abgebrochen.')
        args = ['pkexec', '/usr/bin/apt-get', 'install', '--only-upgrade', '-y', '--', record.identifier]
    elif record.source == 'snap':
        binary = shutil.which('snap')
        if not binary:
            raise RuntimeError('Snap nicht gefunden')
        args = ['pkexec', os.path.realpath(binary), 'refresh', record.identifier]
    else:
        binary = shutil.which('flatpak')
        if not binary or not FLATPAK_RE.fullmatch(record.identifier):
            raise RuntimeError('Flatpak nicht verfügbar')
        base = [os.path.realpath(binary), f'--{record.scope}', 'update', '-y', '--noninteractive', '--app', record.identifier]
        if record.scope == 'user':
            args = base
        elif record.scope == 'system':
            args = ['pkexec', *base]
        else:
            raise RuntimeError('Ungültiger Flatpak-Installationsort')
    try:
        proc = run(args, 1200)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Zeitüberschreitung beim Aktualisieren') from exc
    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(output[-400:] or 'Aktualisierung abgebrochen')
    return True

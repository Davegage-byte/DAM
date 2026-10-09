"""DAM self-updates from authenticated GitHub HTTPS release metadata.

No root privileges. Downloads are treated as untrusted, checked before extraction,
then activated by a separate process after the main application quits.
"""
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPO = 'Davegage-byte/DAM'
API_URL = f'https://api.github.com/repos/{REPO}/releases/latest'
APP_FILES = frozenset(('dam.py', 'dam_updater.py', 'package_updates.py',
    'rustdesk_update.py', 'app_shortcuts.py', 'apt_install.py', 'apt_remove.py',
    'apt_process.py', 'dam.png', 'version.json'))
MAX_DOWNLOAD = 12 * 1024 * 1024
MAX_UNCOMPRESSED = 16 * 1024 * 1024
MAX_SINGLE_FILE = 8 * 1024 * 1024
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')
DIGEST_RE = re.compile(r'^sha256:([0-9a-f]{64})$')


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str
    notes: str = ''


class UpdateError(RuntimeError):
    pass


def data_dir():
    return Path.home() / '.local' / 'share' / 'dam'


def state_dir():
    return Path.home() / '.local' / 'state' / 'dam'


def version_tuple(value):
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise UpdateError('Ungültige DAM-Versionsnummer')
    return tuple(int(piece) for piece in value.split('.'))


def _read_url(url, limit, timeout=12):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'DAM-Updater/0.6', 'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(request, timeout=timeout) as stream:
        out = bytearray()
        while True:
            chunk = stream.read(min(65536, limit + 1 - len(out)))
            if not chunk:
                return bytes(out)
            out.extend(chunk)
            if len(out) > limit:
                raise UpdateError('Download überschreitet die erlaubte Größe')


def _release_from_json(info, current_version):
    if not isinstance(info, dict) or info.get('draft') or info.get('prerelease'):
        return None
    tag = info.get('tag_name')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise UpdateError('Ungültiger Release-Tag')
    version = tag[1:]
    if version_tuple(version) <= version_tuple(current_version):
        return None
    expected_name = f'DAM-v{version}.zip'
    for asset in info.get('assets', []):
        if not isinstance(asset, dict) or asset.get('name') != expected_name:
            continue
        url = asset.get('browser_download_url', '')
        parsed = urllib.parse.urlsplit(url)
        expected_prefix = f'/{REPO}/releases/download/v{version}/'
        if (parsed.scheme != 'https' or parsed.hostname != 'github.com'
                or not parsed.path.startswith(expected_prefix)
                or not parsed.path.endswith('/' + expected_name)
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise UpdateError('Release-Asset liegt nicht am erwarteten GitHub-Pfad')
        digest = asset.get('digest')
        match = DIGEST_RE.fullmatch(digest or '')
        if not match:
            raise UpdateError('Release hat keine gültige SHA-256-Prüfsumme')
        if not isinstance(asset.get('size'), int) or not 0 < asset['size'] <= MAX_DOWNLOAD:
            raise UpdateError('Ungültige Größe des Release-Assets')
        return Release(version, url, match[1], (info.get('body') or '')[:600])
    raise UpdateError('Offizielles DAM-Release-Paket fehlt')


def check_latest(current_version):
    """Return a newer stable DAM release or None (no release/no newer version)."""
    try:
        content = _read_url(API_URL, 1024 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # First release has not been published yet.
            return None
        raise UpdateError(f'GitHub nicht erreichbar (HTTP {exc.code})') from exc
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError('GitHub-Updateprüfung fehlgeschlagen') from exc
    try:
        metadata = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise UpdateError('Ungültige Release-Antwort') from exc
    return _release_from_json(metadata, current_version)


def _safe_archive(payload, version, target):
    """Extract strictly declared plain files, rejecting traversal/symlinks/bombs."""
    import io
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (ValueError, zipfile.BadZipFile) as exc:
        raise UpdateError('Beschädigtes DAM-Archiv') from exc
    with archive:
        members = archive.infolist()
        if len(members) != len(APP_FILES):
            raise UpdateError('Unerwartete Anzahl von Archivdateien')
        found = set()
        total = 0
        for item in members:
            name = item.filename
            path = PurePosixPath(name)
            if (name not in APP_FILES or path.is_absolute() or '..' in path.parts
                    or name in found or item.is_dir()):
                raise UpdateError('Unsichere oder unerwartete Archivdatei')
            found.add(name)
            mode = item.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise UpdateError('Archiv enthält einen Spezialdateityp')
            if item.file_size > MAX_SINGLE_FILE or item.file_size < 1:
                raise UpdateError('Unzulässige Dateigröße im Archiv')
            total += item.file_size
            if total > MAX_UNCOMPRESSED:
                raise UpdateError('Entpacktes Archiv ist zu groß')
        if found != APP_FILES:
            raise UpdateError('Benötigte DAM-Dateien fehlen')
        for item in members:
            data = archive.read(item)
            if len(data) != item.file_size:
                raise UpdateError('Fehler beim Entpacken')
            (target / item.filename).write_bytes(data)
    try:
        manifest = json.loads((target / 'version.json').read_text('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise UpdateError('Ungültiges DAM-Versionsmanifest') from exc
    if manifest != {'schema': 1, 'version': version}:
        raise UpdateError('Version im Archiv stimmt nicht mit dem Release überein')
    if not (target / 'dam.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        raise UpdateError('Ungültiges DAM-Symbol')
    for name in APP_FILES:
        if name.endswith('.py'):
            try:
                compile((target / name).read_bytes(), name, 'exec')
            except (SyntaxError, ValueError) as exc:
                raise UpdateError(f'Syntaxprüfung fehlgeschlagen: {name}') from exc
    (target / 'dam.py').chmod(0o600)


def stage(release):
    """Check + stage, never touch currently running installation on failure."""
    if not isinstance(release, Release):
        raise UpdateError('Release-Angaben fehlen')
    version_tuple(release.version)
    if not DIGEST_RE.fullmatch('sha256:' + release.sha256):
        raise UpdateError('Ungültige Release-Prüfsumme')
    parsed = urllib.parse.urlsplit(release.url)
    expected = f'/{REPO}/releases/download/v{release.version}/DAM-v{release.version}.zip'
    if (parsed.scheme != 'https' or parsed.hostname != 'github.com'
            or parsed.path != expected or parsed.query or parsed.fragment):
        raise UpdateError('Update-Quelle ist nicht das offizielle DAM-Release')
    root = data_dir()
    versions = root / 'versions'
    versions.mkdir(parents=True, exist_ok=True, mode=0o700)
    final = versions / release.version
    if final.exists() or final.is_symlink():
        raise UpdateError('Diese DAM-Version liegt bereits vor')
    temp = Path(tempfile.mkdtemp(prefix='.staging-', dir=versions))
    try:
        payload = _read_url(release.url, MAX_DOWNLOAD)
        if hashlib.sha256(payload).hexdigest() != release.sha256:
            raise UpdateError('SHA-256-Prüfung fehlgeschlagen: Update abgelehnt')
        _safe_archive(payload, release.version, temp)
        os.replace(temp, final)  # same filesystem, no partial version visible
        return final
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def _switch_current(root, version):
    """Atomic symlink swap; destinations only inside managed versions/ directory."""
    version_tuple(version)
    target = root / 'versions' / version
    if not target.is_dir() or target.is_symlink():
        raise UpdateError('Zielversion ist nicht vollständig installiert')
    temp = root / f'.current-{os.getpid()}'
    try:
        temp.symlink_to(Path('versions') / version)
        os.replace(temp, root / 'current')
    finally:
        if temp.is_symlink():
            temp.unlink()


def _current_version(root):
    current = root / 'current'
    if not current.is_symlink():
        raise UpdateError('Aktive DAM-Version fehlt')
    resolved = current.resolve(strict=True)
    if resolved.parent != (root / 'versions').resolve():
        raise UpdateError('Aktiver Versionspfad ist ungültig')
    version_tuple(resolved.name)
    return resolved.name



# ---------------------- Lokale Sicherungen und Bereinigung -----------------
# Versionsordner sind bereits vollständige DAM-Programmkopien. Eine Sicherung
# markiert eine solche Kopie als dauerhaft geschützt, statt sie zu duplizieren.

def _version_path(root, version):
    version_tuple(version)
    directory = root / 'versions' / version
    if not directory.is_dir() or directory.is_symlink():
        raise UpdateError('Gesicherte DAM-Version existiert nicht')
    if directory.resolve().parent != (root / 'versions').resolve():
        raise UpdateError('Unsicherer Versionspfad')
    return directory


def _previous_version():
    marker = state_dir() / 'previous-version.txt'
    if not marker.is_file() or marker.is_symlink():
        return None
    value = marker.read_text('utf-8').strip()
    try:
        version_tuple(value)
    except UpdateError:
        return None
    return value


def _read_backup_pins():
    manifest = state_dir() / 'backup-pins.json'
    if not manifest.exists():
        return set()
    if manifest.is_symlink():
        raise UpdateError('Sicherungsdatei ist eine Verknüpfung')
    try:
        data = json.loads(manifest.read_text('utf-8'))
        if (not isinstance(data, dict) or data.get('schema') != 1
                or not isinstance(data.get('versions'), list)
                or not all(isinstance(v, str) for v in data['versions'])):
            raise ValueError('Ungültiges Sicherungsformat')
        for version in data['versions']:
            version_tuple(version)
        return set(data['versions'])
    except (ValueError, UnicodeError) as exc:
        raise UpdateError('Sicherungsschutz kann nicht gelesen werden; Bereinigung gesperrt') from exc


def _write_backup_pins(pins):
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, filename = tempfile.mkstemp(prefix='.backup-pins-', dir=state)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump({'schema': 1, 'versions': sorted(pins, key=version_tuple)},
                      output, ensure_ascii=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.chmod(filename, 0o600)
        os.replace(filename, state / 'backup-pins.json')
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def _backup_lock():
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    return open(state / 'updater.lock', 'a+', encoding='utf-8')


def protect_version(version, protect=True):
    """Versionskopie explizit behalten / Markierung entfernen."""
    root = data_dir()
    with _backup_lock() as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateError('DAM aktualisiert gerade; bitte erneut versuchen') from exc
        _version_path(root, version)
        pins = _read_backup_pins()
        if protect:
            pins.add(version)
        else:
            pins.discard(version)
        _write_backup_pins(pins)


def _folder_bytes(directory):
    """Tatsächlich belegte reguläre Dateien, keine Symlinks verfolgen."""
    total = 0
    for parent, dirs, files in os.walk(directory, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(parent) / name).is_symlink()]
        for name in files:
            file = Path(parent) / name
            if not file.is_symlink():
                try:
                    mode = file.stat()
                except OSError:
                    continue
                if stat.S_ISREG(mode.st_mode):
                    total += mode.st_size
    return total


def stored_versions():
    """Versionskopien samt Schutz- und Speicherinformationen für die Oberfläche."""
    root = data_dir()
    current = _current_version(root)
    previous = _previous_version()
    pins = _read_backup_pins()
    versions = root / 'versions'
    result = []
    for folder in versions.iterdir():
        try:
            if folder.name.startswith('.') or folder.is_symlink() or not folder.is_dir():
                continue
            version_tuple(folder.name)
            # Nur vollständige und unveränderte lokale Versionspfade behandeln.
            _version_path(root, folder.name)
        except (UpdateError, OSError):
            continue
        version = folder.name
        active = version == current
        rollback = version == previous and not active
        pinned = version in pins
        # Alt-Migration 0.5.25 ohne Updater/Handshake nicht als
        # wiederherstellbar anbieten.
        restorable = (not active and
                      all((folder / part).is_file() and
                          not (folder / part).is_symlink()
                          for part in ('dam.py', 'dam_updater.py', 'version.json')))
        result.append(dict(
            version=version, size_bytes=_folder_bytes(folder),
            active=active, rollback=rollback, pinned=pinned,
            restorable=restorable,
            deletable=not (active or rollback or pinned),
        ))
    return sorted(result, key=lambda row: version_tuple(row['version']), reverse=True)


def delete_stored_versions(versions):
    """Explizit ausgewählte, ungeschützte Versionskopien entfernen."""
    if not isinstance(versions, (tuple, list, set)) or not versions:
        raise UpdateError('Keine Versionen zur Bereinigung ausgewählt')
    requested = list(versions)
    if len(set(requested)) != len(requested):
        raise UpdateError('Version mehrfach ausgewählt')
    for version in requested:
        version_tuple(version)
    root = data_dir()
    with _backup_lock() as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateError('DAM aktualisiert gerade; bitte erneut versuchen') from exc
        current = _current_version(root)
        previous = _previous_version()
        pinned = _read_backup_pins()
        if any(v == current or v == previous or v in pinned for v in requested):
            raise UpdateError('Aktuelle, letzte oder geschützte Version darf nicht gelöscht werden')
        targets = [_version_path(root, v) for v in requested]
        for directory in targets:
            # Pfade vor dem ersten Entfernen vollständig validiert.
            if directory.is_symlink() or directory.resolve().parent != (root / 'versions').resolve():
                raise UpdateError('Unsicherer Bereinigungspfad')
        saved = sum(_folder_bytes(folder) for folder in targets)
        for directory in targets:
            shutil.rmtree(directory)
        return saved


def validate_restoration(version):
    """Reparatur vor dem Wechsel prüfen; ältere Migrationsstände ablehnen."""
    root = data_dir()
    folder = _version_path(root, version)
    manifest = folder / 'version.json'
    if any(not (folder / name).is_file() or (folder / name).is_symlink()
           for name in APP_FILES):
        raise UpdateError('Diese alte DAM-Version unterstützt keine sichere Wiederherstellung')
    try:
        if json.loads(manifest.read_text('utf-8')) != {'schema': 1, 'version': version}:
            raise UpdateError('Gesicherte Version passt nicht zum Versionsmanifest')
        if not (folder / 'dam.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise UpdateError('Gesichertes DAM-Symbol ist beschädigt')
        for name in APP_FILES:
            if name.endswith('.py'):
                compile((folder / name).read_bytes(), str(folder / name), 'exec')
    except (OSError, UnicodeError, ValueError, SyntaxError) as exc:
        raise UpdateError('Gesicherte DAM-Version ist beschädigt') from exc
    return folder


def restore(previous_pid, version):
    """Beliebige gesicherte DAM-Version per Neustart mit automatischem Rollback."""
    root = data_dir()
    with _backup_lock() as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateError('DAM aktualisiert gerade; bitte erneut versuchen') from exc
        _wait_for_pid(previous_pid)
        current = _current_version(root)
        if version == current:
            raise UpdateError('Die ausgewählte DAM-Version ist bereits aktiv')
        validate_restoration(version)
        _switch_current(root, version)
        try:
            _launch_and_wait(root)
            (state_dir() / 'previous-version.txt').write_text(current + '\n', 'utf-8')
            (state_dir() / 'updater-error.json').unlink(missing_ok=True)
        except Exception as exc:
            _switch_current(root, current)
            _record_failure(str(exc), version)
            try:
                subprocess.Popen([str(Path.home() / '.local' / 'bin' / 'dam-launcher')],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                pass
            raise

def _wait_for_pid(pid, timeout=25):
    if pid <= 0 or pid == os.getpid():
        raise UpdateError('Ungültige DAM-Prozess-ID')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise UpdateError('Prozessberechtigung fehlt') from exc
        time.sleep(0.2)
    raise UpdateError('DAM konnte nicht rechtzeitig beendet werden')


def _launch_and_wait(root, timeout=30):
    st = state_dir()
    st.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, filename = tempfile.mkstemp(prefix='ready-', dir=st)
    os.close(fd)
    os.unlink(filename)
    ready = Path(filename)
    launcher = Path.home() / '.local' / 'bin' / 'dam-launcher'
    if not launcher.is_file():
        raise UpdateError('DAM-Startprogramm fehlt')
    env = {**os.environ, 'DAM_UPDATE_READY_FILE': str(ready)}
    child = subprocess.Popen([str(launcher)], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise UpdateError('Neue DAM-Version wurde vorzeitig beendet')
            if ready.is_file():
                # Delayed crash protection: stay alive briefly after GTK says ready.
                time.sleep(1.0)
                if child.poll() is not None:
                    raise UpdateError('Neue DAM-Version stürzte nach dem Start ab')
                return
            time.sleep(0.2)
        raise UpdateError('Neue DAM-Version bestätigt den Start nicht')
    finally:
        ready.unlink(missing_ok=True)
        if child.poll() is None and time.monotonic() >= deadline:
            child.terminate()


def _record_failure(message, version):
    st = state_dir()
    st.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = st / 'updater-error.json'
    target.write_text(json.dumps({'version': version, 'error': message,
                                  'time': int(time.time())}, ensure_ascii=False), 'utf-8')
    target.chmod(0o600)


def activate(previous_pid, target_version):
    """Called in an independent updater process, *after* DAM has been closed."""
    root = data_dir()
    state_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(state_dir() / 'updater.lock', 'w', encoding='utf-8') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateError('Ein DAM-Update läuft bereits') from exc
        _wait_for_pid(previous_pid)
        previous_version = _current_version(root)
        if version_tuple(target_version) <= version_tuple(previous_version):
            raise UpdateError('Nur eine neuere DAM-Version darf aktiviert werden')
        _switch_current(root, target_version)
        try:
            _launch_and_wait(root)
            (state_dir() / 'previous-version.txt').write_text(previous_version + '\n', 'utf-8')
            (state_dir() / 'updater-error.json').unlink(missing_ok=True)
        except Exception as exc:
            _switch_current(root, previous_version)
            _record_failure(str(exc), target_version)
            try:
                subprocess.Popen([str(Path.home() / '.local' / 'bin' / 'dam-launcher')],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                pass
            raise


def rollback(previous_pid):
    """User-triggered rollback to immediate previous version noted after update."""
    st = state_dir()
    previous = st / 'previous-version.txt'
    if not previous.is_file():
        raise UpdateError('Keine Rückfallversion vorhanden')
    target = previous.read_text('utf-8').strip()
    version_tuple(target)
    root = data_dir()
    with open(st / 'updater.lock', 'w', encoding='utf-8') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _wait_for_pid(previous_pid)
        current = _current_version(root)
        _switch_current(root, target)
        try:
            _launch_and_wait(root)
            previous.write_text(current + '\n', 'utf-8')
        except Exception:
            _switch_current(root, current)
            subprocess.Popen([str(Path.home() / '.local' / 'bin' / 'dam-launcher')],
                             start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            raise


def main(argv):
    if len(argv) == 4 and argv[1] == 'activate':
        activate(int(argv[2]), argv[3])
    elif len(argv) == 3 and argv[1] == 'rollback':
        rollback(int(argv[2]))
    elif len(argv) == 4 and argv[1] == 'restore':
        restore(int(argv[2]), argv[3])
    else:
        raise UpdateError('Ungültiger Updater-Aufruf')


if __name__ == '__main__':
    try:
        main(sys.argv)
    except Exception as exc:
        # Eine bereits protokollierte fehlgeschlagene Version nicht durch
        # den generischen CLI-Fehler mit 'unbekannt' überschreiben.
        if not (state_dir() / 'updater-error.json').exists():
            _record_failure(str(exc), 'unbekannt')
        sys.exit(1)

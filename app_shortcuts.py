"""Desktop-Verknüpfungen und Autostart nur innerhalb des Benutzerprofils.

Es werden vorhandene .desktop-Starter verwendet – ohne Shell und ohne Root.
Andere, nicht von DAM angelegte Autostart-Einträge werden nicht verändert.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess

MANAGED = 'X-DAM-Managed=true'


def valid_source(filename):
    if not filename or not isinstance(filename, str):
        return False
    source = Path(filename).expanduser()
    return source.suffix == '.desktop' and source.is_file() and os.access(source, os.R_OK)


def source_for(item):
    source = item.get('desktop_file')
    if not valid_source(source):
        raise ValueError('Für diese App gibt es keinen verwendbaren Desktop-Starter.')
    return Path(source)


def desktop_id(item):
    """Nur sichere Dateinamen aus vorhandenen Desktop-Startern übernehmen."""
    source = source_for(item)
    identifier = item.get('desktop_id') or source.name
    identifier = str(identifier).removesuffix('.desktop')
    # Keine Pfadbestandteile, Kontrollzeichen oder ungeprüften Eingaben.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,180}', identifier):
        raise ValueError('Der Name des App-Starters ist ungültig.')
    return identifier + '.desktop'


def desktop_folder():
    """Bevorzugt xdg-user-dir (inklusive lokalisiertem ~/Schreibtisch)."""
    try:
        proc = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True,
                              text=True, timeout=4, check=False)
        path = proc.stdout.strip()
        if proc.returncode == 0 and path and Path(path).is_dir():
            return Path(path)
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in (Path.home() / 'Schreibtisch', Path.home() / 'Desktop'):
        if candidate.is_dir():
            return candidate
    raise RuntimeError('Desktop-Ordner nicht gefunden. Bitte in Ubuntu einen Desktop-Ordner einrichten.')


def create_desktop_shortcut(item):
    source = source_for(item)
    folder = desktop_folder()
    dest = folder / desktop_id(item)
    if dest.exists() or dest.is_symlink():
        return 'Die Desktop-Verknüpfung ist bereits vorhanden.'
    shutil.copyfile(source, dest)
    dest.chmod(0o755)
    # GNOME benötigt für klickbare .desktop-Dateien zusätzlich einen Trusted-Metadatenwert.
    try:
        proc = subprocess.run(['gio', 'set', str(dest), 'metadata::trusted', 'true'],
                              capture_output=True, text=True, timeout=5)
        if proc.returncode != 0:
            return ('Verknüpfung erstellt. Falls Ubuntu sie noch nicht startet: '
                    'Rechtsklick auf dem Desktop → „Start erlauben“.')
    except (OSError, subprocess.SubprocessError):
        return ('Verknüpfung erstellt. Falls Ubuntu sie noch nicht startet: '
                'Rechtsklick auf dem Desktop → „Start erlauben“.')
    return 'Desktop-Verknüpfung erfolgreich erstellt.'


def autostart_file(item):
    return Path.home() / '.config' / 'autostart' / desktop_id(item)


def autostart_state(item):
    """'none', 'managed' oder 'foreign' – Fremdeinträge nie löschen."""
    try:
        path = autostart_file(item)
    except ValueError:
        return 'none'
    if not path.exists() and not path.is_symlink():
        return 'none'
    try:
        if path.is_file() and MANAGED in path.read_text(encoding='utf-8'):
            return 'managed'
    except OSError:
        pass
    return 'foreign'


def add_autostart(item):
    source = source_for(item)
    dest = autostart_file(item)
    if autostart_state(item) != 'none':
        return 'Für diese App ist bereits ein Autostart-Eintrag vorhanden.'
    text = source.read_text(encoding='utf-8')
    if '[Desktop Entry]' not in text:
        raise ValueError('Der App-Starter enthält keinen gültigen Desktop-Eintrag.')
    # Ein eventuell deaktivierter Eintrag wird in der neuen Kopie aktiviert.
    text = re.sub(r'(?im)^\s*(?:Hidden|X-GNOME-Autostart-enabled)\s*=.*\n?', '', text)
    text = text.replace('[Desktop Entry]', '[Desktop Entry]\n' + MANAGED, 1)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Exklusiv erstellen: kein Überschreiben fremder Autostart-Definitionen.
    with dest.open('x', encoding='utf-8') as file:
        file.write(text)
    dest.chmod(0o644)
    return 'App wurde zum Autostart hinzugefügt.'


def remove_autostart(item):
    if autostart_state(item) != 'managed':
        raise RuntimeError('Der Autostart-Eintrag wurde nicht von DAM erstellt und bleibt geschützt.')
    autostart_file(item).unlink()
    return 'App wurde aus dem Autostart entfernt.'

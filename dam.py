#!/usr/bin/env python3
"""DAM 0.6.4 – Manuelle Backup-Verwaltung und Versionsbereinigung."""
import gzip
import json
import math
from functools import lru_cache
import glob
import os
import logging
from logging.handlers import RotatingFileHandler
import sys
import traceback
import re
import subprocess
import threading
import time
from datetime import datetime

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, Gtk, GLib, Pango

import rustdesk_update
import dam_updater
import package_updates
import app_shortcuts
import apt_install
import apt_remove

VERSION = '0.6.4'
# Nur technische Fehler und Paketaktionen protokollieren, niemals Passwörter.
_LOG_DIR = os.path.expanduser('~/.local/state/dam')
try:
    os.makedirs(_LOG_DIR, mode=0o700, exist_ok=True)
    os.chmod(_LOG_DIR, 0o700)
    _handler = RotatingFileHandler(os.path.join(_LOG_DIR, 'dam.log'),
                                   maxBytes=1024*1024, backupCount=2, encoding='utf-8')
    _handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
    _log = logging.getLogger('dam')
    _log.setLevel(logging.INFO)
    _log.addHandler(_handler)
except OSError:
    _log = logging.getLogger('dam')
    _log.addHandler(logging.NullHandler())

_prev_excepthook = sys.excepthook

def _log_uncaught(kind, value, tb):
    _log.error('Unbehandelte Ausnahme: %s', kind.__name__,
               exc_info=(kind, value, tb))
    _prev_excepthook(kind, value, tb)

sys.excepthook = _log_uncaught

SORTS = ['Name A–Z', 'Name Z–A', 'Größe ↑', 'Größe ↓',
         'Installationsdatum ↓', 'Aktualisierungsdatum ↓', 'Änderungsdatum ↓']
CATALOG = [
    ('RustDesk', 'rustdesk', 'preferences-desktop-remote-desktop-symbolic'),
    ('VLC', 'vlc', 'vlc'),
    ('GIMP', 'gimp', 'gimp'),
    ('OBS Studio', 'obs-studio', 'com.obsproject.Studio'),
    ('Krita', 'krita', 'krita'),
    ('Kdenlive', 'kdenlive', 'org.kde.kdenlive'),
    ('LibreOffice', 'libreoffice', 'libreoffice-startcenter'),
    ('Firefox', 'firefox', 'firefox'),
    ('Thunderbird', 'thunderbird', 'thunderbird'),
    ('DAM', 'dam', 'de.davegage.dam'),
]


# Standardbeschreibungen sind bewusst kurz und vollständig deutsch.
# Eigene Texte können unabhängig vom Programm in ~/DAM/app_beschreibungen.json
# hinterlegt werden. Die Datei wird bei Updates nicht überschrieben.
APP_DESCRIPTIONS = {
    'rustdesk': 'Fernzugriff und Fernwartung von Computern.',
    'vlc': 'Spielt Videos, Musik und viele Medienformate ab.',
    'gimp': 'Bilder bearbeiten und retuschieren.',
    'obs studio': 'Bildschirm aufnehmen und live streamen.',
    'krita': 'Digital malen und zeichnen.',
    'kdenlive': 'Videos schneiden und bearbeiten.',
    'libreoffice': 'Office-Paket für Texte, Tabellen und Präsentationen.',
    'firefox': 'Webbrowser zum Surfen im Internet.',
    'thunderbird': 'E-Mails, Kalender und Kontakte verwalten.',
    'anydesk': 'Computer aus der Ferne bedienen.',
    'aktualisierungsverwaltung': 'Sucht und installiert Ubuntu-Aktualisierungen.',
    'app-zentrum': 'Ubuntu-Programme entdecken und installieren.',
    'archivverwaltung': 'ZIP- und andere Archivdateien öffnen und erstellen.',
    'bildbetrachter': 'Bilder und Fotos ansehen.',
    'dateien': 'Dateien und Ordner durchsuchen und verwalten.',
    'terminal': 'Befehle direkt im System ausführen.',
    'einstellungen': 'Ubuntu und Gerätefunktionen konfigurieren.',
    'systemüberwachung': 'Prozesse und Systemauslastung anzeigen.',
    'texteditor': 'Einfache Textdateien erstellen und bearbeiten.',
    'rechner': 'Berechnungen ausführen.',
    'kalender': 'Termine und Ereignisse verwalten.',
    'kamera': 'Fotos und Videos mit der Kamera aufnehmen.',
    'dokumentbetrachter': 'PDF-Dateien und Dokumente anzeigen.',
    'passwörter und schlüssel': 'Passwörter und Schlüssel verwalten.',
    'software & aktualisierungen': 'Softwarequellen und Update-Einstellungen verwalten.',
    'software und aktualisierungen': 'Softwarequellen und Update-Einstellungen verwalten.',
    'startprogramme': 'Programme für den automatischen Start festlegen.',
    'laufwerke': 'Festplatten und Datenträger verwalten.',
    'disk usage analyzer': 'Zeigt an, wie viel Speicher Ordner belegen.',
    'gnome disks': 'Datenträger anzeigen und verwalten.',
    'dam': 'Programme installieren, aktualisieren und deinstallieren.',
}


def custom_descriptions():
    """Optionale, benutzereigene deutsche Beschreibungen laden."""
    path = os.path.expanduser('~/DAM/app_beschreibungen.json')
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            data = json.load(stream)
        if isinstance(data, dict):
            return {str(k).casefold().strip(): str(v).strip()
                    for k, v in data.items() if isinstance(v, str) and v.strip()}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def describe_app(name, package='', overrides=None):
    """Beschreibung aus Nutzervorgaben oder den deutschen Standardtexten."""
    overrides = overrides or {}
    for key in (name.casefold().strip(), (package or '').casefold().strip()):
        if key in overrides:
            return overrides[key]
        if key in APP_DESCRIPTIONS:
            return APP_DESCRIPTIONS[key]
    return 'Für diese App ist noch keine Kurzbeschreibung hinterlegt.'


def package_info():
    """Installed Debian packages, indexed by package name."""
    packages = {}
    try:
        result = subprocess.run(
            ['dpkg-query', '-W', '-f=${binary:Package}\t${db:Status-Abbrev}\t${Installed-Size}\t${Version}\n'],
            capture_output=True, text=True, timeout=12, check=True)
        for line in result.stdout.splitlines():
            fields = line.split('\t')
            if len(fields) != 4:
                continue
            name, status, kib, version = fields
            if not status.startswith('ii'):
                continue
            try:
                packages[name.split(':')[0]] = (int(kib) * 1024, version)
            except ValueError:
                continue
    except (OSError, subprocess.SubprocessError):
        pass
    return packages


def external_package_versions():
    """Best-effort lookup of installed Snap and Flatpak app versions."""
    found = {}
    try:
        result = subprocess.run(['snap', 'list'], capture_output=True,
                                text=True, timeout=8)
        if result.returncode == 0:
            for line in result.stdout.splitlines()[1:]:
                fields = line.split()
                if len(fields) >= 2:
                    found[fields[0].lower()] = clean_version(fields[1])
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        result = subprocess.run(
            ['flatpak', 'list', '--app', '--columns=application,name,version'],
            capture_output=True, text=True, timeout=8)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                fields = line.split('\t')
                if len(fields) >= 3:
                    app_id, name, version = fields[:3]
                    if version.strip():
                        found[app_id.lower()] = version.strip()
                        found[name.casefold()] = version.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return found


# Mapping between visible launcher names and real Ubuntu package identifiers.
# A desktop launcher is not guaranteed to share its name with its DEB package.
PACKAGE_ALIASES = {
    'rustdesk': ('rustdesk',),
    'libreoffice': ('libreoffice', 'libreoffice-common', 'libreoffice-core'),
    'libreoffice writer': ('libreoffice-writer',),
    'libreoffice calc': ('libreoffice-calc',),
    'firefox': ('firefox',),
    'thunderbird': ('thunderbird',),
    'gimp': ('gimp',),
    'vlc': ('vlc',),
    'obs studio': ('obs-studio',),
    'krita': ('krita',),
    'kdenlive': ('kdenlive',),
}


CATALOG_PACKAGE_NAMES = {package for _, package, _ in CATALOG}


def clean_version(value):
    """Do not show the literal text 'None' as an installed version."""
    if value is None:
        return None
    value = str(value).strip()
    return value if value and value.casefold() not in ('none', 'null', 'unknown', '–') else None


@lru_cache(maxsize=64)
def direct_deb_version(package):
    """Fallback for desktop entries whose DEB version wasn't resolved by the bulk query."""
    if not package or not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', package):
        return None
    try:
        proc = subprocess.run(
            ['dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}', package],
            capture_output=True, text=True, timeout=4)
        if proc.returncode != 0:
            return None
        status, version = proc.stdout.strip().split('\t', 1)
        if status.strip() == 'installed':
            return clean_version(version)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def installed_version(name, package, app_id, packages, external):
    """Look up Snap/Flatpak first, then installed DEB packages."""
    keys = [package or '', app_id.removesuffix('.desktop'),
            name.casefold(), name.casefold().replace(' ', '-')]
    keys.extend(PACKAGE_ALIASES.get(name.casefold(), ()))
    for key in keys:
        version = clean_version(external.get(key.casefold()))
        if version:
            return version
    for key in keys:
        if key in packages:
            version = clean_version(packages[key][1])
            if version:
                return version
    # Query the exact DEB package for curated apps as a second, independent path.
    known = set(CATALOG_PACKAGE_NAMES)
    for key in keys:
        if key in known:
            version = direct_deb_version(key)
            if version:
                return version
    return None


def usable_icon(icon, fallback='application-x-executable'):
    """Avoid GTK's red missing-image placeholder for unavailable icons."""
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    if icon is not None:
        try:
            if isinstance(icon, Gio.FileIcon):
                file = icon.get_file()
                if file and file.query_exists(None):
                    return icon
            if isinstance(icon, Gio.ThemedIcon):
                for name in icon.get_names():
                    if theme.has_icon(name):
                        return Gio.ThemedIcon.new(name)
            if isinstance(icon, Gio.EmblemedIcon):
                return usable_icon(icon.get_icon(), fallback)
        except (AttributeError, TypeError, ValueError):
            pass
    for name in (fallback, 'application-x-executable', 'applications-other'):
        if theme.has_icon(name):
            return Gio.ThemedIcon.new(name)
    return None


def package_dates():
    """Best effort: dpkg log entries may be absent due to log rotation."""
    dates = {}
    paths = ['/var/log/dpkg.log'] + glob.glob('/var/log/dpkg.log.[0-9]*')
    for path in paths:
        try:
            opener = gzip.open if path.endswith('.gz') else open
            with opener(path, 'rt', errors='replace') as stream:
                for line in stream:
                    # yyyy-mm-dd hh:mm:ss install|upgrade package ...
                    parts = line.split(' ', 5)
                    if len(parts) < 4 or parts[2] not in ('install', 'upgrade'):
                        continue
                    name = parts[3].split(':')[0]
                    stamp = parts[0] + ' ' + parts[1]
                    if not re.match(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$', stamp):
                        continue
                    dates.setdefault(name, {})
                    key = 'installed' if parts[2] == 'install' else 'updated'
                    if key == 'installed':
                        dates[name][key] = min(dates[name].get(key, stamp), stamp)
                    else:
                        dates[name][key] = max(dates[name].get(key, stamp), stamp)
        except (OSError, UnicodeError):
            continue
    return dates


def match_package(name, app_id, packages):
    candidates = list(PACKAGE_ALIASES.get(name.casefold(), ()))
    candidates.extend([
        app_id.removesuffix('.desktop').lower(),
        app_id.removesuffix('.desktop').split('.')[-1].lower(),
        name.lower().replace(' ', '-'),
        name.lower().replace(' ', ''),
    ])
    for candidate in candidates:
        if candidate in packages:
            return candidate
    return None


def friendly_size(byte_count):
    if byte_count is None:
        return '–'
    return f'{byte_count / 1024 / 1024:.1f} MB'


def friendly_date(value):
    return value[:10] if value else '–'


class DAM(Adw.Application):
    def __init__(self):
        super().__init__(application_id='de.davegage.dam',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect('activate', self.start)
        # GTK-App-Aktion: Strg+Q beendet DAM aus allen Reitern.
        quit_action = Gio.SimpleAction.new('quit', None)
        quit_action.connect('activate', lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action('app.quit', ['<Primary>q'])
        cancel_action = Gio.SimpleAction.new('cancel_scan', None)
        cancel_action.connect('activate', self.cancel_scan)
        self.add_action(cancel_action)
        self.set_accels_for_action('app.cancel_scan', ['Escape'])
        self.rustdesk_release = None
        self.dam_release = None
        self.rustdesk_update_available = False
        self.update_check_running = False
        self.update_install_running = False
        self.update_records = {}
        self.install_running = False
        self.remove_running = False
        self.last_remove_error = None
        self.list_refresh_running = False
        self._initial_loading = True
        self._update_tab_visited = False
        self._first_update_check_done = False
        self._catalog_ready = False
        self._refresh_generation = 0
        self._update_scan_generation = 0
        self._update_cancel_event = None
        self.list_spinner = None
        self.list_loader_panel = None
        self.list_loader_caption = None
        self.loader_retry_button = None
        self._refresh_plan = None
        self.page_controls = {}
        self.operation_spinners = {}
        self.operation_statuses = {}
        self.operation_stages = {}
        self.operation_start_times = {}
        self.operation_timer_ids = {}
        self._remove_worker = None
        self._remove_worker_finished_at = None
        self._remove_finish_handled = False
        # Alle drei Suchfelder behalten auch bei einer höheren Update-Schaltfläche
        # dieselbe natürliche Höhe, einschließlich späterer Seiten-Neuaufbauten.
        self.search_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.VERTICAL)

    def update_ui_lock(self):
        """Alle Bedienelemente während Prüf- oder Paketvorgängen sperren.

        Die globale Esc-Aktion bleibt aktiv. Echte Paketoperationen dürfen nicht
        über Esc unterbrochen werden, um APT/dpkg nicht zu beschädigen.
        """
        busy = any((self._initial_loading, self.list_refresh_running,
                    self.update_check_running, self.install_running,
                    self.remove_running, self.update_install_running))
        for name in ('stack', 'switcher', 'info_button'):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.set_sensitive(not busy)

    def cancel_scan(self, *_args):
        """Esc: Nur lesende Prüfungen abbrechen, nie Paketänderungen."""
        if self.install_running or self.remove_running or self.update_install_running:
            return False
        if self.update_check_running:
            if self._update_cancel_event is not None:
                self._update_cancel_event.set()
            self._update_scan_generation += 1   # verspaetete Ergebnisse verwerfen
            self.update_check_running = False
            self._update_cancel_event = None
            self.set_list_loading(False)
            self.update_check_button.set_sensitive(True)
            self.update_empty_label.set_text('Updateprüfung abgebrochen. Erneut prüfen ist möglich.')
            self.update_empty_label.set_visible(True)
            self.update_check_info.set_text('Updateprüfung mit Esc abgebrochen.')
            self.update_select_button.set_sensitive(False)
            self.update_all_button.set_sensitive(False)
            self.update_select_all.set_sensitive(False)
            self.update_ui_lock()
            return False
        if self.list_refresh_running and self._refresh_plan is None:
            self._refresh_generation += 1     # Hintergrund-Rueckmeldungen verwerfen
            self.list_refresh_running = False
            self._initial_loading = False
            self.set_list_loading(False)
            if not self._catalog_ready and self.loader_retry_button is not None:
                self.list_loader_caption.set_text('Einlesen abgebrochen')
                self.list_spinner.set_visible(False)
                self.loader_retry_button.set_visible(True)
                self.list_loader_panel.set_visible(True)
            if self._catalog_ready:
                self.install_status.set_text('App-Liste wurde mit Esc nicht erneut eingelesen.')
            self.update_ui_lock()
        return False

    def retry_app_scan(self, *_args):
        """Wird nur nach einem fruehzeitig abgebrochenen Start-Scan angeboten."""
        if self._catalog_ready or self.list_refresh_running:
            return False
        self._initial_loading = True
        self.refresh_app_lists(0, operation='startup')
        return False

    def start_operation_indicator(self, kind, message):
        """GTK-Anzeige für laufende Vorgänge; keine erfundene Prozentanzeige."""
        self.stop_operation_indicator(kind)
        spinner = self.operation_spinners.get(kind)
        label = self.operation_statuses.get(kind)
        if spinner is None or label is None:
            return
        self.operation_stages[kind] = message
        self.operation_start_times[kind] = time.monotonic()
        spinner.set_visible(True)
        spinner.start()
        label.set_text(message + ' · 0 s')
        self.operation_timer_ids[kind] = GLib.timeout_add_seconds(
            1, self.tick_operation_indicator, kind)

    def tick_operation_indicator(self, kind):
        if kind not in self.operation_start_times:
            return False
        label = self.operation_statuses.get(kind)
        if label is None:
            return False
        elapsed = int(time.monotonic() - self.operation_start_times[kind])
        label.set_text(f'{self.operation_stages[kind]} · {elapsed} s')
        return True

    def set_operation_stage(self, kind, message):
        if kind not in self.operation_start_times:
            return False
        self.operation_stages[kind] = message
        self.tick_operation_indicator(kind)
        return False

    def stop_operation_indicator(self, kind):
        timer_id = self.operation_timer_ids.pop(kind, None)
        if timer_id is not None:
            GLib.source_remove(timer_id)
        self.operation_stages.pop(kind, None)
        self.operation_start_times.pop(kind, None)
        spinner = self.operation_spinners.get(kind)
        if spinner is not None:
            spinner.stop()
            spinner.set_visible(False)

    def set_list_loading(self, active, message='App-Liste wird aktualisiert …'):
        """Zentrale Ladefläche für Katalog-Neuaufbau und Updateprüfung."""
        if self.list_loader_panel is None or self.list_spinner is None:
            return
        if active:
            self.list_spinner.set_visible(True)
            if self.loader_retry_button is not None:
                self.loader_retry_button.set_visible(False)
            if self.list_loader_caption is not None:
                self.list_loader_caption.set_text(message)
            self.list_loader_panel.set_visible(True)
            self.list_spinner.start()
        else:
            self.list_spinner.stop()
            self.list_loader_panel.set_visible(False)

    def get_apps(self, packages, dates, external, overrides):
        apps = []
        seen = set()
        for info in Gio.AppInfo.get_all():
            if not info.should_show():
                continue
            name = info.get_display_name() or info.get_name()
            app_id = info.get_id() or ''
            if not name or (name.casefold(), app_id) in seen:
                continue
            seen.add((name.casefold(), app_id))
            package = match_package(name, app_id, packages)
            size, _deb_version = packages.get(package, (None, None))
            version = installed_version(name, package, app_id, packages, external)
            logs = dates.get(package, {})
            changed = ''
            try:
                # .desktop timestamp; NOT necessarily application update time
                filename = info.get_filename() if hasattr(info, 'get_filename') else None
                if filename and os.path.isfile(filename):
                    changed = datetime.fromtimestamp(os.path.getmtime(filename)).strftime('%Y-%m-%d %H:%M:%S')
            except OSError:
                pass
            apps.append(dict(name=name, icon=usable_icon(info.get_icon()), size=size,
                             beschreibung=describe_app(name, package, overrides),
                             version=version, installed=logs.get('installed', ''),
                             updated=logs.get('updated', ''), changed=changed,
                             package=package,
                             is_removable=(package in apt_remove.ALLOWED and package in packages),
                             desktop_id=app_id,
                             desktop_file=(info.get_filename() if hasattr(info, 'get_filename') else None)))
        return sorted(apps, key=lambda item: item['name'].casefold())

    def make_app_lists(self, packages, dates, external, overrides, candidates=None):
        """Die App-Kataloge für die Kacheln frisch aus Ubuntu erzeugen."""
        installed = self.get_apps(packages, dates, external, overrides)
        available = []
        for name, package, icon in CATALOG:
            if package == 'dam':
                # DAM selbst wird benutzerlokal und nicht über APT installiert.
                # Nur tatsächlich vorhandene Starter dürfen als installiert gelten.
                launcher = os.path.expanduser('~/.local/share/applications/de.davegage.dam.desktop')
                image_path = os.path.expanduser('~/.local/share/icons/hicolor/256x256/apps/de.davegage.dam.png')
                is_installed = os.path.isfile(launcher)
                matching = next((a for a in installed if a['name'].casefold() == 'dam'), None)
                if is_installed and os.path.isfile(image_path):
                    image = Gio.FileIcon.new(Gio.File.new_for_path(image_path))
                else:
                    image = (matching['icon'] if matching else usable_icon(Gio.ThemedIcon.new('application-x-executable')))
                available.append(dict(
                    name='DAM', icon=image, beschreibung=describe_app('DAM', 'dam', overrides),
                    size=None, version=VERSION if is_installed else None, package='dam',
                    installed='', updated='', changed='', is_installed=is_installed,
                    desktop_id='de.davegage.dam.desktop' if is_installed else '',
                    desktop_file=launcher if is_installed else None,
                    apt_candidate=None))
                continue
            size, _deb_version = packages.get(package, (None, None))
            app_match = next((a for a in installed
                              if a['name'].casefold() == name.casefold()), None)
            version = installed_version(name, package, '', packages, external)
            if app_match and clean_version(app_match['version']):
                version = app_match['version']
            resolved_icon = (app_match['icon'] if app_match else
                             usable_icon(Gio.ThemedIcon.new(icon),
                                         'applications-graphics' if name in ('GIMP', 'Krita', 'Kdenlive')
                                         else 'application-x-executable'))
            if not clean_version(version):
                version = None
            available.append(dict(name=name, icon=resolved_icon,
                                  beschreibung=describe_app(name, package, overrides),
                                  size=size, version=version, package=package,
                                  installed='', updated='', changed='',
                                  is_installed=bool(version or app_match),
                                  desktop_id=app_match.get('desktop_id', '') if app_match else '',
                                  desktop_file=app_match.get('desktop_file') if app_match else None,
                                  apt_candidate=(candidates.get(package) if candidates is not None else apt_install.candidate(package)) if package in apt_install.ALLOWED else None))

        # DAM hat keinen APT/Snap/Flatpak-Paketeintrag. Manche Desktop-Umgebungen
        # lassen den benutzerlokalen Starter in Gio.AppInfo.get_all() aus. DAM
        # dennoch als Update-Kachel registrieren, wenn es installiert ist.
        # Sonst wird ein korrekt erkanntes GitHub-Release stillschweigend verworfen.
        dam_item = next((item for item in available if item['package'] == 'dam'
                         and item.get('is_installed')), None)
        if dam_item and not any(item['name'].casefold() == 'dam' for item in installed):
            installed.append({**dam_item, 'is_removable': False})
            installed.sort(key=lambda item: item['name'].casefold())

        return installed, available

    def start(self, _app):
        if getattr(self, 'window', None):
            self.window.present()
            return
        # Fenster sofort anzeigen: Dateiprotokolle, Snap, Flatpak und APT
        # werden erst nach dem ersten Zeichnen in einem Worker eingelesen.
        installed, available = [], []

        self.window = Adw.ApplicationWindow(application=self)
        self.window.set_title('DAM')
        self.window.set_default_size(1000, 640)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main.add_css_class('dam-root')
        self.main_box = main
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label='DAM'))
        main.append(header)
        stack = Gtk.Stack()
        self.stack = stack
        stack.set_vexpand(True)
        # Vier gleichartige, gruppierte GTK-ToggleButtons: Info ist kein
        # Sonderbutton mehr. Immer genau ein Reiter ist sichtbar/ausgewaehlt.
        navigation = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        navigation.add_css_class('dam-navigation')
        navigation.set_halign(Gtk.Align.CENTER)
        navigation.set_margin_top(8)
        navigation.set_margin_bottom(8)
        self.switcher = navigation
        self.nav_buttons = {}
        self._current_nav_mode = 'install'
        self._last_main_mode = 'install'
        first_button = None
        for mode, label in (
                ('install', '📦 Installieren'),
                ('update', '🔄 Aktualisieren'),
                ('remove', '🗑️ Deinstallieren'),
                ('info', 'ⓘ')):
            button = Gtk.ToggleButton(label=label)
            if first_button is None:
                first_button = button
            else:
                button.set_group(first_button)
            button.set_valign(Gtk.Align.FILL)
            if mode == 'info':
                button.add_css_class('dam-info-toggle')
                button.set_tooltip_text('Informationen zu DAM')
            button.connect('toggled', self.on_navigation_toggled, mode)
            navigation.append(button)
            self.nav_buttons[mode] = button
        self.info_button = self.nav_buttons['info']
        main.append(navigation)

        self.update_check_info = Gtk.Label(label='Updateprüfung noch nicht gestartet.')
        self.update_check_info.set_wrap(True)
        self.update_check_info.set_xalign(0)
        self.update_check_info.add_css_class('dim-label')

        self.add_page(stack, 'install', '📦 Installieren', available, 'installieren')
        self.add_page(stack, 'update', '🔄 Aktualisieren', installed, 'aktualisieren')
        self.add_page(stack, 'remove', '🗑️ Deinstallieren', installed, 'deinstallieren')
        stack.set_visible_child_name('install')
        # Ein globales Overlay bleibt während des Neuaufbaus aller drei Seiten aktiv.
        # Anders als die alten Pro-Seite-Spinner wird es dabei nicht zerstört.
        app_area = Gtk.Overlay()
        app_area.set_vexpand(True)
        app_area.set_child(stack)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        panel.add_css_class('dam-loading-panel')
        panel.set_halign(Gtk.Align.CENTER)
        panel.set_valign(Gtk.Align.CENTER)
        # Liste liegt zwischen Werkzeugleiste (48+10 px) und Fussbereich
        # (48+28+6+10 px). Daher genau dieselbe nutzbare Flaeche wie die
        # bereits zentrierten Ergebnis-Meldungen als Bezug verwenden.
        # Der Ladeblock zentriert sich horizontal und vertikal in der LISTE,
        # nicht in der gesamten App-Seite samt Werkzeug- und Aktionsleiste.
        panel.set_margin_top(58)
        panel.set_margin_bottom(168)
        panel.set_size_request(330, 132)
        spinner = Gtk.Spinner()
        spinner.add_css_class('dam-loading-spinner')
        spinner.set_size_request(56, 56)
        spinner.set_halign(Gtk.Align.CENTER)
        panel.append(spinner)
        caption = Gtk.Label(label='App-Liste wird aktualisiert …')
        caption.set_size_request(294, 26)
        caption.set_halign(Gtk.Align.CENTER)
        caption.set_xalign(0.5)
        caption.set_justify(Gtk.Justification.CENTER)
        panel.append(caption)
        self.list_loader_caption = caption
        retry = Gtk.Button(label='Erneut laden')
        retry.set_halign(Gtk.Align.CENTER)
        retry.set_visible(False)
        retry.connect('clicked', self.retry_app_scan)
        panel.append(retry)
        self.loader_retry_button = retry
        panel.set_visible(False)
        app_area.add_overlay(panel)
        app_area.set_measure_overlay(panel, False)
        self.list_loader_panel = panel
        self.list_spinner = spinner
        self.content_stack = Gtk.Stack()
        self.content_stack.set_vexpand(True)
        self.content_stack.add_named(app_area, 'apps')
        self.content_stack.add_named(self.create_info_page(), 'info')
        self.content_stack.set_visible_child_name('apps')
        main.append(self.content_stack)
        self.nav_buttons['install'].set_active(True)
        self.apply_mode_theme('install')
        self.window.set_content(main)
        self.add_style()
        self.window.present()
        # Erst nach erfolgreichem Fensteraufbau dem externen Updater bestätigen.
        GLib.timeout_add(900, self._signal_update_ready)
        # Erst das Fenster zeichnen lassen, dann im Hintergrund Paketdaten laden.
        # Währenddessen schützt die Sperre vor Aktionen auf unvollständigen Listen.
        self.update_ui_lock()
        GLib.timeout_add(80, self._begin_startup_scan)

    def _signal_update_ready(self):
        """Handshake mit unabhängiger Watchdog-Instanz nach dem Fensterstart."""
        target = os.environ.pop('DAM_UPDATE_READY_FILE', '')
        if target:
            expected = os.path.expanduser('~/.local/state/dam/ready-')
            if target.startswith(expected) and '/' not in target[len(expected):]:
                try:
                    with open(target, 'x', encoding='utf-8') as stream:
                        stream.write(VERSION + '\n')
                except OSError:
                    _log.exception('DAM-Updater konnte Startbestätigung nicht schreiben')
        return False

    def _begin_startup_scan(self):
        self.refresh_app_lists(0, operation='startup')
        return False

    def on_navigation_toggled(self, button, mode):
        """Ein einheitlicher Umschalter steuert alle vier Seiten.

        Bei Info wird der vorherige Hauptreiter wirklich abgewählt. Das
        vermeidet doppelte aktive Zustände, verlorene Hover-Effekte und
        das Aufblitzen der zuletzt offenen Seite.
        """
        if not button.get_active():
            # Ein Klick auf den bereits aktiven Toggle darf nicht zu
            # einer Navigation ohne markierten Reiter fuehren. Erst am
            # Ende des GTK-Events (nach allen Gruppen-Callbacks) pruefen.
            GLib.idle_add(self.ensure_navigation_selected)
            return
        self._current_nav_mode = mode
        if mode == 'info':
            self.content_stack.set_visible_child_name('info')
            self.info_button.set_tooltip_text('Zur App-Übersicht zurück')
            if hasattr(self, 'refresh_backup_summary'):
                self.refresh_backup_summary()
        else:
            self._last_main_mode = mode
            self.stack.set_visible_child_name(mode)
            self.content_stack.set_visible_child_name('apps')
            self.info_button.set_tooltip_text('Informationen zu DAM')
            if mode == 'update':
                self._update_tab_visited = True
                self.maybe_start_first_update_check()
        self.apply_mode_theme(mode)

    def ensure_navigation_selected(self):
        """Kein Zustand ohne aktive Navigation, auch bei erneutem Klick."""
        if not any(button.get_active() for button in self.nav_buttons.values()):
            self.nav_buttons[self._current_nav_mode].set_active(True)
        return False

    def toggle_info(self, _button):
        """Der Zurück-Button der Info-Seite nutzt denselben Reitermechanismus."""
        if self._current_nav_mode == 'info':
            self.nav_buttons[self._last_main_mode].set_active(True)
        else:
            self.info_button.set_active(True)

    def create_info_page(self):
        """Dauerhafte Hinweise an einem Ort statt unter jeder App-Liste."""
        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class('dam-info-scroll')
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.add_css_class('dam-info-page')
        box.set_margin_start(36)
        box.set_margin_end(36)
        box.set_margin_top(16)
        box.set_margin_bottom(28)

        heading = Gtk.Label(label='Informationen zu DAM')
        heading.add_css_class('title-1')
        heading.set_xalign(0)
        box.append(heading)
        version = Gtk.Label(label=f'Version {VERSION}')
        version.add_css_class('dim-label')
        version.set_xalign(0)
        box.append(version)

        def section(title, description):
            label = Gtk.Label(label=title)
            label.add_css_class('heading')
            label.set_xalign(0)
            label.set_margin_top(10)
            box.append(label)
            body = Gtk.Label(label=description)
            body.set_xalign(0)
            body.set_wrap(True)
            body.set_selectable(True)
            box.append(body)

        section('Installieren',
                'DAM installiert ausgewählte, unterstützte Apps aus deinen Ubuntu-APT-Quellen. '
                'Bereits installierte Programme lassen sich über „Installierte anzeigen“ einblenden.')
        section('Aktualisieren',
                'Die erste Updateprüfung beginnt beim ersten Öffnen des Reiters „Aktualisieren“. '
                'Danach kannst du über „Nach Updates suchen“ erneut prüfen. '
                'Geprüft werden APT (mit lokal vorhandenen Paketlisten), Snap, Flatpak und '
                'RustDesk über GitHub. Es werden nur bestätigte App-Updates angezeigt.')
        section('Deinstallieren',
                'Nur unterstützte App-Pakete lassen sich entfernen. DAM simuliert die Entfernung '
                'vorher und stoppt, wenn zusätzliche Pakete entfernt würden. Es verwendet '
                'weder „purge“ noch „autoremove“. Vor der Entfernung musst du bestätigen.')
        section('Bedienung',
                'App-Kacheln anklicken, um sie auszuwählen; „Alle auswählen“ markiert alle '
                'sichtbaren, unterstützten Apps. Rechtsklick auf eine App öffnet die Optionen '
                'für Desktop-Verknüpfung und Autostart. Strg+Q beendet DAM.')
        section('DAM aktualisieren',
                'Beim Öffnen von „Aktualisieren“ prüft DAM auch sein offizielles GitHub-Release. '
                'Neue Versionen werden heruntergeladen, geprüft und erst nach einem Neustart aktiviert. '
                'Falls DAM nicht startet, stellt der Updater die vorherige Version wieder her.')
        section('Speicher & Backups',
                'DAM speichert seine Programmversionen bereits getrennt. '
                'Mit „Aktuelle Version sichern“ beim Rechtsklick schützt du eine '
                'Version dauerhaft – ohne eine zweite Kopie anzulegen. '
                'Bereinigung erfolgt ausschließlich auf deine Bestätigung.')
        self.backup_summary = Gtk.Label(label='Gesicherte DAM-Versionen werden geprüft …')
        self.backup_summary.add_css_class('dim-label')
        self.backup_summary.set_xalign(0)
        self.backup_summary.set_wrap(True)
        box.append(self.backup_summary)
        manage = Gtk.Button(label='Backups verwalten / Bereinigen')
        manage.set_halign(Gtk.Align.START)
        manage.connect('clicked', self.open_dam_backups)
        box.append(manage)
        self.backup_notice = Gtk.Label(label='')
        self.backup_notice.add_css_class('dim-label')
        self.backup_notice.set_xalign(0)
        self.backup_notice.set_wrap(True)
        box.append(self.backup_notice)
        self.refresh_backup_summary()
        section('Administratorrechte',
                'Ubuntu fragt bei Paketänderungen nach Administratorrechten. DAM speichert '
                'keine Passwörter. Die gezeigten Versions- und Datumsinformationen können '
                'je nach Paketquelle unvollständig sein.')
        section('Technische Informationen',
                'Fehlerprotokoll: ~/.local/state/dam/dam.log\n'
                'Eigene App-Beschreibungen: ~/DAM/app_beschreibungen.json')
        update_heading = Gtk.Label(label='Letzte Updateprüfung')
        update_heading.add_css_class('heading')
        update_heading.set_xalign(0)
        update_heading.set_margin_top(10)
        box.append(update_heading)
        box.append(self.update_check_info)
        back = Gtk.Button(label='Zurück zu den Apps')
        back.set_halign(Gtk.Align.START)
        back.set_margin_top(16)
        back.connect('clicked', self.toggle_info)
        box.append(back)
        scroll.set_child(box)
        return scroll

    def maybe_start_first_update_check(self):
        """Update-Abfrage erst nach dem ersten echten Besuch starten."""
        if (not self._update_tab_visited or self._first_update_check_done
                or self._initial_loading or self.list_refresh_running
                or not self._catalog_ready):
            return
        self._first_update_check_done = True
        GLib.idle_add(self.check_updates)

    def apply_mode_theme(self, mode):
        """Alle Elemente erhalten dieselbe Akzentfarbe; keine Widgets neu erzeugen."""
        if mode not in ('install', 'update', 'remove', 'info'):
            return
        for node in (self.window, self.main_box):
            for name in ('install', 'update', 'remove', 'info'):
                node.remove_css_class('dam-mode-' + name)
            node.add_css_class('dam-mode-' + mode)

    def add_style(self):
        css = Gtk.CssProvider()
        css.load_from_data(b'''
            .dam-tile {
                border-radius: 12px;
                padding: 12px;
                min-width: 145px;
                min-height: 135px;
                /* Reserve border space in both states: no jumping when selected. */
                border: 2px solid transparent;
            }
            .dam-tile:checked {
                background-color: @accent_bg_color;
                color: @accent_fg_color;
                border-color: @accent_bg_color;
            }
            .dam-tile:checked label {
                color: @accent_fg_color;
            }
            .dam-tile:checked .dim-label {
                color: alpha(@accent_fg_color, 0.90);
            }
            /* Bereits installierte Apps im Installieren-Katalog dezent gruen markieren.
               Die feste Rahmenbreite verhindert, dass die Kacheln beim Auswaehlen springen. */
            .dam-tile.dam-installed {
                background-color: alpha(@success_color, 0.13);
                border-color: alpha(@success_color, 0.50);
            }
            .dam-tile.dam-installed:checked {
                background-color: @accent_bg_color;
                color: @accent_fg_color;
                border-color: @accent_bg_color;
            }
            /* Neutral ohne Auswahl, je nach Reiter gruen, blau oder rot bei Auswahl. */
            /* Gut lesbare, gleichbleibend breite Aktionsbuttons. Die Breite
               des Alle-auswaehlen-Buttons ist in beiden Textzustaenden gleich. */
            button.dam-main-action {
                font-size: 15px;
                font-weight: 700;
                min-height: 48px;
                padding: 8px 17px;
                border-radius: 9px;
            }
            /* Alle vier Navigationsbuttons benutzen in jedem Zustand dieselbe
               Rahmenbreite, Schrift, Innenabstaende und Hoehe. So springt
               beim Umschalten weder die Beschriftung noch die Buttonposition. */
            .dam-navigation button, button.dam-info-toggle {
                min-height: 43px;
                padding: 7px 16px;
                font-size: 15px;
                font-weight: 700;
                border: 1px solid transparent;
                background-color: transparent;
                background-image: none;
                box-shadow: none;
            }
            /* Alle nicht aktiven Reiter nehmen den jeweiligen Fensterfarbton
               an. Hover zeigt nur einen dezenten transparenten Schimmer. */
            .dam-navigation button:not(:checked) {
                background-color: transparent;
                background-image: none;
                box-shadow: none;
                color: @window_fg_color;
                border-color: transparent;
            }
            .dam-navigation button:not(:checked):hover {
                background-color: alpha(@window_fg_color, 0.08);
            }
            /* Trennlinien nehmen nur die bereits reservierte linke
               Rahmen-Pixelspalte ein - ohne die Breite zu veraendern. */
            .dam-navigation button:not(:first-child) {
                border-left-width: 1px;
                border-left-style: solid;
                border-left-color: alpha(@window_fg_color, 0.28);
            }
            button.dam-info-toggle {
                min-width: 43px;
                border-radius: 0 9px 9px 0;
            }
            .dam-navigation button:first-child {
                border-top-right-radius: 0;
                border-bottom-right-radius: 0;
                border-top-left-radius: 9px;
                border-bottom-left-radius: 9px;
            }
            .dam-navigation button:not(:first-child):not(:last-child) {
                border-radius: 0;
            }
            /* Alle drei Suchfelder und der Update-Button nutzen eine Hoehengruppe.
               Die kleinere innere Button-Hoehe vermeidet aufgeblasene Toolbars. */
            searchentry.dam-search-field {
                min-height: 46px;
                padding: 0 9px;
            }
            searchentry.dam-search-field > text {
                min-height: 30px;
                padding-top: 0;
                padding-bottom: 0;
            }
            button.dam-check-updates {
                min-height: 32px;
                padding: 5px 14px;
                font-size: 14px;
                font-weight: 700;
            }
            button.dam-selection-button.dam-has-selection {
                background-color: @accent_bg_color;
                color: @accent_fg_color;
                border-color: @accent_bg_color;
            }
            button.dam-selection-button.dam-has-selection:hover {
                background-color: shade(@accent_bg_color, 1.09);
                color: @accent_fg_color;
            }
            /* GTK zeichnet den nativen Ladekreis selbst mit fluessiger Animation. */
            spinner.dam-loading-spinner {
                min-width: 56px;
                min-height: 56px;
                color: #e95420;
            }
            .dam-loading-panel {
                border-radius: 16px;
                /* Gleiche Aussengroesse; Inhalt um 6 px nach unten schieben. */
                padding: 18px 24px 6px 24px;
                background-color: alpha(@window_bg_color, 0.94);
                border: 1px solid alpha(@window_fg_color, 0.15);
            }
            .dam-small { font-size: 11px; }
            /* Bereichsfarben: dunkler Grundton, dezente Kacheln, kraeftige Auswahl.
               Gleiche Masse und Border-Staerken verhindern Layout-Spruenge. */
            .dam-page, scrolledwindow.dam-app-scroll,
            scrolledwindow.dam-app-scroll > viewport,
            flowbox.dam-app-grid, scrolledwindow.dam-info-scroll,
            scrolledwindow.dam-info-scroll > viewport,
            .dam-info-page { background-color: transparent; }

            /* Deutlichere RGB-Toene, 3x schneller als zuvor.
               Dunkle Werte erhalten die Lesbarkeit von Text und Bedienelementen. */
            @keyframes dam-info-ambient {
                0%   { background-color: #69341d; }
                20%  { background-color: #583078; }
                40%  { background-color: #185778; }
                60%  { background-color: #21624a; }
                80%  { background-color: #74344d; }
                100% { background-color: #69341d; }
            }
            window.dam-mode-info, .dam-root.dam-mode-info,
            .dam-mode-info headerbar {
                color: #fff5ef;
                background-color: #69341d;
                animation-name: dam-info-ambient;
                animation-duration: 15s;
                animation-timing-function: linear;
                animation-iteration-count: infinite;
            }
            /* Gleicher 15-Sekunden-Takt und gleiche Farbstationen wie
               dam-info-ambient; kraeftigere, kontrastreiche Button-Toene. */
            @keyframes dam-info-button-rgb {
                0%   { background-color: #cf6325; border-color: #ffba80; }
                20%  { background-color: #a744ce; border-color: #e2a7ff; }
                40%  { background-color: #197ec2; border-color: #9edcff; }
                60%  { background-color: #279b65; border-color: #98f4bf; }
                80%  { background-color: #c44468; border-color: #ffadc1; }
                100% { background-color: #cf6325; border-color: #ffba80; }
            }
            /* Aktiv: synchron zum Hintergrund animieren, nicht nur orange.
               Hover aendert das RGB-Timing nicht. */
            .dam-mode-info button.dam-info-toggle:checked,
            .dam-mode-info button.dam-info-toggle:checked:hover {
                background-color: #cf6325;
                border: 1px solid #ffba80;
                color: #ffffff;
                box-shadow: inset 0 0 0 1px alpha(#ffffff, 0.22);
                animation-name: dam-info-button-rgb;
                animation-duration: 15s;
                animation-timing-function: linear;
                animation-iteration-count: infinite;
            }
            /* Barrierefreiheit: beide RGB-Animationen gemeinsam anhalten. */
            @media (prefers-reduced-motion: reduce) {
                window.dam-mode-info, .dam-root.dam-mode-info,
                .dam-mode-info headerbar,
                .dam-mode-info button.dam-info-toggle:checked {
                    animation-name: none;
                }
            }

            window.dam-mode-install, .dam-root.dam-mode-install,
            .dam-mode-install headerbar {
                background-color: #242d27;
                color: #eaf6ee;
            }
            .dam-mode-install .dam-tile:not(:checked) {
                background-color: #313e35;
                border-color: transparent;
            }
            .dam-mode-install .dam-tile:checked,
            .dam-mode-install .dam-tile.dam-installed:checked {
                background-color: #367c4d;
                border-color: #79c58b;
                color: #ffffff;
            }
            .dam-mode-install .dam-tile:checked label,
            .dam-mode-install .dam-tile:checked .dim-label { color: #ffffff; }
            .dam-mode-install button.dam-selection-button.dam-has-selection {
                background-color: #367c4d;
                border-color: #79c58b;
                color: #ffffff;
            }
            .dam-mode-install button.dam-selection-button.dam-has-selection:hover {
                background-color: #345f44;
                border-color: #79c58b;
                color: #ffffff;
            }
            .dam-mode-install .dam-navigation button:checked {
                background-color: #345f44;
                color: #ffffff;
                border-color: #79c58b;
            }
            .dam-mode-install .dam-loading-panel {
                background-color: #242d27;
                border-color: #79c58b;
            }
            .dam-mode-install spinner.dam-loading-spinner { color: #79c58b; }

            window.dam-mode-update, .dam-root.dam-mode-update,
            .dam-mode-update headerbar {
                background-color: #242e3a;
                color: #edf6ff;
            }
            .dam-mode-update .dam-tile:not(:checked) {
                background-color: #313f4c;
                border-color: transparent;
            }
            .dam-mode-update .dam-tile:checked,
            .dam-mode-update .dam-tile.dam-installed:checked {
                background-color: #2e70a5;
                border-color: #83bdec;
                color: #ffffff;
            }
            .dam-mode-update .dam-tile:checked label,
            .dam-mode-update .dam-tile:checked .dim-label { color: #ffffff; }
            .dam-mode-update button.dam-selection-button.dam-has-selection {
                background-color: #2e70a5;
                border-color: #83bdec;
                color: #ffffff;
            }
            .dam-mode-update button.dam-selection-button.dam-has-selection:hover {
                background-color: #365f83;
                border-color: #83bdec;
                color: #ffffff;
            }
            .dam-mode-update .dam-navigation button:checked {
                background-color: #365f83;
                color: #ffffff;
                border-color: #83bdec;
            }
            .dam-mode-update .dam-loading-panel {
                background-color: #242e3a;
                border-color: #83bdec;
            }
            .dam-mode-update spinner.dam-loading-spinner { color: #83bdec; }

            window.dam-mode-remove, .dam-root.dam-mode-remove,
            .dam-mode-remove headerbar {
                background-color: #32272a;
                color: #fff0f0;
            }
            .dam-mode-remove .dam-tile:not(:checked) {
                background-color: #443539;
                border-color: transparent;
            }
            .dam-mode-remove .dam-tile:checked,
            .dam-mode-remove .dam-tile.dam-installed:checked {
                background-color: #a34249;
                border-color: #e69aa0;
                color: #ffffff;
            }
            .dam-mode-remove .dam-tile:checked label,
            .dam-mode-remove .dam-tile:checked .dim-label { color: #ffffff; }
            .dam-mode-remove button.dam-selection-button.dam-has-selection {
                background-color: #a34249;
                border-color: #e69aa0;
                color: #ffffff;
            }
            .dam-mode-remove button.dam-selection-button.dam-has-selection:hover {
                background-color: #85474e;
                border-color: #e69aa0;
                color: #ffffff;
            }
            .dam-mode-remove .dam-navigation button:checked {
                background-color: #85474e;
                color: #ffffff;
                border-color: #e69aa0;
            }
            .dam-mode-remove .dam-loading-panel {
                background-color: #32272a;
                border-color: #e69aa0;
            }
            .dam-mode-remove spinner.dam-loading-spinner { color: #e69aa0; }

            .dam-mode-install .dam-tile.dam-installed:not(:checked) {
                background-color: #30543b;
                border-color: #5b9a6c;
            }
        ''')
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def app_context_menu(self, tile, item, status, x, y):
        """Rechtsklickmenü für bereits installierte Anwendungen."""
        pop = Gtk.Popover()
        pop.set_autohide(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.set_margin_top(8)
        content.set_margin_bottom(8)
        content.set_margin_start(8)
        content.set_margin_end(8)
        name = Gtk.Label(label=item['name'])
        name.add_css_class('heading')
        content.append(name)
        source = item.get('desktop_file')
        if source and app_shortcuts.valid_source(source):
            create = Gtk.Button(label='Desktop-Verknüpfung erstellen')
            create.connect('clicked', lambda *_: self.do_shortcut('desktop', item, status, pop))
            content.append(create)
            managed = app_shortcuts.autostart_state(item)
            if managed == 'managed':
                autostart = Gtk.Button(label='Aus Autostart entfernen')
                autostart.connect('clicked', lambda *_: self.do_shortcut('remove_autostart', item, status, pop))
            elif managed == 'foreign':
                autostart = Gtk.Button(label='Bereits im Autostart (extern)')
                autostart.set_sensitive(False)
            else:
                autostart = Gtk.Button(label='Zum Autostart hinzufügen')
                autostart.connect('clicked', lambda *_: self.do_shortcut('autostart', item, status, pop))
            content.append(autostart)
        else:
            reason = Gtk.Label(label='Kein nutzbarer App-Starter vorhanden.')
            reason.add_css_class('dim-label')
            content.append(reason)
        if item.get('package') == 'dam' and (
                item.get('is_installed') or
                os.path.isfile(os.path.expanduser('~/.local/share/dam/current/dam.py'))):
            save = Gtk.Button(label='Aktuelle Version sichern')
            save.connect('clicked', lambda *_: self.pin_current_dam_version(status, pop))
            content.append(save)
            backups = Gtk.Button(label='Backups verwalten / Version wiederherstellen…')
            backups.connect('clicked', lambda *_: (pop.popdown(), self.open_dam_backups()))
            content.append(backups)
        else:
            note = Gtk.Label(label='Programm-Backups folgen in einer späteren Version.')
            note.add_css_class('dim-label')
            note.set_wrap(True)
            content.append(note)
        pop.set_child(content)
        pop.set_parent(tile)
        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rectangle)
        pop.connect('closed', lambda p: p.unparent())
        pop.popup()

    def do_shortcut(self, action, item, status, popover):
        popover.popdown()
        try:
            if action == 'desktop':
                message = app_shortcuts.create_desktop_shortcut(item)
            elif action == 'autostart':
                message = app_shortcuts.add_autostart(item)
            elif action == 'remove_autostart':
                message = app_shortcuts.remove_autostart(item)
            else:
                raise ValueError('Unbekannte Verknüpfungsaktion')
        except (OSError, ValueError, RuntimeError) as exc:
            message = f'Fehler: {exc}'
        status.set_text(message)

    def add_page(self, stack, key, title, apps, verb):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.add_css_class('dam-page')
        page.set_margin_start(20)
        page.set_margin_end(20)
        page.set_margin_bottom(20)
        toolbar = Gtk.Box(spacing=10)
        toolbar.set_size_request(-1, 48)
        toolbar.add_css_class('dam-toolbar')
        search = Gtk.SearchEntry()
        search.add_css_class('dam-search-field')
        search.set_size_request(-1, 48)
        search.set_valign(Gtk.Align.FILL)
        self.search_size_group.add_widget(search)
        search.set_placeholder_text('App suchen …')
        search.set_hexpand(True)
        toolbar.append(search)
        show_installed = None
        if key in ('install', 'remove'):
            # Im Installieren-Tab verstecken wir installierte Programme,
            # im Deinstallieren-Tab geschützte / nicht unterstützte Apps.

            label = 'Installierte anzeigen' if key == 'install' else 'Weitere Apps anzeigen'
            show_installed = Gtk.CheckButton(label=label)
            show_installed.set_tooltip_text(
                'Bereits installierte Apps ein- oder ausblenden' if key == 'install'
                else 'Auch Apps zeigen, deren Deinstallation in DAM derzeit nicht unterstützt wird')
            show_installed.set_active(False)
            toolbar.append(show_installed)
        sort = Gtk.DropDown.new_from_strings(SORTS)
        sort.set_tooltip_text('Sortierung auswählen')
        toolbar.append(sort)
        if key == 'update':
            # Die manuelle Prüfung gehört nach oben neben die Sortierung.
            self.update_check_button = Gtk.Button(label='Nach Updates suchen')
            self.update_check_button.add_css_class('dam-check-updates')
            self.update_check_button.set_size_request(-1, 48)
            self.update_check_button.set_valign(Gtk.Align.FILL)
            self.search_size_group.add_widget(self.update_check_button)
            self.update_check_button.set_tooltip_text('Paketquellen jetzt erneut auf Updates prüfen')
            self.update_check_button.connect('clicked', lambda *_: self.check_updates())
            toolbar.append(self.update_check_button)
        page.append(toolbar)

        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class('dam-app-scroll')
        scroll.set_vexpand(True)
        flow = Gtk.FlowBox()
        flow.add_css_class('dam-app-grid')
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_column_spacing(12)
        flow.set_row_spacing(12)
        flow.set_homogeneous(True)
        flow.set_min_children_per_line(1)
        flow.set_max_children_per_line(7)
        flow.set_valign(Gtk.Align.START)
        flow.set_margin_top(4)
        flow.set_margin_bottom(8)
        rows = {}
        buttons = []
        selection_info = Gtk.Label(label='0 ausgewählt')
        selection_info.add_css_class('dim-label')

        def refresh_count(*_unused):
            selected = sum(button.get_active() for button in buttons)
            selection_info.set_text(f'{selected} ausgewählt')
            selection_button.set_label(f'Auswahl {verb.capitalize()} ({selected})')
            # Die Aktionsfarbe spiegelt immer die Auswahl der Kacheln wider.
            if selected:
                selection_button.add_css_class('dam-has-selection')
            else:
                selection_button.remove_css_class('dam-has-selection')
            # Der Sammelbutton bezieht sich auf sichtbare, anwählbare Kacheln.
            # Damit stimmt sein Text auch nach manueller Auswahl/Abwahl.
            relevant = [row.get_child() for row in rows
                        if row.get_child_visible() and row.get_child().get_sensitive()]
            select_all.set_label('Alle abwählen' if relevant and all(
                tile.get_active() for tile in relevant) else 'Alle auswählen')

        for item in apps:
            tile = Gtk.ToggleButton()
            tile.add_css_class('dam-tile')
            if key == 'install' and item.get('is_installed'):
                tile.add_css_class('dam-installed')
            tile.set_tooltip_text(
                f"{item['name']}\n{item['beschreibung']}\n\nPaket: {item['package'] or 'nicht zugeordnet'}"
                f"\nVersion: {item['version'] or 'unbekannt'}"
                f"\nPaketgröße: {friendly_size(item['size'])}"
                f"\nInstalliert: {friendly_date(item['installed'])}"
                f"\nAktualisiert: {friendly_date(item['updated'])}"
                f"\nStarter geändert: {friendly_date(item['changed'])}")
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            content.set_halign(Gtk.Align.CENTER)
            content.set_valign(Gtk.Align.CENTER)
            icon = Gtk.Image.new_from_gicon(item['icon']) if item['icon'] else Gtk.Image.new_from_icon_name('application-x-executable')
            icon.set_pixel_size(48)
            content.append(icon)
            label = Gtk.Label(label=item['name'])
            label.set_wrap(True)
            label.set_justify(Gtk.Justification.CENTER)
            label.set_max_width_chars(18)
            label.set_lines(2)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            content.append(label)
            caption = (f"Installiert\n{item['version'] or 'Version unbekannt'}" if key == 'install' and item.get('is_installed')
                       else (item['version'] or ('Nicht installiert' if key == 'install' else 'Version unbekannt')))
            detail = Gtk.Label(label=caption)
            detail.add_css_class('dim-label')
            detail.add_css_class('dam-small')
            detail.set_ellipsize(Pango.EllipsizeMode.END)
            detail.set_max_width_chars(19)
            content.append(detail)
            tile.set_child(content)
            if key == 'update':
                item['caption_widget'] = detail
                item['tile_widget'] = tile
                item['update'] = None
            # Rechtsklick, ohne die Mehrfachauswahl der linken Maustaste zu verändern.
            gesture = Gtk.GestureClick.new()
            gesture.set_button(3)
            gesture.connect('pressed', lambda g, n, x, y, t=tile, i=item:
                            self.app_context_menu(t, i, status, x, y))
            tile.add_controller(gesture)
            if key == 'remove':
                if item.get('is_removable'):
                    detail.set_text(item.get('version') or 'Version unbekannt')
                else:
                    detail.set_text('Geschützt / nicht unterstützt')
                    tile.set_sensitive(False)
            if key == 'install':
                if item.get('is_installed'):
                    detail.set_text(f"Installiert\n{item['version'] or 'Version unbekannt'}")
                elif item.get('package') not in apt_install.ALLOWED:
                    tile.set_sensitive(False)
                    detail.set_text('Installation folgt später')
                elif not item.get('apt_candidate'):
                    tile.set_sensitive(False)
                    detail.set_text('Keine APT-Quelle gefunden')
                else:
                    detail.set_text(f"APT: {item['apt_candidate']}")
                item['tile_widget'] = tile
                item['caption_widget'] = detail
            tile.connect('toggled', refresh_count)
            flow.insert(tile, -1)
            rows[tile.get_parent()] = item
            buttons.append(tile)

        def visible(child):
            item = rows[child]
            query = search.get_text().casefold().strip()
            if query not in item['name'].casefold():
                return False
            if key == 'install' and item.get('is_installed') and not show_installed.get_active():
                return False
            if key == 'remove' and not item.get('is_removable') and not show_installed.get_active():
                return False
            return key != 'update' or item.get('update') is not None

        if show_installed is not None:
            def installed_visibility_changed(_button):
                # Unsichtbare Kacheln sollen nicht ausgewählt bleiben.
                if not show_installed.get_active():
                    for row, item in rows.items():
                        hidden = (item.get('is_installed') if key == 'install'
                                  else not item.get('is_removable'))
                        if hidden:
                            row.get_child().set_active(False)
                flow.invalidate_filter()
                refresh_count()
            show_installed.connect('toggled', installed_visibility_changed)

        def compare(a, b):
            x, y = rows[a], rows[b]
            index = sort.get_selected()
            if index in (0, 1):
                result = (x['name'].casefold() > y['name'].casefold()) - (x['name'].casefold() < y['name'].casefold())
                return -result if index == 1 else result
            field = 'size' if index in (2, 3) else ('installed' if index == 4 else ('updated' if index == 5 else 'changed'))
            vx, vy = x[field], y[field]
            if vx is None or vx == '':
                return 1 if vy is not None and vy != '' else 0
            if vy is None or vy == '':
                return -1
            result = (vx > vy) - (vx < vy)
            if index in (3, 4, 5, 6):
                result = -result
            return result or ((x['name'].casefold() > y['name'].casefold()) - (x['name'].casefold() < y['name'].casefold()))

        flow.set_filter_func(visible)
        flow.set_sort_func(compare)
        def on_search(*_unused):
            flow.invalidate_filter()
            refresh_count()
            if key == 'update' and not self.update_check_running:
                self.update_empty_label.set_visible(not any(
                    row.get_child_visible() for row in rows))
                if any(data.get('update') for data in rows.values()):
                    self.update_empty_label.set_text('Keine Treffer für diese Suche.')
        search.connect('search-changed', on_search)
        sort.connect('notify::selected', lambda *_: flow.invalidate_sort())
        scroll.set_child(flow)
        # Ergebnis-, Warte- und Leermeldungen mittig in der App-Fläche zeigen.
        # Der große globale Ladeindikator liegt weiterhin über dem Stack.
        if key == 'update':
            message_overlay = Gtk.Overlay()
            message_overlay.set_vexpand(True)
            message_overlay.set_child(scroll)
            self.update_empty_label = Gtk.Label(label='Noch keine Updateprüfung durchgeführt.')
            self.update_empty_label.add_css_class('dim-label')
            self.update_empty_label.add_css_class('dam-center-message')
            self.update_empty_label.set_halign(Gtk.Align.CENTER)
            self.update_empty_label.set_valign(Gtk.Align.CENTER)
            self.update_empty_label.set_margin_bottom(76)
            self.update_empty_label.set_justify(Gtk.Justification.CENTER)
            self.update_empty_label.set_xalign(0.5)
            self.update_empty_label.set_wrap(True)
            self.update_empty_label.set_max_width_chars(64)
            message_overlay.add_overlay(self.update_empty_label)
            message_overlay.set_measure_overlay(self.update_empty_label, False)
            page.append(message_overlay)
        else:
            page.append(scroll)

        actions = Gtk.Box(spacing=8)
        actions.set_halign(Gtk.Align.CENTER)
        select_all = Gtk.Button(label='Alle auswählen')
        select_all.add_css_class('dam-main-action')
        # Feste Breite: Der Button darf beim Wechsel der Beschriftung nicht springen.
        select_all.set_size_request(190, 48)

        def toggle_all(*_):
            relevant = [row.get_child() for row in rows
                        if row.get_child_visible() and row.get_child().get_sensitive()]
            if not relevant:
                return
            mark = not all(tile.get_active() for tile in relevant)
            for tile in relevant:
                tile.set_active(mark)
            refresh_count()

        select_all.connect('clicked', toggle_all)
        actions.append(select_all)
        selection_button = Gtk.Button(label=f'Auswahl {verb.capitalize()} (0)')
        selection_button.add_css_class('dam-selection-button')
        selection_button.add_css_class('dam-main-action')
        selection_button.set_size_request(285, 48)
        actions.append(selection_button)
        all_button = Gtk.Button(label=f'Alle {verb.capitalize()}')
        all_button.add_css_class('dam-main-action')
        all_button.set_size_request(205, 48)
        actions.append(all_button)
        # Einheitlicher, fester Fussbereich auf allen drei Seiten:
        # Auch unsichtbare Statuslabels reservieren exakt dieselbe Hoehe.
        # Der Update-Reiter hatte zuvor keinen progress_row-Container, weshalb
        # die Aktionsbuttons durch GTK anders positioniert wurden.
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        footer.add_css_class('dam-actions-footer')
        footer.set_valign(Gtk.Align.END)
        # Hinweise ueber den Buttons, Aktionen als unterste Zeile.
        # Kein separater Auswahlzaehler und keine dauerhaften Hinweise.
        # Rueckmeldungen erscheinen in einem gleich hohen Statusbereich.
        status = Gtk.Label(label='')
        status.add_css_class('dim-label')
        status.set_visible(False)
        status.set_ellipsize(Pango.EllipsizeMode.END)
        status.set_single_line_mode(True)
        status.set_hexpand(True)
        status.set_xalign(0.5)
        status.set_justify(Gtk.Justification.CENTER)
        status.connect('notify::label', lambda label, _prop: (
            label.set_visible(bool(label.get_text().strip())),
            label.set_tooltip_text(label.get_text() if label.get_text().strip() else None)))
        progress_row = Gtk.Box(spacing=8)
        progress_row.add_css_class('dam-feedback-row')
        progress_row.set_size_request(-1, 28)
        progress_row.set_halign(Gtk.Align.FILL)
        progress_row.set_valign(Gtk.Align.CENTER)
        progress_content = Gtk.Box(spacing=8)
        progress_content.set_halign(Gtk.Align.CENTER)
        progress_content.set_hexpand(True)
        if key in ('install', 'remove'):
            spinner = Gtk.Spinner()
            spinner.set_size_request(18, 18)
            spinner.set_visible(False)
            progress_content.append(spinner)
            self.operation_spinners[key] = spinner
            self.operation_statuses[key] = status
        progress_content.append(status)
        progress_row.append(progress_content)
        footer.append(progress_row)
        footer.append(actions)
        page.append(footer)

        def execute(_button, all_items=False):
            chosen = ([data for row, data in rows.items()
                       if row.get_child_visible() and row.get_child().get_sensitive()] if all_items
                      else [data for row, data in rows.items()
                            if row.get_child_visible() and row.get_child().get_sensitive()
                            and row.get_child().get_active()])
            if not chosen:
                status.set_text('Keine Apps ausgewählt.')
                return
            if key == 'update':
                if self.update_check_running or self.update_install_running:
                    status.set_text('Bitte warten, bis der laufende Vorgang beendet ist.')
                    return
                selected = [(data['name'], data['update']) for data in chosen if data.get('update')]
                if selected:
                    self.confirm_updates(status, selected)
                else:
                    status.set_text('Keine verfügbaren Updates ausgewählt.')
                return
            if key == 'install':
                if self.install_running or self.update_install_running or self.remove_running:
                    status.set_text('Bitte warten, bis der aktuelle Vorgang beendet ist.')
                    return
                safe = [data for data in chosen if not data.get('is_installed')
                        and data.get('package') in apt_install.ALLOWED and data.get('apt_candidate')]
                if not safe:
                    status.set_text('Keine unterstützten, noch nicht installierten APT-Apps ausgewählt.')
                    return
                self.confirm_install(safe, status)
                return
            if key == 'remove':
                if (self.remove_running or self.install_running or self.update_install_running
                        or self.update_check_running or self.list_refresh_running):
                    status.set_text('Bitte warten, bis die laufende Aktion abgeschlossen ist.')
                    return
                safe = [data for data in chosen if data.get('is_removable')]
                if not safe:
                    status.set_text('Keine unterstützten APT-Apps zur Deinstallation ausgewählt.')
                    return
                self.confirm_remove(safe, status, bool(all_items))
                return
            status.set_text(f'{len(chosen)} Apps zum {verb} vorgemerkt. Testmodus: nichts verändert.')

        refresh_count()
        selection_button.connect('clicked', execute)
        all_button.connect('clicked', lambda b: execute(b, True))
        stack.add_titled(page, key, title)
        self.page_controls[key] = (search, sort, show_installed)
        if key == 'install':
            self.install_status = status
            self.install_select_button = selection_button
            self.install_all_button = all_button
            self.install_select_all = select_all
        if key == 'remove':
            self.remove_status = status
            self.remove_select_button = selection_button
            self.remove_all_button = all_button
            self.remove_select_all = select_all
        if key == 'update':
            self.update_rows = rows
            self.update_flow = flow
            self.update_status = status
            self.update_select_button = selection_button
            self.update_all_button = all_button
            self.update_select_all = select_all
            self.update_selection_info = selection_info

    def confirm_install(self, chosen, status):
        packages = [item['package'] for item in chosen]
        dlg = Adw.MessageDialog.new(
            self.window, f'{len(packages)} Programm(e) installieren?',
            'DAM installiert über die konfigurierten Ubuntu-APT-Quellen:\n'
            + ', '.join(item['name'] for item in chosen)
            + '\n\nAPT kann zusätzlich benötigte Abhängigkeiten installieren. '
              'Die Paketlisten werden dabei nicht automatisch aktualisiert. '
              'Vor der Installation prüft DAM, dass keine Pakete entfernt werden.')
        dlg.add_response('cancel', 'Abbrechen')
        dlg.add_response('install', 'Installieren')
        dlg.set_response_appearance('install', Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response('cancel')
        dlg.set_close_response('cancel')
        dlg.connect('response', lambda _dialog, response:
                    self.install_apt(chosen, status) if response == 'install' else None)
        dlg.present()

    def install_apt(self, chosen, status):
        if self.install_running or self.remove_running:
            return
        self.install_running = True
        self.update_ui_lock()
        for button in (self.install_select_button, self.install_all_button, self.install_select_all):
            button.set_sensitive(False)
        self.start_operation_indicator('install', 'APT-Installationsplan wird geprüft …')

        def worker():
            try:
                versions = apt_install.install([item['package'] for item in chosen],
                                                lambda message: GLib.idle_add(
                                                    self.set_operation_stage, 'install', message))
                GLib.idle_add(self.finish_apt_install, chosen, versions, None, status)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                GLib.idle_add(self.finish_apt_install, chosen, {}, str(exc), status)
        threading.Thread(target=worker, daemon=True).start()

    def finish_apt_install(self, chosen, versions, error, status):
        self.stop_operation_indicator('install')
        self.install_running = False
        self.update_ui_lock()
        for item in chosen:
            version = versions.get(item['package'])
            if version:
                item['version'] = version
                item['is_installed'] = True
                item['caption_widget'].set_text('Installiert\n' + version)
                item['tile_widget'].set_active(False)
                item['tile_widget'].set_sensitive(False)
        if error:
            for button in (self.install_select_button, self.install_all_button, self.install_select_all):
                button.set_sensitive(True)
            status.set_text('Installation nicht abgeschlossen: ' + error[:220])
        else:
            status.set_text(f'{len(versions)} Programm(e) installiert. App-Liste wird aktualisiert …')
            # Den Katalog nach dem erfolgreichen APT-Vorgang live erneuern.
            # Wichtig: Gio/GTK-Widgets dürfen nur im GTK-Hauptthread entstehen.
            self.refresh_app_lists(len(versions))
        return False

    def refresh_app_lists(self, changed_count, operation='install'):
        """Paketdaten im Hintergrund neu laden, ohne DAM zu schließen."""
        if self.list_refresh_running:
            return
        self.list_refresh_running = True
        self._refresh_generation += 1
        generation = self._refresh_generation
        self._list_refresh_started_at = time.monotonic()
        self.set_list_loading(True)
        self.update_ui_lock()

        def worker():
            try:
                candidates = {package: apt_install.candidate(package)
                              for package in apt_install.ALLOWED}
                snapshot = (package_info(), package_dates(),
                            external_package_versions(), custom_descriptions(),
                            candidates)
                GLib.idle_add(self.finish_app_list_refresh, snapshot, changed_count,
                              None, operation, generation)
            except Exception as exc:
                GLib.idle_add(self.finish_app_list_refresh, None, changed_count,
                              str(exc), operation, generation)

        # Dem GTK-Hauptloop einen Frame zum Anzeigen des Ladekreises geben.
        def launch_scan():
            threading.Thread(target=worker, daemon=True).start()
            return False
        GLib.timeout_add(60, launch_scan)

    def finish_app_list_refresh(self, snapshot, changed_count, error,
                                operation='install', generation=None):
        """Ignoriert veraltete/abgebrochene Ergebnisse; Seiten stufenweise neu bauen."""
        if generation is not None and generation != self._refresh_generation:
            return False
        target_status = self.remove_status if operation.startswith('remove') else self.install_status
        action = ('Startprüfung' if operation == 'startup' else
                  'Deinstallation' if operation.startswith('remove') else 'Installation')
        if error:
            self.list_refresh_running = False
            self.set_list_loading(False)
            if operation == 'startup':
                self._initial_loading = False
                target_status.set_text('App-Liste konnte nicht eingelesen werden: ' + error[:160])
            else:
                target_status.set_text(
                    action + ' abgeschlossen/fehlgeschlagen; App-Liste konnte nicht neu geladen werden: '
                    + error[:160])
            self.update_ui_lock()
            return False

        # Keine Reiter ersetzen, solange der Update-Scan auf ihnen arbeitet.
        if self.update_check_running or self.update_install_running:
            GLib.timeout_add(250, self.finish_app_list_refresh, snapshot,
                             changed_count, error, operation, generation)
            return False

        # Kurze Mindestanzeigezeit für sehr schnelle Paketabfragen.
        started = getattr(self, '_list_refresh_started_at', None)
        if started is not None:
            remaining = 0.6 - (time.monotonic() - started)
            if remaining > 0:
                GLib.timeout_add(max(20, int(remaining * 1000)),
                                 self.finish_app_list_refresh, snapshot,
                                 changed_count, error, operation)
                return False
        try:
            installed, available = self.make_app_lists(*snapshot)
            active = self.stack.get_visible_child_name() or 'install'
            preferences = {
                key: (controls[0].get_text(), controls[1].get_selected(),
                      controls[2].get_active() if controls[2] is not None else False)
                for key, controls in self.page_controls.items()
            }
            self.stop_operation_indicator('install')
            self.stop_operation_indicator('remove')
            # Eine Seite pro GTK-Frame neu bauen, damit der native Spinner
            # zwischen zwei Schritten weitergezeichnet werden kann.
            self._refresh_plan = {
                'pages': [
                    ('install', '📦 Installieren', available, 'installieren'),
                    ('update', '🔄 Aktualisieren', installed, 'aktualisieren'),
                    ('remove', '🗑️ Deinstallieren', installed, 'deinstallieren')],
                'index': 0,
                'active': active,
                'preferences': preferences,
                'operation': operation,
                'changed_count': changed_count,
            }
            GLib.timeout_add(35, self._rebuild_refresh_step)
        except Exception as exc:
            _log.exception('App-Liste konnte nicht vorbereitet werden')
            target_status.set_text(action + ': Aktualisierung fehlgeschlagen: ' + str(exc)[:140])
            self._refresh_plan = None
            self.list_refresh_running = False
            self.set_list_loading(False)
            self.update_ui_lock()
        return False

    def _rebuild_refresh_step(self):
        """GTK-Hauptthread: höchstens eine Seite pro Aufruf erzeugen."""
        plan = self._refresh_plan
        if plan is None:
            return False
        operation = plan['operation']
        target_status = self.remove_status if operation.startswith('remove') else self.install_status
        finished = False
        try:
            if plan['index'] < len(plan['pages']):
                key, title, apps, verb = plan['pages'][plan['index']]
                old = self.stack.get_child_by_name(key)
                if old is not None:
                    self.stack.remove(old)
                self.page_controls.pop(key, None)
                self.add_page(self.stack, key, title, apps, verb)
                search, sort, show_installed = self.page_controls[key]
                old_text, old_sort, old_show = plan['preferences'].get(
                    key, ('', 0, False))
                search.set_text(old_text)
                sort.set_selected(old_sort)
                if show_installed is not None:
                    show_installed.set_active(old_show)
                plan['index'] += 1
                GLib.timeout_add(35, self._rebuild_refresh_step)
                return False

            finished = True
            self.stack.set_visible_child_name(plan['active'])
            if operation == 'startup':
                # Kein dauerhafter Start-Hinweis unter den App-Kacheln.
                pass
            elif operation == 'remove_error':
                self.remove_status.set_text(
                    'App-Liste aktualisiert. Deinstallation fehlgeschlagen: '
                    + str(self.last_remove_error or 'Bitte Paketstatus prüfen.')[:180])
            elif operation == 'remove':
                self.remove_status.set_text(
                    f"{plan['changed_count']} Programm(e) deinstalliert. "
                    'App-Liste automatisch aktualisiert!')
            else:
                self.install_status.set_text(
                    f"{plan['changed_count']} Programm(e) installiert. "
                    'App-Liste automatisch aktualisiert!')
        except Exception as exc:
            _log.exception('Fehler beim schrittweisen Neuaufbau der App-Liste')
            target_status.set_text('Aktualisierung fehlgeschlagen: ' + str(exc)[:160])
            finished = True
        finally:
            # Nur nach dem finalen Schritt aufraeumen, nie beim Erzeugen einer Seite.
            if finished:
                self._refresh_plan = None
                self.list_refresh_running = False
                self.apply_mode_theme(self.stack.get_visible_child_name() or 'install')
                self.set_list_loading(False)
                self._initial_loading = False
                self._catalog_ready = True
                self.update_ui_lock()
                # Kein ungefragter Update-Scan beim Programmstart.
                # Nur nach einem Besuch von Aktualisieren neu prüfen.
                if self.stack.get_visible_child_name() == 'update':
                    if not self._first_update_check_done:
                        self.maybe_start_first_update_check()
                    elif operation != 'remove_error' and operation != 'startup':
                        GLib.idle_add(self.check_updates)
        return False

    def confirm_remove(self, chosen, status, bulk=False):
        """APT-Plan im Hintergrund prüfen, bevor überhaupt eine Bestätigung erscheint."""
        packages = list(dict.fromkeys(item['package'] for item in chosen))
        if not packages or self.remove_running:
            return
        self.remove_running = True
        self.update_ui_lock()
        for button in (self.remove_select_button, self.remove_all_button, self.remove_select_all):
            button.set_sensitive(False)
        self.start_operation_indicator('remove', 'APT prüft den Entfernungsplan …')

        def worker():
            try:
                result = apt_remove.simulate(packages)
                GLib.idle_add(self.finish_remove_preview, packages, chosen, status, bulk, result, None)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                GLib.idle_add(self.finish_remove_preview, packages, chosen, status, bulk, None, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def finish_remove_preview(self, packages, chosen, status, bulk, plan, error):
        self.stop_operation_indicator('remove')
        if error:
            self.remove_running = False
            self.update_ui_lock()
            for button in (self.remove_select_button, self.remove_all_button, self.remove_select_all):
                button.set_sensitive(True)
            status.set_text('Deinstallation gestoppt: ' + error[:240])
            return False
        if plan != set(packages):
            self.remove_running = False
            self.update_ui_lock()
            for button in (self.remove_select_button, self.remove_all_button, self.remove_select_all):
                button.set_sensitive(True)
            status.set_text('Deinstallation gestoppt: APT-Plan stimmt nicht mit der Auswahl überein.')
            return False
        names = ', '.join(dict.fromkeys(item['name'] for item in chosen))
        extra = ('\n\nAchtung: Eine bestehende RustDesk-Fernverbindung kann abbrechen.'
                 if 'rustdesk' in packages else '')
        dlg = Adw.MessageDialog.new(
            self.window, f'{len(packages)} App(s) deinstallieren?',
            'APT wird genau folgende Paket(e) entfernen:\n' + ', '.join(packages)
            + '\n\nApps: ' + names
            + '\n\nWeitere Paketentfernungen sind nicht erlaubt. '
              'DAM verwendet weder purge noch autoremove; Benutzerdateien werden von DAM nicht gelöscht.'
            + extra)
        dlg.add_response('cancel', 'Abbrechen')
        dlg.add_response('remove', 'Deinstallieren')
        dlg.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response('cancel')
        dlg.set_close_response('cancel')

        def on_response(_dlg, response):
            if response == 'remove':
                if bulk and len(packages) > 1:
                    self.confirm_bulk_remove(packages, status)
                else:
                    self.start_remove(packages, status)
            else:
                self.release_remove_buttons()
                status.set_text('Deinstallation abgebrochen. Keine Änderungen vorgenommen.')
        dlg.connect('response', on_response)
        dlg.present()
        return False

    def confirm_bulk_remove(self, packages, status):
        """Eine zusätzliche Bestätigung für 'Alle deinstallieren'."""
        dlg = Adw.MessageDialog.new(
            self.window, 'ALLE ausgewählten Apps entfernen?',
            f'Du bist dabei, {len(packages)} Programme auf einmal zu entfernen. '
            'Dieser Vorgang kann laufende Programme und Fernzugriffe unterbrechen. '
            'Bist du sicher?')
        dlg.add_response('cancel', 'Abbrechen')
        dlg.add_response('remove', 'Ja, alle deinstallieren')
        dlg.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response('cancel')
        dlg.set_close_response('cancel')
        dlg.connect('response', lambda _dlg, response:
                    self.start_remove(packages, status) if response == 'remove' else
                    (self.release_remove_buttons(), status.set_text('Deinstallation abgebrochen.')))
        dlg.present()

    def release_remove_buttons(self):
        self.remove_running = False
        self.update_ui_lock()
        for button in (self.remove_select_button, self.remove_all_button, self.remove_select_all):
            button.set_sensitive(True)

    def start_remove(self, packages, status):
        """APT-Arbeit im Hintergrund, Abschluss zwingend zur GTK-Schleife melden."""
        self._remove_finish_handled = False
        self._remove_worker_finished_at = None
        self.start_operation_indicator('remove', 'Entfernung wird vorbereitet …')
        _log.info('Deinstallation gestartet: %s', ', '.join(packages))

        def worker():
            removed = []
            error = None
            try:
                removed = apt_remove.remove(
                    packages, lambda message: GLib.idle_add(
                        self.set_operation_stage, 'remove', message))
                _log.info('Paketoperation beendet: %s', ', '.join(packages))
            except BaseException as exc:
                error = f'{type(exc).__name__}: {exc}'
                _log.exception('Deinstallationsworker fehlgeschlagen')
            finally:
                try:
                    GLib.idle_add(self.finish_remove, removed, status, error)
                    _log.info('Abschlussmeldung an GTK gesendet')
                except BaseException:
                    _log.exception('GTK-Abschlussmeldung konnte nicht übergeben werden')
                self._remove_worker_finished_at = time.monotonic()

        thread = threading.Thread(target=worker, daemon=True, name='dam-remove-worker')
        self._remove_worker = thread
        thread.start()
        GLib.timeout_add_seconds(2, self.watch_remove_completion, status)

    def watch_remove_completion(self, status):
        """Erkennt fehlende GTK-Abschlussrückmeldungen nach Worker-Ende."""
        if self._remove_finish_handled or not self.remove_running:
            return False
        finished_at = self._remove_worker_finished_at
        worker = self._remove_worker
        if worker is not None and not worker.is_alive() and finished_at is not None:
            if time.monotonic() - finished_at > 4:
                _log.error('Worker beendet, aber GTK-Abschluss nach 4 Sekunden nicht verarbeitet')
                self._remove_finish_handled = True
                self.stop_operation_indicator('remove')
                self.release_remove_buttons()
                status.set_text('DAM-Fehler bei der Abschlussmeldung. Paketstatus wird neu geprüft. '
                                'Details: ~/.local/state/dam/dam.log')
                self.refresh_app_lists(0, operation='remove_error')
                return False
        return True

    def finish_remove(self, removed, status, error):
        self._remove_finish_handled = True
        _log.info('GTK-Abschluss empfangen: erfolgreich=%s, Fehler=%s',
                  bool(not error), error or '-')
        try:
            self.stop_operation_indicator('remove')
            self.release_remove_buttons()
            if error:
                self.last_remove_error = error
                status.set_text('Deinstallation nicht abgeschlossen: ' + error[:260])
                # APT kann vor dem Fehler teilweise erfolgreich gewesen sein.
                self.refresh_app_lists(0, operation='remove_error')
            else:
                self.last_remove_error = None
                status.set_text(f'{len(removed)} Programm(e) deinstalliert. Aktualisiere App-Liste …')
                self.refresh_app_lists(len(removed), operation='remove')
        except BaseException as exc:
            _log.exception('Fehler beim GTK-Abschluss')
            self.stop_operation_indicator('remove')
            self.remove_running = False
            self.update_ui_lock()
            status.set_text('Fehler bei der Abschlussverarbeitung: ' + str(exc)[:140]
                            + ' – Protokoll: ~/.local/state/dam/dam.log')
        return False

    def refresh_backup_summary(self):
        """Info-Seite zeigt nur mögliche Einsparungen, nie automatische Löschung."""
        if not hasattr(self, 'backup_summary'):
            return
        try:
            versions = dam_updater.stored_versions()
            possible = sum(row['size_bytes'] for row in versions if row['deletable'])
            self.backup_summary.set_text(
                f"{len(versions)} DAM-Version(en) gespeichert · "
                f"{self._backup_size(possible)} freiwillig freigebbar.")
            if possible >= 250 * 1024 * 1024:
                self.backup_notice.set_text(
                    f"Hinweis: Durch das Aufräumen älterer Versionen könntest du "
                    f"{self._backup_size(possible)} sparen. Es wird nichts automatisch gelöscht.")
            else:
                self.backup_notice.set_text('')
        except (OSError, ValueError, dam_updater.UpdateError) as exc:
            self.backup_summary.set_text('Backup-Übersicht konnte nicht geladen werden: ' + str(exc)[:150])
            self.backup_notice.set_text('')

    @staticmethod
    def _backup_size(count):
        if count >= 1024 * 1024 * 1024:
            return f'{count / (1024 ** 3):.2f} GB'
        if count >= 1024 * 1024:
            return f'{count / (1024 ** 2):.1f} MB'
        return f'{count / 1024:.1f} KB'

    def pin_current_dam_version(self, status, popover):
        """Rechtsklick sichert die aktuelle Versionskopie ohne Speicherduplikat."""
        popover.popdown()
        try:
            current = dam_updater._current_version(dam_updater.data_dir())
            dam_updater.protect_version(current, True)
            status.set_text(f'DAM {current} als dauerhaftes Backup geschützt.')
            self.refresh_backup_summary()
        except (OSError, ValueError, dam_updater.UpdateError) as exc:
            status.set_text('Sicherung fehlgeschlagen: ' + str(exc)[:180])

    def open_dam_backups(self, *_):
        """Dialog für gezielte Versionswahl, Schutz und bewusste Bereinigung."""
        try:
            dam_updater.stored_versions()
        except (OSError, ValueError, dam_updater.UpdateError) as exc:
            dlg = Adw.MessageDialog.new(self.window, 'Sicherungen nicht verfügbar', str(exc)[:240])
            dlg.add_response('ok', 'OK')
            dlg.present()
            return
        window = Gtk.Window(title='DAM – Speicher & Backups')
        window.set_transient_for(self.window)
        window.set_modal(True)
        window.set_default_size(690, 535)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel.set_margin_start(20)
        panel.set_margin_end(20)
        panel.set_margin_top(20)
        panel.set_margin_bottom(20)

        title = Gtk.Label(label='Gesicherte DAM-Versionen')
        title.add_css_class('title-2')
        title.set_xalign(0)
        panel.append(title)
        description = Gtk.Label(
            label='Die aktive und die letzte Rückfallversion sind immer geschützt. '
                  'Weitere Versionen kannst du dauerhaft behalten, wiederherstellen '
                  'oder gezielt zur Bereinigung auswählen.')
        description.set_xalign(0)
        description.set_wrap(True)
        panel.append(description)
        summary = Gtk.Label()
        summary.add_css_class('dim-label')
        summary.set_xalign(0)
        panel.append(summary)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        entries = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll.set_child(entries)
        panel.append(scroll)

        selection_status = Gtk.Label(label='Keine Sicherung ausgewählt.')
        selection_status.set_xalign(0)
        selection_status.add_css_class('dim-label')
        panel.append(selection_status)
        message = Gtk.Label(label='')
        message.set_xalign(0)
        message.set_wrap(True)
        message.add_css_class('dim-label')
        panel.append(message)

        controls = Gtk.Box(spacing=8)
        all_button = Gtk.Button(label='Ältere auswählen')
        controls.append(all_button)
        delete_button = Gtk.Button(label='Ausgewählte löschen')
        delete_button.add_css_class('destructive-action')
        delete_button.set_sensitive(False)
        controls.append(delete_button)
        close_button = Gtk.Button(label='Schließen')
        close_button.connect('clicked', lambda *_: window.close())
        controls.append(close_button)
        panel.append(controls)
        window.set_child(panel)

        selected = set()
        visible_rows = []
        checkboxes = {}

        def update_selection():
            eligible = {r['version']: r for r in visible_rows if r['deletable']}
            selected.intersection_update(eligible)
            total = sum(eligible[v]['size_bytes'] for v in selected)
            selection_status.set_text(
                f"{len(selected)} Version(en) ausgewählt · "
                f"{self._backup_size(total)} freigebbar")
            delete_button.set_sensitive(bool(selected))

        def on_check(check, version):
            if check.get_active():
                selected.add(version)
            else:
                selected.discard(version)
            update_selection()

        def refresh():
            nonlocal visible_rows
            try:
                visible_rows = dam_updater.stored_versions()
            except (OSError, ValueError, dam_updater.UpdateError) as exc:
                message.set_text('Fehler beim Lesen: ' + str(exc)[:170])
                return
            while child := entries.get_first_child():
                entries.remove(child)
            checkboxes.clear()
            reclaimable = sum(x['size_bytes'] for x in visible_rows if x['deletable'])
            summary.set_text(
                f"{len(visible_rows)} Version(en) vorhanden · "
                f"{self._backup_size(reclaimable)} bereinigbar · "
                'kein automatisches Löschen')
            for backup in visible_rows:
                version = backup['version']
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                row.set_margin_top(5)
                row.set_margin_bottom(5)
                check = Gtk.CheckButton()
                check.set_sensitive(backup['deletable'])
                check.set_active(version in selected and backup['deletable'])
                check.connect('toggled', on_check, version)
                row.append(check)
                checkboxes[version] = check

                state = ('Aktiv' if backup['active'] else
                         'Letzte Rückfallversion' if backup['rollback'] else
                         'Dauerhaft gesichert' if backup['pinned'] else
                         'Ältere Version')
                name = Gtk.Label(
                    label=f"v{version} · {self._backup_size(backup['size_bytes'])}\n{state}")
                name.set_xalign(0)
                name.set_hexpand(True)
                row.append(name)
                protect = Gtk.Button(
                    label='Schutz aufheben' if backup['pinned'] else 'Behalten')
                if backup['active'] or backup['rollback']:
                    protect.set_tooltip_text('Version bleibt unabhängig davon geschützt')
                protect.connect('clicked', lambda _btn, v=version, mark=not backup['pinned']:
                                on_protect(v, mark))
                row.append(protect)

                restore = Gtk.Button(label='Wiederherstellen')
                restore.set_sensitive(backup['restorable'])
                if backup['active']:
                    restore.set_tooltip_text('Diese Version läuft bereits')
                elif not backup['restorable']:
                    restore.set_tooltip_text('Alte Migration ohne gesicherten Neustart nicht wiederherstellbar')
                restore.connect('clicked', lambda _btn, v=version: self.confirm_dam_restore(v, window))
                row.append(restore)
                entries.append(row)
                entries.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            update_selection()
            self.refresh_backup_summary()

        def on_protect(version, mark):
            try:
                dam_updater.protect_version(version, mark)
                message.set_text(
                    f'DAM v{version} ' +
                    ('wird dauerhaft behalten.' if mark else 'ist nicht mehr zusätzlich fixiert.'))
                refresh()
            except (OSError, ValueError, dam_updater.UpdateError) as exc:
                message.set_text('Schutzänderung fehlgeschlagen: ' + str(exc)[:180])

        def select_older(*_):
            candidates = [r['version'] for r in visible_rows if r['deletable']]
            if candidates and all(v in selected for v in candidates):
                selected.clear()
            else:
                selected.update(candidates)
            for version, check in checkboxes.items():
                check.set_active(version in selected)
            update_selection()

        def confirm_cleanup(*_):
            eligible = {r['version']: r for r in dam_updater.stored_versions()
                        if r['deletable']}
            target = sorted(v for v in selected if v in eligible)
            if not target:
                message.set_text('Keine löschbaren Versionen ausgewählt.')
                refresh()
                return
            total = sum(eligible[v]['size_bytes'] for v in target)
            dlg = Adw.MessageDialog.new(
                window, f'{len(target)} DAM-Version(en) endgültig löschen?',
                f"Ausgewählt: {', '.join('v' + v for v in target)}\n"
                f"Mögliche Ersparnis: {self._backup_size(total)}.\n\n"
                'Aktive, letzte und dauerhaft geschützte Versionen bleiben erhalten.')
            dlg.add_response('cancel', 'Abbrechen')
            dlg.add_response('delete', 'Endgültig löschen')
            dlg.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
            dlg.set_default_response('cancel')
            dlg.set_close_response('cancel')

            def on_response(_dlg, response):
                if response != 'delete':
                    return
                try:
                    freed = dam_updater.delete_stored_versions(target)
                    selected.difference_update(target)
                    message.set_text(
                        f'{len(target)} ältere Version(en) gelöscht · '
                        f'{self._backup_size(freed)} freigegeben.')
                except (OSError, ValueError, dam_updater.UpdateError) as exc:
                    message.set_text('Bereinigung gestoppt: ' + str(exc)[:190])
                refresh()

            dlg.connect('response', on_response)
            dlg.present()

        all_button.connect('clicked', select_older)
        delete_button.connect('clicked', confirm_cleanup)
        refresh()
        window.present()

    def confirm_dam_restore(self, version, parent):
        """Einzelne gesicherte Version bewusst mit Rollback-Schutz aktivieren."""
        if any((self.update_check_running, self.update_install_running,
                self.install_running, self.remove_running, self.list_refresh_running)):
            return
        try:
            dam_updater.validate_restoration(version)
        except (OSError, ValueError, dam_updater.UpdateError) as exc:
            dlg = Adw.MessageDialog.new(parent, 'Wiederherstellung nicht möglich', str(exc)[:220])
            dlg.add_response('ok', 'OK')
            dlg.present()
            return
        dlg = Adw.MessageDialog.new(
            parent, f'DAM v{version} wiederherstellen?',
            'DAM wird beendet und mit der ausgewählten Version neu gestartet. '
            'Die bisher aktive Version bleibt als Rückfallversion erhalten. '
            'Persönliche Einstellungen werden nicht verändert.')
        dlg.add_response('cancel', 'Abbrechen')
        dlg.add_response('restore', 'Wiederherstellen')
        dlg.set_response_appearance('restore', Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response('cancel')
        dlg.set_close_response('cancel')

        def on_response(_dlg, answer):
            if answer == 'restore':
                parent.close()
                self._run_dam_updater('restore', version)

        dlg.connect('response', on_response)
        dlg.present()

    def confirm_dam_rollback(self, *_):
        """Bewusste manuelle Rückkehr zur letzten funktionierenden Version."""
        if any((self.update_check_running, self.update_install_running,
                self.install_running, self.remove_running, self.list_refresh_running)):
            return
        dlg = Adw.MessageDialog.new(
            self.window, 'Vorherige DAM-Version wiederherstellen?',
            'DAM wird beendet und danach mit der letzten Version neu gestartet. '
            'Deine persönlichen Einstellungen bleiben erhalten.')
        dlg.add_response('cancel', 'Abbrechen')
        dlg.add_response('rollback', 'Wiederherstellen')
        dlg.set_response_appearance('rollback', Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response('cancel')
        dlg.set_close_response('cancel')
        dlg.connect('response', lambda _dlg, response:
                    self._run_dam_updater('rollback') if response == 'rollback' else None)
        dlg.present()

    def _run_dam_updater(self, mode, version=None):
        """Watchdog bleibt unabhängig vom beendeten GTK-Prozess aktiv."""
        try:
            executable = os.path.realpath(dam_updater.__file__)
            args = ['/usr/bin/python3', executable, mode, str(os.getpid())]
            if version is not None:
                args.append(version)
            subprocess.Popen(args, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
        except (OSError, ValueError) as exc:
            self.update_status.set_text('DAM-Neustart fehlgeschlagen: ' + str(exc)[:140])
            return
        GLib.timeout_add(250, self._close_for_update)

    def _close_for_update(self):
        self.quit()
        return False

    def check_updates(self):
        """APT aus lokalem Cache, Snap/Flatpak und RustDesk aus GitHub prüfen."""
        if (self._initial_loading or self.list_refresh_running or
                self.update_check_running or self.update_install_running or self.remove_running):
            return False
        self.update_check_running = True
        self._update_scan_generation += 1
        generation = self._update_scan_generation
        cancel_event = threading.Event()
        self._update_cancel_event = cancel_event
        self.apply_mode_theme('update')
        self.set_list_loading(True, 'Updates werden geprüft …')
        self.update_ui_lock()
        self.update_check_button.set_sensitive(False)
        self.update_select_button.set_sensitive(False)
        self.update_all_button.set_sensitive(False)
        self.update_check_info.set_text('Suche nach Updates … (APT, Snap, Flatpak, GitHub/DAM)')
        # Die einheitliche zentrale Ladeflaeche zeigt die Meldung bereits.
        # Keine zweite, versetzt liegende Beschriftung darunter einblenden.
        self.update_empty_label.set_visible(False)
        self.update_empty_label.set_text('Updates werden geprüft …')
        for item in self.update_rows.values():
            item['update'] = None
            item['tile_widget'].set_active(False)
        self.update_flow.invalidate_filter()
        self.update_selection_info.set_text('0 ausgewählt')

        def worker():
            try:
                records, errors, checked = package_updates.probe_updates(cancel_event=cancel_event)
            except package_updates.UpdateScanCancelled:
                return
            except Exception:
                records, errors, checked = [], ['Paketprüfung unerwartet fehlgeschlagen'], 0
            if cancel_event.is_set():
                return
            release = None
            installed = None
            try:
                installed = rustdesk_update.installed_version()
                if installed:
                    release = rustdesk_update.fetch_latest()
                    if rustdesk_update.is_newer(installed, release.version):
                        # GitHub-RustDesk ist die Quelle für DEB-Installationen.
                        records = [r for r in records if r.identifier.casefold() != 'rustdesk']
                        records.append(package_updates.UpdateRecord(
                            'github', 'rustdesk', installed, release.version))
                    checked += 1
            except Exception as exc:
                errors.append(f'GitHub/RustDesk: {str(exc)[:100]}')
            dam_release = None
            if not cancel_event.is_set():
                try:
                    dam_release = dam_updater.check_latest(VERSION)
                    if dam_release:
                        records.append(package_updates.UpdateRecord(
                            'dam', 'dam', VERSION, dam_release.version))
                    checked += 1
                except Exception as exc:
                    errors.append('DAM/GitHub: ' + str(exc)[:100])
            if not cancel_event.is_set():
                GLib.idle_add(self.finish_update_check, records, errors, checked,
                              release, generation, dam_release)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def finish_update_check(self, records, errors, checked, release, generation=None, dam_release=None):
        """Nur aktuelle Scan-Ergebnisse anzeigen, nie abgebrochene Ergebnisse."""
        if generation is not None and generation != self._update_scan_generation:
            return False
        self.update_check_running = False
        self._update_cancel_event = None
        self.set_list_loading(False)
        self.update_ui_lock()
        self.update_check_button.set_sensitive(True)
        self.rustdesk_release = release
        self.dam_release = dam_release
        mapped = package_updates.updates_for_apps(records, list(self.update_rows.values()))
        if dam_release:
            mapped['dam'] = package_updates.UpdateRecord(
                'dam', 'dam', VERSION, dam_release.version)
        # RustDesk auch dann zuordnen, wenn Desktop-Starter keinen Paketnamen hat.
        github = next((r for r in records if r.source == 'github' and r.identifier == 'rustdesk'), None)
        if github:
            for item in self.update_rows.values():
                if item['name'].casefold() == 'rustdesk':
                    mapped['rustdesk'] = github
                    break
        self.update_records = mapped
        for item in self.update_rows.values():
            record = mapped.get(item['name'].casefold())
            item['update'] = record
            caption = item['caption_widget']
            if record:
                caption.set_text(f'{record.installed} → {record.available}')
                item['tile_widget'].set_tooltip_text(
                    f"{item['name']}\n{item['beschreibung']}\n\n"
                    f"Updatequelle: {record.source.upper()}\n"
                    f"Installiert: {record.installed}\nVerfügbar: {record.available}")
            else:
                item['tile_widget'].set_active(False)
                caption.set_text(item['version'] or 'Version unbekannt')
        self.update_flow.invalidate_filter()
        self.update_selection_info.set_text('0 ausgewählt')
        self.update_select_all.set_label('Alle auswählen')
        count = sum(1 for item in self.update_rows.values() if item['update'])
        self.update_select_button.set_sensitive(count > 0)
        self.update_all_button.set_sensitive(count > 0)
        self.update_select_all.set_sensitive(count > 0)
        self.update_empty_label.set_visible(count == 0)
        if count:
            self.update_check_info.set_text(f'{count} App-Update(s) verfügbar')
            self.update_status.set_text('')
        elif not checked:
            self.update_check_info.set_text('Keine Updatequelle konnte geprüft werden')
            self.update_empty_label.set_text('Updateprüfung nicht möglich. Bitte erneut versuchen.')
            self.update_status.set_text('')
        else:
            self.update_check_info.set_text('Keine App-Updates gefunden')
            self.update_empty_label.set_text('Alle geprüften Apps sind aktuell! ✅' if not errors
                                             else 'Keine Updates ermittelt – Prüfung teilweise fehlgeschlagen.')
            self.update_status.set_text('')
        if errors:
            details = '; '.join(errors)
            self.update_check_info.set_tooltip_text(details)
            # Fehlerquelle im sichtbaren Status zeigen – nicht nur im Hover-Tooltip.
            self.update_status.set_text('Prüfung teilweise fehlgeschlagen: ' + details[:280])
        else:
            self.update_check_info.set_tooltip_text(None)
        return False

    def confirm_updates(self, status, selected):
        if self.update_check_running or self.update_install_running:
            return
        names = ', '.join(name for name, _rec in selected[:6])
        if len(selected) > 6:
            names += f' … (+{len(selected) - 6})'
        extra = ('\n\nAchtung: Eine RustDesk-Fernverbindung kann abbrechen. '
                 'Bitte direkt vor Ort aktualisieren.'
                 if any(rec.identifier == 'rustdesk' for _, rec in selected) else '')
        if any(rec.source == 'dam' for _, rec in selected):
            extra += ('\n\nDAM wird nach dem erfolgreichen Update automatisch '
                      'geschlossen und neu gestartet. Die Vorversion bleibt erhalten.')
        dlg = Adw.MessageDialog.new(
            self.window, f'{len(selected)} App(s) aktualisieren?',
            f'{names}\n\nDAM installiert nur die angezeigten Updates. '
            'Ubuntu kann dafür Administratorrechte anfordern.' + extra)
        dlg.add_response('cancel', 'Abbrechen')
        dlg.add_response('install', 'Updates installieren')
        dlg.set_response_appearance('install', Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response('cancel')
        dlg.set_close_response('cancel')
        dlg.connect('response', lambda _dlg, response:
                    self.install_updates(status, selected) if response == 'install' else None)
        dlg.present()

    def install_updates(self, status, selected):
        if self.update_install_running:
            return
        self.update_install_running = True
        self.update_ui_lock()
        self.update_check_button.set_sensitive(False)
        self.update_select_button.set_sensitive(False)
        self.update_all_button.set_sensitive(False)

        def report(message):
            GLib.idle_add(status.set_text, message)

        def worker():
            completed = []
            errors = []
            staged_dam = None
            # DAM muss als letztes aktualisiert werden, da ein Neustart folgt.
            selected_ordered = sorted(selected, key=lambda item: item[1].source == 'dam')
            for index, (name, record) in enumerate(selected_ordered, 1):
                report(f'{index}/{len(selected)}: {name} wird aktualisiert …')
                try:
                    if record.source == 'dam':
                        if not self.dam_release or record.available != self.dam_release.version:
                            raise RuntimeError('DAM-Release ist nicht mehr gültig')
                        dam_updater.stage(self.dam_release)
                        staged_dam = self.dam_release.version
                    elif record.source == 'github':
                        if not self.rustdesk_release or record.identifier != 'rustdesk':
                            raise RuntimeError('Keine gültigen RustDesk-Release-Daten vorhanden')
                        rustdesk_update.install(self.rustdesk_release, report)
                    else:
                        package_updates.do_update(record)
                    completed.append(name)
                except Exception as exc:
                    errors.append(f'{name}: {str(exc)[:250]}')
                    # Keine endlose Kette fehlerhafter Anmeldedialoge.
                    break
            GLib.idle_add(self.finish_updates, status, completed, errors, staged_dam)

        threading.Thread(target=worker, daemon=True).start()

    def finish_updates(self, status, completed, errors, staged_dam=None):
        self.update_install_running = False
        self.update_ui_lock()
        self.update_check_button.set_sensitive(True)
        if errors:
            status.set_text(f'{len(completed)} aktualisiert. Fehler: {errors[0]}')
        else:
            status.set_text(f'{len(completed)} App(s) erfolgreich aktualisiert!')
        if staged_dam and not errors:
            status.set_text('DAM wurde geprüft und wird neu gestartet …')
            self._run_dam_updater('activate', staged_dam)
            return False
        # Neu scannen, damit erfolgreich aktualisierte Kacheln verschwinden.
        # Status bleibt zunächst sichtbar, während die Prüfung läuft.
        GLib.timeout_add(1400, self.check_updates)
        return False


if __name__ == '__main__':
    DAM().run()

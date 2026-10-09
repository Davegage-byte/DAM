# DAM

**DAM** ist ein grafischer App-Manager für Ubuntu mit nativer GTK-4/Libadwaita-Oberfläche.

## Funktionen (lokaler Entwicklungsstand v0.5.25)

- Anwendungen installieren, aktualisieren und deinstallieren
- Kachelansicht mit Suche, Mehrfachauswahl und App-Informationen
- Update-Erkennung über APT, Snap, Flatpak und RustDesk/GitHub
- Sichere APT-Installation und -Deinstallation ausgewählter Apps
- Desktop-Verknüpfungen und Autostart über das Kontextmenü
- Deutsche Benutzeroberfläche, getrennte Farbschemata und animierte Info-Seite

**Status:** Aktuell lokal entwickelte Anwendung. Der Quellcode wird im nächsten Schritt übertragen; dieses Repository enthält bis dahin noch keine lauffähige DAM-Version.

## Geplanter Aufbau

- Quellcode, Tests, Installationsskript und App-Symbole in diesem Repository
- Persönliche App-Sammlung getrennt im Repository `DAM-AppList` (später)
- Versionspakete und Selbstupdates über GitHub Releases (später)

## Sicherheit

Für Paketänderungen nutzt DAM die Ubuntu-Rechteverwaltung. Es werden keine Administratorpasswörter im Repository gespeichert. Vor dem Veröffentlichen eines Releases müssen Quellcode und Installationsskript geprüft und die Aktualisierung getestet werden.

**Hinweis zu privaten Repositories:** Eine spätere automatische Updateprüfung benötigt für private Releases eine autorisierte GitHub-Verbindung. Das ist noch nicht eingerichtet.

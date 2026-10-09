# DAM

**DAM** ist ein grafischer App-Manager für Ubuntu (GTK 4 / Libadwaita).

## Stand: v0.6.1 – Selbstupdate-Praxistest

- Apps installieren, aktualisieren und deinstallieren (unterstützte Quellen)
- GTK-Kacheln, Suche, Auswahl, Info-Reiter und deutsche Oberfläche
- DAM-Selbstupdate über stabile öffentliche GitHub-Releases
- SHA-256-Prüfung mit dem offiziellen Release-Digest, striktes ZIP-Dateischema, Versions- und Python-Syntaxprüfung
- Versionierte, benutzerlokale Installationen mit stabilem Launcher
- Automatische Wiederherstellung der Vorversion, wenn DAM nach dem Update nicht erfolgreich startet
- Manuelles Rollback auf der Info-Seite (nach dem ersten erfolgreichen Selbstupdate)

**Wichtig:** v0.6.0 wurde unter Ubuntu erfolgreich über den neuen Launcher gestartet. v0.6.1 ist das erste Test-Release für die automatische Aktualisierung; eine Prüfung auf dem echten Ubuntu-Desktop steht noch aus. Der erste Einstieg erfolgt einmalig über `install.sh` aus dem Bootstrap-Paket.

### Lokale Installation

Das Bootstrap-Paket `DAM_v0.6.0.zip` entpacken und im entpackten Ordner `bash install.sh` ausführen. Die alte Installation in `~/DAM` und eigene App-Beschreibungen bleiben bestehen.

Danach: Start über das Anwendungsmenü; der stabile Launcher liegt in `~/.local/bin/dam-launcher`. Die aktuelle Programmversion liegt unter `~/.local/share/dam/current`.

### Releases

Nur bewusst freigegebene stabile Tags `vX.Y.Z` werden veröffentlicht. GitHub Actions prüft den Quellcode und baut das Asset `DAM-vX.Y.Z.zip`. Der Selbst-Updater akzeptiert nur den exakten Assetnamen, die offizielle SHA-256-Prüfsumme und erlaubte Programmdateien. **GitHubs automatisch generiertes Quellcode-ZIP ist nicht als Update geeignet.**

Eine SHA-256-Prüfsumme beweist die Integrität des Pakets gegenüber den GitHub-Metadaten, aber keine unabhängige Autorenschaftssignatur. Ein signierter Veröffentlichungsprozess ist als spätere Verbesserung geplant.

Technische Details: [Selbstupdate-Plan](docs/SELBSTUPDATE_PLAN.md).

### Tests

```bash
python3 -m unittest discover -p 'test_*.py' -q
```

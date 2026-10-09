# DAM

**DAM** ist ein grafischer App-Manager für Ubuntu (GTK 4 / Libadwaita).

## Stand: v0.6.4 – Manuelle DAM-Backups und Bereinigung

- Apps installieren, aktualisieren und deinstallieren (unterstützte Quellen)
- GTK-Kacheln, Suche, Auswahl, Info-Reiter und deutsche Oberfläche
- DAM-Selbstupdate über stabile öffentliche GitHub-Releases
- SHA-256-Prüfung mit dem offiziellen Release-Digest, striktes ZIP-Dateischema, Versions- und Python-Syntaxprüfung
- Versionierte, benutzerlokale Installationen mit stabilem Launcher
- Automatische Wiederherstellung der Vorversion, wenn DAM nach dem Update nicht erfolgreich startet
- Manuelle Sicherung der aktuellen DAM-Version via Rechtsklick (Markierung statt zusätzlicher Kopie)
- Info-Reiter: **Speicher & Backups** mit Versionsliste, individueller Wiederherstellung und freiwilliger Bereinigung
- Aktive und letzte Rückfallversion vor Löschung geschützt; zusätzlich dauerhaft markierte Versionen ebenfalls geschützt
- Kein automatisches Löschen: nur einzeln ausgewählte ältere Versionen nach Bestätigungsdialog
- Alte Migrationsstände ohne neueren Neustartmechanismus sind nicht per Ein-Klick-Restore verfügbar
- Unaufdringlicher Bereinigungshinweis im Info-Reiter ab 250 MiB möglicher Ersparnis
- Manuelles Rollback über gespeicherte und kompatible frühere DAM-Versionen

**Wichtig:** v0.6.0 wurde unter Ubuntu erfolgreich über den neuen Launcher gestartet. v0.6.1 hat die neue Version über GitHub erkannt, wurde jedoch nicht als Kachel angezeigt, wenn Gio den DAM-Starter nicht listete. v0.6.2 korrigiert das und zeigt konkrete Fehlerquellen direkt an. v0.6.2 und v0.6.3 liefen erfolgreich auf dem Ubuntu-Rechner; v0.6.3 wurde vollständig über die DAM-Oberfläche installiert. v0.6.4 ergänzt die Backup- und Bereinigungsverwaltung, deren Bedienung auf dem Ubuntu-Desktop noch praktisch getestet werden muss. Der erste Einstieg erfolgt einmalig über `install.sh` aus dem Bootstrap-Paket.

### Lokale Installation

Das Bootstrap-Paket `DAM_v0.6.0.zip` entpacken und im entpackten Ordner `bash install.sh` ausführen. Die alte Installation in `~/DAM` und eigene App-Beschreibungen bleiben bestehen.

Danach: Start über das Anwendungsmenü; der stabile Launcher liegt in `~/.local/bin/dam-launcher`. Die aktuelle Programmversion liegt unter `~/.local/share/dam/current`.

### Backups und Bereinigung (v0.6.4)

DAM-Versionen liegen unter `~/.local/share/dam/versions/`. Eine Sicherung per Rechtsklick markiert die vorhandene Version als **dauerhaft behalten**. Der Schutz wird in `~/.local/state/dam/backup-pins.json` gespeichert und übersteht Updates. Im Info-Reiter ist immer sichtbar, welche **älteren** Versionen bereinigt werden könnten und wie groß diese zusammen sind. DAM löscht nie ungefragt Dateien. Die derzeit aktive und die unmittelbare Rückfallversion können nicht gelöscht werden. Schutzmarkierungen anderer Versionen lassen sich bewusst aufheben. Bei einer Wiederherstellung startet DAM automatisch neu und rollt bei Startfehler zurück.

**Geltungsbereich:** Diese Funktion gilt vorerst nur für DAM selbst. App-Backups für APT, Snap und Flatpak müssen jeweils paketquellenspezifisch implementiert werden und sind noch nicht verfügbar. Persönliche Daten und Programmeinstellungen werden nicht gesichert bzw. verändert.

### Releases

**Kein manuelles Release nötig:** Sobald eine Version fertig und getestet ist, committen wir `release-request.json` mit derselben Version wie in `dam.py` und `version.json`. Nur dieser gezielte Commit startet GitHub Actions. Der Workflow validiert die Version und Release-Notizen, führt die vollständigen Tests aus, baut `DAM-vX.Y.Z.zip` und erstellt das stabile GitHub-Release samt Download-Asset automatisch. Normale Code-Commits veröffentlichen nichts. Bereits existierende Tags und Releases werden nicht überschrieben. Der Selbst-Updater akzeptiert nur den exakten Assetnamen, die offizielle SHA-256-Prüfsumme und erlaubte Programmdateien. **GitHubs automatisch generiertes Quellcode-ZIP ist nicht als Update geeignet.**

Eine SHA-256-Prüfsumme beweist die Integrität des Pakets gegenüber den GitHub-Metadaten, aber keine unabhängige Autorenschaftssignatur. Ein signierter Veröffentlichungsprozess ist als spätere Verbesserung geplant.

Technische Details: [Selbstupdate-Plan](docs/SELBSTUPDATE_PLAN.md).

### Tests

```bash
python3 -m unittest discover -p 'test_*.py' -q
```

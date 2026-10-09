# DAM – Plan für sichere Selbstupdates (ab v0.6.0)

Stand: 09.10.2026. **Planung**, noch keine implementierte Selbstaktualisierung.

## Ausgangslage

- DAM v0.5.25, GTK 4 / Libadwaita / Python.
- Der aktuelle Installer kopiert Dateien in `~/DAM` und erstellt einen benutzerlokalen Desktop-Starter.
- Keine Root-Rechte für DAM selbst erforderlich; Root wird nur für Paketaktionen verwendet.
- GitHub-Repository: `Davegage-byte/DAM`; derzeit **privat**.
- Die Updateprüfung soll wie bisher erst beim ersten Öffnen des Reiters „Aktualisieren“ starten.
- Die bisherige Benutzeroberfläche und die 3 + Info-Reiter bleiben unverändert.

## Architektur

### 1. Fester Launcher, versionierte Installationen

- Stabiles Einstiegsskript: `~/.local/bin/dam-launcher`; Desktop-Starter zeigt ausschließlich darauf.
- Freigegebene Versionen: `~/.local/share/dam/versions/<version>/`.
- Aktiver Versionsverweis: `~/.local/share/dam/current` (atomar umschaltbarer Symlink).
- Der Launcher startet `current/dam.py` mit `/usr/bin/python3`.
- Ein vom gestarteten DAM unabhängiger Updater nimmt den Versionswechsel vor, **nachdem DAM sich beendet hat**.
- Laufzeitdaten getrennt halten: `~/.config/dam/` für Einstellungen und `~/.local/state/dam/` für Logs/Updatezustände.
- Migration: Bestehende Installation `~/DAM` **zuerst sichern**, danach eine geprüfte v0.6.0 als erste verwaltete Version installieren. Alte Desktop-Verknüpfungen berücksichtigen.

### 2. Update-Erkennung

- Ausschließlich die bekannte Quelle `https://api.github.com/repos/Davegage-byte/DAM/releases/latest`.
- Nur veröffentlichtes stabiles Release: nicht `draft`, nicht `prerelease`.
- Versionsvergleich gegen die tatsächlich aktive DAM-Version; kein ungefragtes Downgrade.
- Erwarteter Assetname nach festem Schema, etwa `DAM-v0.6.1.zip`.
- Fehlende Verbindung, GitHub-Rate-Limit oder fehlendes Release zeigen eine verständliche Meldung, ohne bestehende Installation zu beeinträchtigen.
- DAM erscheint unter „Aktualisieren“ **nur wenn eine neuere Version gefunden wird**; kein Start-Scan vor dem ersten Reiterwechsel.

### 3. Sicherer Download und Prüfung

- HTTPS, Zeitlimit, begrenzte Größe; Download in separates temporäres Verzeichnis.
- Asset-Hash (SHA-256) berechnen und gegen den Wert `assets[].digest` der offiziellen GitHub-Releases-API prüfen.
- Release-Tag, Assetname, Manifestversion und angekündigte Version müssen übereinstimmen.
- ZIP vor Extraktion prüfen: keine absoluten Pfade, `../`-Traversal, doppelte Namen, unerwartete Symlinks oder nicht erlaubte Dateien; Schutz gegen ZIP-Bomben.
- Nur vordefinierte Programmdateien in ein neues Staging-Verzeichnis extrahieren. **Keine mitgelieferten Shell-Skripte blind ausführen.**
- Python-Dateien syntaktisch prüfen; danach Start-/Importtests der isolierten Version.
- SHA-256 schützt die Integrität des Downloads, **nicht** gegen eine kompromittierte GitHub-Veröffentlichung. Releases nach Möglichkeit auf immutable stellen; für höhere Sicherheit später signiertes Manifest / unabhängigen Prüfschlüssel ergänzen.

### 4. Aktivierung und Rollback

- Vor jeder Aktivierung die bisherige Version unverändert behalten; maximal einige alte Versionen kontrolliert aufbewahren.
- Wartenden Updater starten; DAM beendet sich normal.
- Neue Version nach erfolgreicher Prüfung atomar aktivieren, dann über den stabilen Launcher starten.
- DAM bestätigt nach dem erfolgreichen Aufbau des GTK-Fensters die Bereitschaft gegenüber dem Updater.
- Kein Bereitschaftssignal innerhalb eines sinnvollen Limits (z. B. 30 Sekunden), Prozessabsturz oder Startfehler: Verweis atomar auf die vorherige Version zurücksetzen, diese starten, Fehlermeldung protokollieren.
- Optional in „Info“: „Vorherige Version wiederherstellen“ für Fehler, die erst nach dem Start sichtbar werden.
- Niemals Nutzerkonfiguration oder persönliche App-Listen beim Rollback überschreiben.
- Ein Update-Lock verhindert parallele Updater oder Paketaktionen während des Versionswechsels.

### 5. Benutzeroberfläche

- Bestehende Farbschemata bleiben erhalten; DAM erscheint im Reiter „Aktualisieren“ nur bei neuem Release.
- Anzeige von Version, kurzen Release-Notizen und den Aktionen „Später“ und „Jetzt aktualisieren“.
- Laden, Prüfen und Aktivieren mit der bestehenden einheitlichen Ladeanzeige; keine erfundenen Fortschrittsprozente.
- Bestätigung und kurzer Hinweis vor Neustart.
- Fehler mit Rückfall auf die alte Version; in „Info“ ein lesbarer Updateverlauf.

## Veröffentlichung

1. Repository vor Umstellung auf Public auf Passwörter/Tokens, lokale Pfade, Protokolle und **gesamte Git-Historie** prüfen. Die erste Prüfung der bekannten aktuellen Quellcodedateien zeigte keine offensichtlichen Tokens; das ersetzt keine vollständige Auditierung.
2. Sichtbarkeit **erst nach ausdrücklicher Zustimmung** auf Public ändern. Öffentliche Repositories legen auch Commit-Historie und GitHub-Actions-Logs offen.
3. CI führt bestehende Tests, statische Syntaxchecks, Paketstrukturprüfung und reproduzierbaren Build aus.
4. Releases zunächst bewusst manuell freigeben: v0.6.0 als Bootstrap, v0.6.1 als erster echter Selbstupdate-Test.
5. ZIP als echtes Release-Asset veröffentlichen (nicht GitHubs automatisch generiertes Quellcode-ZIP); SHA-256-Digest der API prüfen.
6. Releases nach Möglichkeit immutable veröffentlichen. Später Signaturen/Attestierungen ergänzen.

## Geplante Abnahmetests

- Update erfolgreich: v0.6.0 → v0.6.1, Desktop-Verknüpfung bleibt funktionsfähig.
- Kein Update, offline, GitHub 403/404/429, Downloadabbruch, beschädigter ZIP, falscher Hash, falscher Versions-Tag, unerlaubte Datei: alte Version bleibt unverändert.
- Fehler vor Aktivierung: Staging verwerfen.
- Neue Version startet nicht oder bestätigt Bereitschaft nicht: automatischer Rollback und erneuter Start der vorherigen Version.
- Manuelles Rollback nach erfolgreichem Start ist möglich, solange eine Vorversion existiert.
- Keine Root-/Passwortabfrage für DAM-Selbstupdates.
- Keine Aktualisierung anderer APT/Snap/Flatpak-Apps durch den Self-Updater selbst.
- Ausführung von DAM-Updates nicht parallel zu einer laufenden Installation/Deinstallation.

## Umsetzung in Schritten

- **v0.6.0:** Migration + stabiler Launcher, getrennter Updater, Releases-Check, Verifikation, Staging, atomare Aktivierung, automatischer Rollback.
- **v0.6.1:** Erster regulärer GitHub-Release zum Ende-zu-Ende-Praxistest des Selbstupdates.
- **später:** Signierter Veröffentlichungsprozess, Konfiguration/Favoriten-Export, AppList-Synchronisierung.

**Wichtig:** Dieses Dokument autorisiert weder den Wechsel auf Public noch das Veröffentlichen eines neuen Releases. Beides geschieht erst nach Prüfung und Freigabe.

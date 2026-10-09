#!/usr/bin/env bash
# DAM – benutzerlokale Installation mit Backup, ohne Root-Rechte.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/DAM"
APPDIR="$HOME/.local/share/applications"
ICONDIR="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$DEST" "$APPDIR" "$ICONDIR"
# Vor einer Änderung die Syntax aller benötigten Python-Dateien prüfen.
/usr/bin/python3 - "$HERE" <<'PY'
import pathlib, sys
folder = pathlib.Path(sys.argv[1])
for filename in ('dam.py', 'package_updates.py', 'rustdesk_update.py', 'app_shortcuts.py', 'apt_install.py', 'apt_remove.py', 'apt_process.py'):
    compile((folder / filename).read_bytes(), str(folder / filename), 'exec')
PY
if [[ -f "$DEST/dam.py" ]]; then
  cp -a -- "$DEST/dam.py" "$DEST/dam_backup_before_v0.5.25.py"
fi
for file in dam.py package_updates.py rustdesk_update.py app_shortcuts.py apt_install.py apt_remove.py apt_process.py; do
  cp -- "$HERE/$file" "$DEST/$file"
done
cp -- "$HERE/dam.png" "$ICONDIR/de.davegage.dam.png"
cat > "$APPDIR/de.davegage.dam.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DAM
Comment=Programme verwalten
Exec=/usr/bin/python3 $DEST/dam.py
Icon=$ICONDIR/de.davegage.dam.png
Terminal=false
Categories=System;Utility;
StartupNotify=true
EOF
chmod 644 "$APPDIR/de.davegage.dam.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPDIR" || true
fi
printf '\nDAM v0.5.25 installiert. Bitte DAM über das Anwendungsmenü starten.\n'

#!/usr/bin/env bash
# DAM – einmalige Migration auf versionierte Installationen (ohne sudo).
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$HOME/.local/share/dam"
VERSIONS="$ROOT/versions"
APPDIR="$HOME/.local/share/applications"
ICONDIR="$HOME/.local/share/icons/hicolor/256x256/apps"
BINDIR="$HOME/.local/bin"
STATE="$HOME/.local/state/dam"
FILES=(dam.py dam_updater.py package_updates.py rustdesk_update.py app_shortcuts.py apt_install.py apt_remove.py apt_process.py dam.png version.json)
for file in "${FILES[@]}"; do
  [[ -f "$HERE/$file" ]] || { echo "Fehlende Programmdatei: $file" >&2; exit 1; }
done
/usr/bin/python3 - "$HERE" <<'PY'
import json, pathlib, sys
folder = pathlib.Path(sys.argv[1])
assert json.loads((folder / 'version.json').read_text()) == {'schema': 1, 'version': '0.6.0'}
for path in folder.glob('*.py'):
    compile(path.read_bytes(), str(path), 'exec')
PY
mkdir -p "$VERSIONS" "$APPDIR" "$ICONDIR" "$BINDIR" "$STATE"
chmod 700 "$ROOT" "$VERSIONS" "$STATE"
# Originalinstall 0.5.25 als Rückfallversion behalten, ohne Nutzerdaten anzufassen.
if [[ -f "$HOME/DAM/dam.py" && ! -e "$VERSIONS/0.5.25" ]]; then
  TEMP_OLD="$(mktemp -d "$VERSIONS/.migration-old-XXXXXXXX")"
  for file in dam.py package_updates.py rustdesk_update.py app_shortcuts.py apt_install.py apt_remove.py apt_process.py; do
    [[ ! -f "$HOME/DAM/$file" ]] || cp -- "$HOME/DAM/$file" "$TEMP_OLD/$file"
  done
  if [[ -f "$ICONDIR/de.davegage.dam.png" ]]; then
    cp -- "$ICONDIR/de.davegage.dam.png" "$TEMP_OLD/dam.png"
  fi
  printf '{"schema":1,"version":"0.5.25"}\n' > "$TEMP_OLD/version.json"
  mv -- "$TEMP_OLD" "$VERSIONS/0.5.25"
fi
# Quelle vollständig kopieren, bevor der Startverweis geändert wird.
STAGING="$(mktemp -d "$VERSIONS/.bootstrap-XXXXXXXX")"
trap '[[ ! -d "${STAGING:-}" ]] || rm -rf -- "$STAGING"' EXIT
for file in "${FILES[@]}"; do
  cp -- "$HERE/$file" "$STAGING/$file"
done
if [[ -e "$VERSIONS/0.6.0" ]]; then
  echo 'DAM 0.6.0 liegt bereits vor: installierte Kopie wird ersetzt.'
  # Eine bestehende aktiv verwendete Version niemals in-place überschreiben.
  if [[ "$(readlink "$ROOT/current" 2>/dev/null || true)" == 'versions/0.6.0' ]]; then
    echo 'DAM 0.6.0 ist bereits aktiv; keine Änderung vorgenommen.'
    exit 0
  fi
  rm -rf -- "$VERSIONS/0.6.0"
fi
mv -- "$STAGING" "$VERSIONS/0.6.0"
# Stabiler Starter bleibt bei künftigen Updates unverändert.
cat > "$BINDIR/dam-launcher" <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 "$HOME/.local/share/dam/current/dam.py" "$@"
EOF
chmod 755 "$BINDIR/dam-launcher"
cp -- "$HERE/dam.png" "$ICONDIR/de.davegage.dam.png"
cat > "$APPDIR/de.davegage.dam.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DAM
Comment=Programme verwalten
Exec=$BINDIR/dam-launcher
Icon=$ICONDIR/de.davegage.dam.png
Terminal=false
Categories=System;Utility;
StartupNotify=true
EOF
chmod 644 "$APPDIR/de.davegage.dam.desktop"
LINK="$ROOT/.current-bootstrap-$$"
ln -s 'versions/0.6.0' "$LINK"
mv -Tf -- "$LINK" "$ROOT/current"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPDIR" || true
fi
printf '\nDAM v0.6.0 eingerichtet. Bitte über das Anwendungsmenü starten.\n'

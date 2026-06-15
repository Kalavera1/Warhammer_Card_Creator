#!/usr/bin/env bash
# Startet den Warhammer Card Generator.
#
#   ./run.sh                 -> verarbeitet alle Listen in lists/
#   ./run.sh datei.json      -> nur diese Datei
#   ./run.sh /pfad/zu/ordner -> alle Listen in diesem Ordner
#
# Ergebnisse landen in output/. Funktioniert von ueberall (cd ins Skript-Verz.).
set -e
cd "$(dirname "$0")"

python3 generate_cards.py "$@"

echo
echo "Fertig. Ergebnisse in: $(pwd)/output"

# Output-Ordner im Datei-Explorer oeffnen, falls unter WSL/Windows verfuegbar.
if command -v explorer.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    explorer.exe "$(wslpath -w "$(pwd)/output")" >/dev/null 2>&1 || true
fi

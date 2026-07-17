# Warhammer Card Creator — Projektregeln für Claude

Einheiten-Karten + Ablaufplan für "Warhammer: The Old World" aus
NewRecruit/BattleScribe- oder Old-World-Builder-Listen (JSON).
CLI: `generate_cards.py <liste.json>` → `output/<name>.html`, PDF via
Browser-Druck; `--zauber` → Zauberkarten aller Lehren (live von
tow.whfb.app). Browser-UI: `index.html` + `js/app.js` (Pyodide).
Karten: Klick auf Regel/Zauber einer Rückseite = vom Druck ausnehmen;
Höhe wächst 105→140 mm (Duplex-Paar gleich hoch), dann erst Schrift-Shrink.

## Randbedingungen

- Repo ist **ÖFFENTLICH**: keine GW-Regeltexte in Volltext, keine
  persönlichen Armeelisten einchecken (`lists/*.json` ist gitignored,
  Test-Fixtures nur synthetisch mit erfundenen Namen/Texten).
- Der `<title>` der generierten Seiten = Name der Eingabedatei — daraus
  macht der Browser den PDF-Dateinamen-Vorschlag. Nicht ändern.

## Datenfluss (Entscheidungen vom Nutzer, 2026-07-12 / 2026-07-16)

- **Kuratierte Kartentexte gewinnen immer:** `rule_text.json`
  → `overrides` enthält vom Nutzer formulierte Kurzfassungen
  (max. 150 Zeichen ≙ 2 Zeilen auf der Rückseite, Test erzwingt das).
  Sie ersetzen den Export-Text, der sonst mitten im Satz mit „…"
  abgeschnitten würde. Schlüssel = Regel-/Zauber-Name ohne
  (X)-Klammer. Neue Langtexte → neuen Override ergänzen.
- Sonst: **die Export-JSON ist die Quelle der Wahrheit.** Liefert sie
  einen Regeltext, wird dieser angezeigt (frisch gekürzt via
  `short_text`) — nichts wird gemerkt/eingefroren.
- `rule_text.json → front_highlights` (Regelname → '' | 'charge' |
  'charged'): Kampf-Sonderregeln, die als „Auf einen Blick"-Zeile mit
  Kurz-Effekt auf die VORDERSEITE kommen (gruppiert nach „Wenn du
  angreifst"/„Wenn du angegriffen wirst"). Magische Items mit Wirkung
  (Standarten, Waffen-Note …) bekommen dort automatisch eine Zeile;
  magische Waffen sind in der Waffentabelle gold markiert.
- Die lokalen Regel-DBs (`rule_text.json`, `rule_glossary.json`) sind
  NUR Fallback für Regeln ohne Text im Export (OWB-Listen,
  Waffen-/Universalregeln). `rule_phases.json` ordnet Regeln den
  Phasen im Ablaufplan zu (selbstlernend).
- OWB-Listen: Statlines + Zauber live von tow.whfb.app (Build-ID wird
  von der Startseite gescrapt — fragil, Fehler werden als Hinweis
  gemeldet und die Karten kommen ohne Statline).

## Tests: KEIN Commit ohne grüne Suite

- `python3 run_tests.py` — Syntax, pyflakes, `node --check`,
  Regel-DB-Struktur, Kurztext-Priorität, Ende-zu-Ende-Generierung
  mit synthetischem Fixture (`tests/fixtures/testliste.json`).
- Hook: `hooks/pre-commit` (aktivieren via
  `git config core.hooksPath hooks`); CI: `.github/workflows/tests.yml`.
- Regeln vom Nutzer: jeder Fix → Regressionstest, neue Features → Tests.

# Warhammer: The Old World – Unit Card Generator

Erzeugt aus einer NewRecruit/BattleScribe-Armeeliste (JSON-Export) pro Einheit
eine kompakte **Übersichtskarte** mit Vorder- und Rückseite – druckfertig als
HTML (A6 quer, 2 Karten pro A4-Seite).

## Projektstruktur

```
generate_cards.py   Skript (von überall startbar)
rule_phases.json    Phasen-Zuordnung für den Ablaufplan
lists/              HIER die NewRecruit-JSON-Exporte ablegen (Eingabe)
output/             erzeugte Karten + Pläne (Ausgabe)
reference/          Vorlage (docx) + Beispiel-Screenshot
```

## Benutzung

NewRecruit-Listen als JSON nach `lists/` legen, dann starten:

```bash
# Alle Listen im Ordner lists/
python3 generate_cards.py

# Oder gezielt: eine Datei bzw. ein beliebiger Ordner
python3 generate_cards.py "lists/Steelhammer 1000_1200  (Copy).json"
python3 generate_cards.py /pfad/zu/meinen_listen
```

Die Pfade hängen am Skript, nicht am Arbeitsverzeichnis – du kannst
`python3 /pfad/zu/generate_cards.py` von überall aufrufen.

Pro Liste entstehen in `output/` **zwei** Dateien:
- `<Name>.html` – die Unit-Karten
- `<Name>_plan.html` – der **Ablaufplan** (Phasen-Cheatsheet) der Armee

Zusätzlich entsteht **einmal pro Lauf** eine listenunabhängige
**`Schnellreferenz.html`** – eine Karte (Vorder- + Rückseite) mit den
statischen Kernregeln: To-Hit-Tabellen (Nahkampf & Schießen), To-Wound-Tabelle,
Schuss-Modifikatoren sowie alle Würfe/Abläufe (Leadership-Test, Charge, Flee &
Pursuit, Rally, Restraint, Break-Test, Panic-Test) und die Kampfergebnis-Boni.
Werte geprüft gegen <https://tow.whfb.app/quick-reference> u. a. Im selben
A6-Format, mitdruckbar im Karten-Deck.

Zum Drucken/PDF die Datei im Browser
öffnen und **Strg+P** → beidseitig drucken (Wenden an der **langen Kante**).
Reihenfolge der Seiten: Blatt 1 = 2 Vorderseiten, Blatt 2 = die passenden
2 Rückseiten usw., damit Front/Back beim Duplexdruck zusammenpassen.

## Karteninhalt

**Vorderseite (kompakt):**
- Name, Punkte (über den ganzen Einheiten-Teilbaum summiert), Kategorie
  (Characters/Core/Special/Rare), Truppentyp, Basegröße, Modellzahl
- Statline(s) (M WS BS S T W I A Ld) – mehrere Zeilen bei abweichenden
  Modellen/Mounts (z.B. Champion, Reittier)
- Rüstungswurf als Schild-Symbol, automatisch berechnet, plus Auflistung der
  eingegangenen Teile (z.B. „Heavy Armour (5+), Shield (−1)“)
- Waffen (R / S / AP / Sonderregeln), Kommandogruppe, magische Gegenstände,
  Zauberliste, sowie alle Sonderregel-Namen

**Rückseite:** Alle Sonderregeln (Name + **Kurzfassung**), magische Gegenstände
und Zauber (mit Gusswert/Reichweite/Effekt) als Liste untereinander, plus ein
**Auffang-Eimer** für sonstige Profiltypen (Vows, Blessings, neue
Fraktionsmechaniken …) – gruppiert unter ihrer Typ-Überschrift. So geht nichts
verloren, egal welche Fraktion eingelesen wird. (Die generischen Command-Texte –
Champion/Standartenträger/Musiker – sind über `HANDLED_TYPES` ausgenommen, da
sie sonst jede Karte aufblähen; die Kommandogruppe steht weiterhin vorne.)

**Hervorhebung:** Spielentscheidende Stellen im Regeltext werden amber markiert –
Würfelausdrücke (`D6`, `2D6 hits`, `D3+1 wounds` …), Reichweiten (`12"`),
Stärke (`S5`, `S+2`, `Strength 5`), Trefferschwellen (`4+ to wound`) und
„kein Rettungswurf"-Phrasen (`no armour save`, `no save of any kind`,
`ignoring armour saves` …). Steuerung über `HL_RE` in `generate_cards.py`.

**Kurzfassungen (`rule_text.json`):** Damit auch Charaktere/Magier mit vielen
Regeln und Zaubern lesbar auf eine A6-Rückseite passen, wird pro Regel/Zauber nur
eine **Kurzfassung** gezeigt (auf Karte **und** im Plan identisch). Verwaltung wie
bei `rule_phases.json`:
- `summaries` – von Hand gepflegte Kurztexte (Schlüssel = exakter Name)
- `learned` – vom Tool automatisch gekürzt (erster Satz) und gemerkt; jederzeit
  korrigierbar oder nach `summaries` verschiebbar

Da ein Eintrag pro Name gilt, sieht dieselbe Regel überall gleich aus.

**Waffenregeln-Glossar (`rule_glossary.json`):** NewRecruit exportiert die
**Beschreibungen der Waffen-Sonderregeln** (Helblaster, Multiple Shots, Killing
Blow, Breath Weapon …) **nicht** – im Waffenprofil stehen nur die Namen. Diese
Erklärungen liefert das Glossar und zeigt sie auf der Rückseite unter
**„Waffenregeln"**. Quelle/Prüfung: <https://tow.whfb.app/special-rules>. Schlüssel
= Regelname ohne `(X)`-Klammer; fehlende Regeln erscheinen als „– nachschlagen"
und können einfach in `rule_glossary.json` ergänzt werden.

**Layout der Rückseite:** **immer eine Spalte** (zwei Spalten wären zu klein zum
Lesen). Passt der Inhalt nicht in die Kartenhöhe, verkleinert ein kleines Script
beim Öffnen/Drucken nur die **Schrift** so weit, dass nichts abgeschnitten wird –
im Browser, ohne zusätzliche Abhängigkeit.

## Ablaufplan (`<Name>_plan.html`)

Pro Armee ein **Phasen-Cheatsheet** als 4-Spalten-Tabelle
(Phase | Unterphase | Aktion & Sonderfertigkeit | Einheit) entlang der festen
Old-World-Zugreihenfolge (Setup → Strategy → Movement → Shooting → Combat).
Hineinsortiert wird automatisch:

- **Zauber** nach ihrem `Type` (in TOW fest einer Phase zugeordnet):
  Hex/Enchantment/Conjuration → Command, Conveyance → Movement,
  Magic Missile/Vortex → Shooting, Assailment → Combat.
- **Fernkampfwaffen**: Jede Einheit mit einer Distanzwaffe (Reichweite mit Zahl,
  z.B. Helblaster, Pistoliere, Handgunner) erscheint in der Shooting-Phase –
  auch ohne eigene Sonderregel.
- **Sonderregeln** über die Datendatei `rule_phases.json` (siehe unten),
  z.B. Scouts/Vanguard → Setup, Impact Hits/Stomp → Choose & Fight,
  Terror → Break Test.
- Jede Zeile: **Name + Kurz-Effekt** (erster Satz der Regel) + betroffene Einheit(en).
  In der Spalte „Einheit" wird jede Einheit pro Zelle nur **einmal** genannt
  (auch wenn sie dort mehrere Aktionen/Zauber hat).

Der Plan zeigt **nur, was in einer Phase aktiv passiert**. Rein passive /
nicht eindeutig zuordenbare Regeln werden im Plan bewusst weggelassen (sie
stehen ohnehin auf den Karten). Die Zuordnung ist best-effort; vor dem Spiel
kurz gegenprüfen.

### Selbstständige Phasen-Zuordnung (`rule_phases.json`)

Damit das Tool **offline und ohne KI** arbeitet, steckt das gesamte Wissen in
`rule_phases.json` (neben dem Skript, frei editierbar):

- `sequence` – die Zugreihenfolge (Phasen/Unterphasen)
- `spell_types` – Zaubertyp → Phase
- `rules` – Stichwort im Regel**namen** → `[Phase, Unterphase]`
  (`"Passiv"` = Immer-aktiv-Sektion). Seed enthält die TOW Universal Special Rules.
- `heuristic` – Stichwort im Regel**text** → Phase (Fallback für Unbekanntes)
- `passive_text_signals` – Textsignale, die eine Regel als rein passiv markieren
- `learned` – **vom Tool automatisch ergänzt**: Regeln, die per Heuristik aus der
  Beschreibung zugeordnet wurden, werden hier gespeichert und beim nächsten Lauf
  wiederverwendet. Bei Bedarf korrigieren oder nach `rules` verschieben.

Ablauf je Regel: erst `rules`/`learned` (Name), dann passive Textsignale, dann
`heuristic` (Text) – Treffer wird in `learned` gemerkt –, sonst „Passiv".
So braucht es keine Internet-Referenz: der Regeltext steht bereits im
NewRecruit-Export, das Tool muss nur die Phase erkennen.

## Save-Berechnung (Best-effort)

- Bester Basiswert aus den Rüstungsprofilen (Wert steht in Description **oder**
  im Profilnamen, z.B. Monster „Armour Value : 5+“)
- Schild / Barding verbessern um 1
- Feste Werte („cannot be improved“, z.B. Master Rune of Gromril 2+)
  überschreiben Basis + Verbesserungen
- Da exotische Kombinationen vorkommen können, immer kurz gegenprüfen – die
  eingegangenen Teile stehen zur Kontrolle auf der Karte.

## Layout anpassen

Das komplette Aussehen steckt in der `CSS`-Konstante in `generate_cards.py`
(Farben, Schriftgrößen, Kartenmaße). Kartengröße: `.card { width/height }`.

## Hinweise

- Eingaben sind BattleScribe-JSON: `roster.forces[].selections[]`, jede
  Top-Level-Selection vom Typ `unit` (oder mit eigenem Profil) wird eine Karte.
- `*.json:Zone.Identifier`-Dateien (Windows-Downloadmarker) werden ignoriert.

## Eingabeformate

- **NewRecruit / BattleScribe** (`roster`-JSON) – **volle Karten** mit Statline,
  Waffenprofilen und Rüstungswurf (alle Werte stehen im Export). Empfohlen.
- **Old World Builder** (`*.owb.json`) – OWB exportiert **keine Statwerte** (nur
  Namen/Punkte/Optionen/Regelnamen). Das Tool erkennt das Format automatisch und
  **holt die Statlines live von [tow.whfb.app](https://tow.whfb.app)** (per
  Einheitenname; eine Anfrage pro Fraktion, `buildId` wird live ermittelt).
  Ergebnis: echte Statline + Reittier-Werte + Regel-Kurzfassungen. Waffen
  erscheinen mit Namen (R/S/AP liegen nicht im OWB-Export). Ohne Internet bzw.
  ohne Treffer bleiben die Karten ohne Statline, sonst aber vollständig.
  Der Netzwerkabruf liegt bewusst **außerhalb** von `generate_cards.py` (Browser:
  JS `fetch`; CLI: `fetch_owb_stat_units` via `urllib`), damit der NewRecruit-Pfad
  voll offline bleibt.

### Zauber bei OWB

OWB nennt nur die gewählte Magielehre (`activeLore`), nicht die konkreten Zauber
(die werden im Spiel ausgewürfelt). Hat ein Magier eine Lore gewählt, holt das Tool
die **komplette Lehre live von tow.whfb.app** (`/cards/<lore>`) und zeigt sie **in
Würfel-Reihenfolge**: der **Signature-Zauber** (immer verfügbar, mit `*` markiert),
gefolgt von den **6 nummerierten Zaubern (1–6)** – jeweils mit Gusswert, Kategorie,
Reichweite und Effekt. So kann man am Tisch direkt mit W6 darauf würfeln. (Bei
NewRecruit stehen die Zauber inkl. Nummer ohnehin im Export.)

## Web-App (im Browser, ohne Installation)

Neben der lokalen CLI gibt es eine **Browser-Version** auf GitHub Pages:

**<https://kalavera1.github.io/Warhammer_Card_Creator/>**

Liste(n) als JSON wählen → die Karten werden direkt im Browser erzeugt und können
über den Druck-Dialog als PDF gespeichert werden. Technik:

- Der **unveränderte** Generator (`generate_cards.py`) läuft per **Pyodide**
  (CPython als WebAssembly) im Browser – kein Server, **nichts wird hochgeladen**,
  die Liste bleibt auf dem Gerät des Nutzers.
- Frontend: `index.html` + `js/app.js`. Diese laden `generate_cards.py` und die
  drei Datendateien in Pyodides virtuelles Dateisystem und rufen
  `build_cards_html(data)` bzw. `render_reference_document()` auf – also exakt
  dieselbe Render-Pipeline wie die CLI (eine Quelle der Wahrheit).
- Die **lokale CLI bleibt unverändert** voll nutzbar (`python3 generate_cards.py`,
  `run.sh`, `Karten erstellen.bat`).

## Mitentwickeln / Branch-Workflow

Das Projekt liegt auf GitHub:
<https://github.com/Kalavera1/Warhammer_Card_Creator>

- **`main`** ist immer stabil und lauffähig – hier wird **nicht** direkt entwickelt.
- Jedes neue Feature / jeder Fix entsteht auf einem eigenen **Feature-Branch**:

  ```bash
  git checkout main && git pull          # aktuellen Stand holen
  git checkout -b feature/<kurzname>     # Seiten-Branch anlegen
  # ... entwickeln, committen ...
  git push -u origin feature/<kurzname>  # Branch hochladen
  gh pr create --fill                    # Pull Request nach main öffnen
  ```

- Nach Review wird der PR nach `main` gemergt; danach den Branch löschen
  (`git branch -d feature/<kurzname>`).

**Datenschutz:** Persönliche Armeelisten (`lists/*.json`) und der `output/`-Ordner
sind via `.gitignore` ausgeschlossen und landen nicht im öffentlichen Repo.
Commits nutzen die GitHub-noreply-Adresse, damit keine private E-Mail in der
öffentlichen History steht.

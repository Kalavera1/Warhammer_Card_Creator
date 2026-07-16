#!/usr/bin/env python3
"""Warhammer: The Old World - Unit Card Generator.

Liest eine NewRecruit/BattleScribe-Armeeliste (JSON) und erzeugt pro Einheit
eine kompakte Karte mit Vorder- und Rueckseite als druckbare HTML-Datei
(A6 quer, 2 Karten pro A4-Seite).

Benutzung:
    python3 generate_cards.py            # verarbeitet alle JSON in lists/
    python3 generate_cards.py datei.json # oder eine bestimmte Datei
    python3 generate_cards.py ordner/    # oder einen beliebigen Ordner

Pfade haengen am Skriptverzeichnis -> von ueberall aufrufbar.
Ausgabe landet in output/<Listenname>.html. Drucken/PDF via Browser (Strg+P).
"""
from __future__ import annotations

import glob
import html
import json
import os
import re
import sys
from dataclasses import dataclass, field

# Alle Pfade haengen am Skriptverzeichnis -> von ueberall startbar.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT_DIR = os.path.join(BASE_DIR, "lists")    # Eingabe: NewRecruit-JSONs
OUTPUT_DIR = os.path.join(BASE_DIR, "output")          # Ausgabe: Karten + Plaene

# --- Statline-Reihenfolge wie im Old-World-Profil ----------------------------
STAT_KEYS = ["M", "WS", "BS", "S", "T", "W", "I", "A", "Ld"]

MAGIC_ITEM_TYPES = {
    "Magic Weapons", "Magic Armour", "Armour Runes", "Weapon Runes",
    "Talismanic Runes", "Engineering Runes", "Standard Runes",
    "Enchanted Items", "Arcane Items", "Talismans", "Magic Standards",
}
WEAPON_TYPES = {"Weapon", "Magic Weapons"}

# typeNames, die bereits in eigenen Bereichen behandelt werden bzw. rein
# strukturell sind -> nicht in den Auffang-Eimer (siehe build_unit).
HANDLED_TYPES = {
    "Model", "Unit", "Base", "Special Rule", "Spell", "Armour", "Command",
} | MAGIC_ITEM_TYPES | WEAPON_TYPES


# --- Datencontainer -----------------------------------------------------------
@dataclass
class ModelProfile:
    name: str
    stats: dict
    count: int = 1


@dataclass
class Weapon:
    name: str
    r: str = "-"
    s: str = "-"
    ap: str = "-"
    rules: str = "-"


@dataclass
class NamedText:
    name: str
    text: str


@dataclass
class Spell:
    name: str
    number: str = ""
    type: str = ""
    casting: str = ""
    rng: str = ""
    effect: str = ""


@dataclass
class Unit:
    name: str
    points: int = 0
    category: str = ""
    troop_type: str = ""
    unit_size: str = ""
    base_size: str = ""
    model_count: int = 0
    models: list = field(default_factory=list)
    weapons: list = field(default_factory=list)
    armour_items: list = field(default_factory=list)  # (name, desc)
    save: str = ""
    save_melee: str = ""   # Parry: verbesserter Wurf im Nahkampf, z.B. "4+"
    has_mount: bool = False  # Reittier gewaehlt -> Modell gilt nicht als zu Fuss
    save_parts: list = field(default_factory=list)    # menschenlesbare Teile
    special_rules: list = field(default_factory=list)  # NamedText
    magic_items: list = field(default_factory=list)    # NamedText
    spells: list = field(default_factory=list)
    command: list = field(default_factory=list)        # Namen der Kommandogruppe
    other: list = field(default_factory=list)          # (Gruppe, Name, Text) fuer
    # unbekannte typeNames (Vows, Blessings, Command-Texte ...) -> Auffang-Eimer
    weapon_rules: list = field(default_factory=list)   # Waffen-Sonderregeln (Namen,
    # z.B. Helblaster, Multiple Shots) -> Erklaerung kommt aus rule_glossary.json


# --- Hilfsfunktionen ----------------------------------------------------------
def chars_of(profile: dict) -> dict:
    """Charakteristik-Name -> Text."""
    out = {}
    for c in profile.get("characteristics", []) or []:
        out[c.get("name")] = (c.get("$text") or c.get("text") or "").strip()
    return out


def iter_selections(sel: dict):
    """Yield die Auswahl selbst und rekursiv alle Unterauswahlen."""
    yield sel
    for sub in sel.get("selections", []) or []:
        yield from iter_selections(sub)


def sum_points(sel: dict) -> int:
    total = 0
    for s in iter_selections(sel):
        for c in s.get("costs", []) or []:
            if c.get("name") == "pts" and c.get("value"):
                total += int(c["value"])
    return total


def primary_category(sel: dict) -> str:
    for c in sel.get("categories", []) or []:
        if c.get("primary") and not c.get("name", "").startswith("Faction:"):
            return c.get("name", "")
    # Fallback: irgendeine nicht-Faction Kategorie
    for c in sel.get("categories", []) or []:
        n = c.get("name", "")
        if not n.startswith("Faction:") and "Units (" not in n:
            return n
    return ""


def parse_armour_value(desc: str):
    """Findet 'Armour Value 4+', 'Armour Value : 3+', 'armour value of 2+'
    -> int. None wenn nicht vorhanden."""
    m = re.search(r"[Aa]rmour\s*[Vv]alue\s*(?:of|:)?\s*(\d+)\s*\+", desc)
    return int(m.group(1)) if m else None


def compute_save(armour_items):
    """Berechnet Best-effort den Ruestungswurf aus allen Teilen.

    Rueckgabe: (save_str, parts) wobei parts eine Liste lesbarer Strings ist.
    """
    base = None            # bestes (niedrigstes) Basisprofil
    improve = 0            # Summe der Verbesserungen (Schild, Barding ...)
    fixed = None           # feste Werte (z.B. Master Rune of Gromril)
    parts = []

    for name, desc in armour_items:
        # Wert kann in der Description ODER im Profilnamen stehen
        # (z.B. Monster-Profil heisst direkt "Armour Value : 5+").
        val = parse_armour_value(desc)
        from_name = val is None and parse_armour_value(name) is not None
        if val is None:
            val = parse_armour_value(name)
        low = desc.lower()
        is_fixed = "cannot be improved" in low
        # Label: wenn der Name schon den Wert enthaelt, nicht doppelt anhaengen
        label_val = "" if from_name else (f" ({val}+)" if val is not None else "")

        if val is not None and is_fixed:
            # Fester Wert, der nicht verbessert werden darf (z.B. Master Rune of Gromril)
            if fixed is None or val < fixed:
                fixed = val
            parts.append(f"{name} ({val}+ fest)")
        elif "improves its armour value" in low:
            # Schild / Barding: verbessert um X (Standard 1)
            m = re.search(r"by\s*(\d+)", low)
            step = int(m.group(1)) if m else 1
            improve += step
            parts.append(f"{name} (−1)" if step == 1 else f"{name} (−{step})")
        elif val is not None:
            if base is None or val < base:
                base = val
            parts.append(f"{name}{label_val}")
        else:
            # Ruestungsteil ohne erkennbaren Wert trotzdem auflisten
            parts.append(name)

    if fixed is not None:
        return f"{fixed}+", parts
    if base is None:
        return "", parts
    final = max(1, base - improve)
    return f"{final}+", parts


_TWO_HANDED_RE = re.compile(r"two.?handed|requires\s+two\s+hands", re.I)


def parry_save(u: Unit) -> str:
    """Parry: NUR Infanterie/leichte Infanterie zu Fuss mit Schild +
    Einhandwaffe (z.B. Handwaffe) hat im Nahkampf eine Ruestungsstufe mehr.
    Beritten (Reittier gewaehlt), monstroese Infanterie und Zweihandwaffen:
    kein Parry. Rueckgabe: verbesserter Wurf ("4+") oder ""."""
    if not u.save or not u.save.endswith("+"):
        return ""
    # Feste Werte ("cannot be improved") duerfen nicht verbessert werden
    if any("fest)" in p for p in u.save_parts):
        return ""
    tt = (u.troop_type or "").lower()
    if "infantry" not in tt or "monstrous" in tt:
        return ""
    # Charakter mit Reittier: Truppentyp im Export bleibt "infantry",
    # aber das Modell kaempft nicht mehr zu Fuss -> kein Parry.
    if u.has_mount:
        return ""
    if not any("shield" in (n or "").lower() for n, _ in u.armour_items):
        return ""
    # Nahkampfwaffen: mind. eine einhaendige noetig (keine Waffe gelistet
    # = Handwaffe, die in The Old World jedes Modell traegt)
    melee = [w for w in u.weapons if "combat" in (w.r or "").lower()]
    if melee and all(_TWO_HANDED_RE.search(w.rules or "") for w in melee):
        return ""
    try:
        val = int(u.save.rstrip("+"))
    except ValueError:
        return ""
    return f"{max(1, val - 1)}+"


# --- Extraktion einer Einheit -------------------------------------------------
def build_unit(sel: dict) -> Unit:
    u = Unit(name=sel.get("name", "?"))
    u.points = sum_points(sel)
    u.category = primary_category(sel)

    seen_models, seen_rules, seen_items, seen_weapons, seen_spells = (
        set(), set(), set(), set(), set())
    seen_other = set()

    for s in iter_selections(sel):
        stype = s.get("type")
        sname = s.get("name", "")
        snum = int(s.get("number", 1) or 1)

        if stype == "mount":
            u.has_mount = True

        # Kommandogruppe / Champion
        if stype in ("crew", "upgrade") and sname in (
                "Standard Bearer", "Musician", "Veteran", "Champion"):
            if sname not in u.command:
                u.command.append(sname)

        for p in s.get("profiles", []) or []:
            tn = p.get("typeName")
            pname = p.get("name", "")
            ch = chars_of(p)

            if tn == "Model":
                key = (pname, tuple(sorted(ch.items())))
                if key not in seen_models:
                    seen_models.add(key)
                    stats = {k: (ch.get(k) or "-") for k in STAT_KEYS}
                    u.models.append(ModelProfile(pname, stats, snum))
                if stype == "model" and snum > u.model_count:
                    u.model_count = snum

            elif tn == "Unit":
                u.troop_type = ch.get("Troop Type", u.troop_type)
                u.unit_size = ch.get("Unit Size", u.unit_size)

            elif tn == "Base":
                if ch.get("Base Size"):
                    u.base_size = ch["Base Size"]

            elif tn in WEAPON_TYPES:
                if pname not in seen_weapons:
                    seen_weapons.add(pname)
                    rules = ch.get("Special Rules", "-")
                    u.weapons.append(Weapon(
                        pname,
                        ch.get("R", "-"), ch.get("S", "-"),
                        ch.get("AP", "-"), rules))
                    # Referenzierte Waffen-Sonderregeln einsammeln (Namen),
                    # Erklaerung kommt spaeter aus dem Glossar.
                    if rules and rules != "-":
                        for part in rules.split(","):
                            r_name = part.strip()
                            if r_name and r_name not in u.weapon_rules:
                                u.weapon_rules.append(r_name)

            elif tn in ("Armour", "Armour Runes"):
                desc = ch.get("Description", "")
                if (pname, desc) not in u.armour_items:
                    u.armour_items.append((pname, desc))

            elif tn == "Special Rule":
                if pname not in seen_rules:
                    seen_rules.add(pname)
                    u.special_rules.append(
                        NamedText(pname, ch.get("Description", "")))

            elif tn == "Spell":
                if pname not in seen_spells:
                    seen_spells.add(pname)
                    u.spells.append(Spell(
                        pname, ch.get("Number", ""), ch.get("Type", ""),
                        ch.get("Casting Value", ""), ch.get("Range", ""),
                        ch.get("Effect", "")))

            elif tn in MAGIC_ITEM_TYPES:
                desc = ch.get("Description", "")
                if not desc and "S" in ch:  # magische Waffe -> als Waffe gefuehrt
                    continue
                if pname not in seen_items:
                    seen_items.add(pname)
                    u.magic_items.append(NamedText(pname, desc))

            else:
                # Auffang-Eimer: jedes unbekannte typeName (Vows, Blessings,
                # Command-Texte, neue Fraktions-Mechaniken ...) mit Beschreibung
                # landet auf der Rueckseite, gruppiert unter seinem typeName.
                if tn in HANDLED_TYPES:
                    continue
                desc = ch.get("Description") or ch.get("Effect") or ""
                if not desc:
                    continue
                key = (tn, pname)
                if key not in seen_other:
                    seen_other.add(key)
                    u.other.append((tn or "Sonstiges", pname, desc))

    u.save, u.save_parts = compute_save(u.armour_items)
    u.save_melee = parry_save(u)
    if not u.model_count:
        u.model_count = max((m.count for m in u.models), default=1)
    return u


def units_from_roster(data: dict, fallback_name: str = ""):
    """Kern der Listen-Auswertung: geparste NewRecruit/BattleScribe-Daten ->
    (army_name, total, units). Pfad-unabhaengig, damit auch der Browser (Pyodide)
    die geparste JSON direkt hineingeben kann."""
    roster = data["roster"]
    army_name = roster.get("name") or fallback_name
    total = next((c["value"] for c in roster.get("costs", [])
                  if c.get("name") == "pts"), "")
    units = []
    for force in roster.get("forces", []):
        for sel in force.get("selections", []):
            if sel.get("type") == "unit" or sel.get("profiles"):
                units.append(build_unit(sel))
    return army_name, total, units


def load_units(path: str):
    data = json.load(open(path, encoding="utf-8"))
    return units_from_roster(data, fallback_name=os.path.basename(path))


def build_cards_html(data: dict, fallback_name: str = "Armee",
                     stat_units=None, lore_spells=None,
                     doc_title: str = None) -> str:
    """Browser-Eintrittspunkt: geparste Listen-JSON -> fertiges Karten-HTML-
    Dokument (Vorder-/Rueckseiten). Erkennt NewRecruit/BattleScribe und Old
    World Builder automatisch. 'stat_units' = tow.whfb.app-Profile (Statlines),
    'lore_spells' = {lore-slug: [Zauber]} (Lore-Zauber), beides nur fuer OWB.
    'doc_title' (z. B. Name der hochgeladenen Datei) wird zum <title> und
    damit zum PDF-Dateinamen-Vorschlag des Browsers."""
    if is_owb(data):
        army_name, total, units = units_from_owb(data, stat_units, lore_spells)
    else:
        army_name, total, units = units_from_roster(data, fallback_name=fallback_name)
    return render_document(army_name, total, units, doc_title=doc_title)


# --- Old World Builder (OWB) Import ------------------------------------------
# OWB exportiert KEINE Statwerte (nur Namen/Punkte/Optionen/Regelnamen). Die
# Statlines werden live von tow.whfb.app geholt und als 'stat_units' (Liste der
# Fraktions-Profile) hineingegeben. Der Netzwerkabruf passiert AUSSERHALB dieses
# Moduls (Browser: JS fetch; CLI: fetch_owb_stat_units via urllib), damit das
# Modul selbst offline/netzwerkfrei bleibt (NewRecruit-Pfad unberuehrt).
OWB_CATEGORIES = [("characters", "Characters"), ("core", "Core"),
                  ("special", "Special"), ("rare", "Rare"),
                  ("mercenaries", "Mercenaries"), ("allies", "Allies")]


def is_owb(data: dict) -> bool:
    """OWB-Export erkennen: kein 'roster', aber Kategorie-Arrays."""
    return isinstance(data, dict) and "roster" not in data and any(
        k in data for k in ("characters", "core", "special", "rare"))


def _owb_norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _owb_name(o: dict) -> str:
    return o.get("name_en") or o.get("name_de") or o.get("name") or "?"


def _owb_active(lst):
    return [x for x in (lst or []) if x.get("active")]


def _stat_index(stat_units):
    """tow-Profile -> (exakt-Index, nach Laenge sortierte Liste fuer Teilstring)."""
    idx, ordered = {}, []
    for u in stat_units or []:
        f = u.get("fields", u) if isinstance(u, dict) else {}
        nm = f.get("name")
        if not nm:
            continue
        idx[_owb_norm(nm)] = f
        ordered.append((_owb_norm(nm), f))
    ordered.sort(key=lambda x: -len(x[0]))
    return idx, ordered


def _match_profile(name, idx, ordered):
    """Einheitenname -> tow-Profil: exakt, dann ' of X'-Suffix strippen, dann
    Teilstring (laengster tow-Name zuerst)."""
    n = _owb_norm(name)
    if n in idx:
        return idx[n]
    base = name
    while re.search(r"\s+of\s+", base, re.I):
        base = re.sub(r"\s+of\s+[\w\s]+$", "", base, flags=re.I).strip()
        if _owb_norm(base) in idx:
            return idx[_owb_norm(base)]
    for tn, f in ordered:
        if tn and (tn in n or n in tn):
            return f
    return None


def _profile_troop_type(prof) -> str:
    tt = prof.get("troopType")
    if isinstance(tt, list) and tt:
        return (tt[0].get("fields", {}) or {}).get("name", "") or ""
    return ""


def _add_profile_models(u: Unit, prof, fallback_name):
    for line in prof.get("unitProfile", []) or []:
        stats = {k: str(line.get(k, "-")) for k in STAT_KEYS}
        u.models.append(ModelProfile(line.get("Name") or fallback_name, stats, 1))


def _rule_summary(name: str) -> str:
    """Kurztext einer Regel allein anhand des Namens (OWB liefert keine Texte):
    rule_text.json (summaries/learned, mit Klammer-Fallback) sonst Glossar."""
    for table in (RT.get("summaries", {}), RT.get("learned", {})):
        if name in table:
            return table[name]
        base = base_rule_name(name)
        if base != name and base in table:
            return table[base]
    return glossary_lookup(name) or ""


def _owb_richtext(body) -> str:
    """Contentful-Rich-Text -> Klartext (fuer Zauber-Effekte)."""
    out = []
    def w(n):
        if isinstance(n, dict):
            if n.get("nodeType") == "text":
                out.append(n.get("value", ""))
            for c in n.get("content", []) or []:
                w(c)
    w(body or {})
    return " ".join(" ".join(out).split())


def _lore_spell_objects(spell_list):
    """tow /cards/<lore>-Zauber (Signature + 6, bereits in Reihenfolge) -> Spells.
    Signature wird mit '*' markiert, die uebrigen mit ihrer Wuerfelzahl 1-6."""
    spells = []
    for sp in spell_list or []:
        f = sp.get("fields", sp) if isinstance(sp, dict) else {}
        name = f.get("name")
        if not name:
            continue
        raw = _owb_richtext(f.get("body"))
        mc = re.match(r"Type\s+(.+?)\s+Casting Value", raw)
        category = mc.group(1).strip() if mc else ""
        me = re.search(r"\bRange\s+\S+\s+(.*)$", raw)
        effect = me.group(1).strip() if me else raw
        typ = str(f.get("type", ""))
        number = "*" if "signature" in typ.lower() else typ
        cv = f.get("castingValue")
        casting = f"{cv}+" if cv not in (None, "") else ""
        spells.append(Spell(name=name, number=number, type=category,
                            casting=casting, rng=f.get("range", "") or "",
                            effect=effect))
    return spells


def _build_owb_unit(o: dict, category: str, idx, ordered, lore_spells=None) -> Unit:
    u = Unit(name=_owb_name(o), category=category)
    try:
        u.points = int(o.get("points") or 0)
    except (TypeError, ValueError):
        u.points = 0

    # Statline live aus tow.whfb.app (per Namens-Matching)
    prof = _match_profile(u.name, idx, ordered)
    if prof:
        u.troop_type = _profile_troop_type(prof)
        _add_profile_models(u, prof, u.name)

    # Reittier (aktiv, nicht "zu Fuss"): eigene Statline-Zeile anhaengen
    for m in _owb_active(o.get("mounts")):
        nm = m.get("name_en") or m.get("name") or ""
        if nm and "foot" not in nm.lower() and "fuss" not in nm.lower():
            u.has_mount = True
            mp = _match_profile(nm, idx, ordered)
            if mp:
                _add_profile_models(u, mp, nm)

    # Waffen: nur Namen (OWB hat keine R/S/AP-Profile)
    for e in _owb_active(o.get("equipment")):
        nm = e.get("name_en") or e.get("name")
        if nm:
            u.weapons.append(Weapon(nm))

    # Ruestung -> Save-Teile (Namen)
    for a in _owb_active(o.get("armor")):
        nm = a.get("name_en") or a.get("name")
        if nm:
            u.save_parts.append(nm)

    # Magische Gegenstaende + aktive Optionen (Vows etc.) + Banner aus Kommando
    for grp in o.get("items", []) or []:
        for it in grp.get("selected", []) or []:
            nm = it.get("name_en") or it.get("name")
            if nm:
                u.magic_items.append(NamedText(nm, _rule_summary(nm)))
    for opt in _owb_active(o.get("options")):
        nm = opt.get("name_en") or opt.get("name")
        if nm:
            u.magic_items.append(NamedText(nm, _rule_summary(nm)))

    # Kommandogruppe (aktiv) + ggf. getragene magische Banner
    for c in _owb_active(o.get("command")):
        nm = c.get("name_en") or c.get("name")
        if nm:
            u.command.append(nm)
        for b in ((c.get("magic") or {}).get("selected", []) or []):
            bn = b.get("name_en") or b.get("name")
            if bn:
                u.magic_items.append(NamedText(bn, _rule_summary(bn)))

    # Sonderregeln: Namen aus specialRules (kommagetrennt) -> Kurztext per Name
    sr = o.get("specialRules") or {}
    srnames = sr.get("name_en") or sr.get("name_de") or sr.get("name") or ""
    seen = set()
    for rn in (x.strip() for x in srnames.split(",")):
        if rn and rn.casefold() not in seen:
            seen.add(rn.casefold())
            u.special_rules.append(NamedText(rn, _rule_summary(rn)))

    # Zauber: OWB nennt nur die gewaehlte Lore (Spells sind zufaellig). Wir zeigen
    # die KOMPLETTE Lore in Reihenfolge (Signature + 6) zum Auswuerfeln. Die Lore-
    # Zauber kommen live von tow.whfb.app (/cards/<lore>) ueber 'lore_spells'.
    lore = o.get("activeLore")
    if lore and lore_spells and lore_spells.get(lore):
        u.spells.extend(_lore_spell_objects(lore_spells[lore]))
    return u


def units_from_owb(data: dict, stat_units=None, lore_spells=None):
    """OWB-Export -> (army_name, total, units). 'stat_units' liefert die
    Statlines (Liste von tow.whfb.app-Profilen); ohne sie bleiben die Karten
    ohne Statline (Namen/Regeln trotzdem vorhanden)."""
    idx, ordered = _stat_index(stat_units)
    army_name = data.get("name") or "Old World Builder"
    total = data.get("points", "") or ""
    units = []
    for key, label in OWB_CATEGORIES:
        for o in data.get(key, []) or []:
            units.append(_build_owb_unit(o, label, idx, ordered, lore_spells))
    return army_name, total, units


_TOW_BUILDID = None


def _tow_get(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8")


def _tow_pageprops(path: str):
    """Holt /_next/data/<buildId>/<path>.json -> pageProps. buildId wird einmal
    pro Lauf live ermittelt (selbstheilend bei tow-Deploys)."""
    global _TOW_BUILDID
    if not _TOW_BUILDID:
        m = re.search(r'"buildId":"([^"]+)"', _tow_get("https://tow.whfb.app/"))
        _TOW_BUILDID = m.group(1) if m else None
    if not _TOW_BUILDID:
        return {}
    url = f"https://tow.whfb.app/_next/data/{_TOW_BUILDID}/{path}.json"
    return json.loads(_tow_get(url)).get("pageProps", {})


def fetch_owb_stat_units(army_slug: str):
    """CLI-Netzwerkpfad: Fraktions-Profile (Statlines) live von tow.whfb.app."""
    if not army_slug:
        return []
    try:
        return _tow_pageprops(f"army/{army_slug}").get("units", []) or []
    except Exception as e:  # noqa: BLE001
        print(f"  Hinweis: tow.whfb.app-Statabruf fehlgeschlagen ({e}) – "
              f"Karten ohne Statline.")
        return []


def fetch_owb_lore_spells(lore_slug: str):
    """CLI-Netzwerkpfad: die 7 Zauber einer Lore (Signature + 6) live von
    tow.whfb.app (/cards/<lore>), bereits in Wuerfel-Reihenfolge."""
    if not lore_slug:
        return []
    try:
        return _tow_pageprops(f"cards/{lore_slug}").get("spells", []) or []
    except Exception as e:  # noqa: BLE001
        print(f"  Hinweis: Lore-Zauberabruf '{lore_slug}' fehlgeschlagen ({e}).")
        return []


# --- Ablaufplan (Phasen-Cheatsheet) ------------------------------------------
# Phasen-Zuordnung kommt aus rule_phases.json (neben diesem Skript). Damit
# kann das Tool offline arbeiten: bekannte Regeln per Woerterbuch, unbekannte
# per Text-Heuristik aus der Beschreibung; neu Geratenes wird zurueckgeschrieben.
RULE_PHASES_PATH = os.path.join(BASE_DIR, "rule_phases.json")


def load_rule_phases():
    with open(RULE_PHASES_PATH, encoding="utf-8") as fh:
        rp = json.load(fh)
    # Namens-Schluessel (rules + learned) nach Laenge sortiert -> spezifisch zuerst
    name_map = {}
    name_map.update({k.lower(): tuple(v) for k, v in rp.get("rules", {}).items()})
    name_map.update({k.lower(): tuple(v) for k, v in rp.get("learned", {}).items()})
    rp["_name_keys"] = sorted(name_map, key=len, reverse=True)
    rp["_name_map"] = name_map
    return rp


RP = load_rule_phases()
SEQUENCE = [(p, subs) for p, subs in RP["sequence"]]
LEARNED_DIRTY = False


def save_rule_phases():
    """Schreibt neu gelernte Zuordnungen zurueck (ohne interne _-Felder)."""
    if not LEARNED_DIRTY:
        return
    out = {k: v for k, v in RP.items() if k not in ("_name_keys", "_name_map")}
    with open(RULE_PHASES_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)


def classify_rule(name: str, text: str):
    """(Phase, Unterphase) oder ('Passiv','') fuer eine Sonderregel.

    1) Name-Woerterbuch (rules + learned)  2) klar passive Textsignale
    3) Text-Heuristik (und merken)  4) sonst passiv."""
    global LEARNED_DIRTY
    low_name = name.lower()
    for key in RP["_name_keys"]:
        if key in low_name:
            return RP["_name_map"][key]
    low_text = (text or "").lower()
    for sig in RP.get("passive_text_signals", []):
        if sig in low_text:
            return ("Passiv", "")
    for kw, phase, sub in RP.get("heuristic", []):
        if kw in low_text:
            RP.setdefault("learned", {})[name] = [phase, sub]
            RP["_name_map"][low_name] = (phase, sub)
            RP["_name_keys"] = sorted(RP["_name_map"], key=len, reverse=True)
            LEARNED_DIRTY = True
            return (phase, sub)
    return ("Passiv", "")


def spell_phase(spell_type: str):
    return RP.get("spell_types", {}).get((spell_type or "").lower())


def short_effect(text: str, n: int = 150) -> str:
    """Kurzfassung eines Regeltexts: erster Satz, max. n Zeichen."""
    t = " ".join((text or "").split())
    if not t:
        return ""
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    s = m.group(1) if m else t
    if len(s) > n:
        s = s[: n - 1].rstrip() + "…"
    return s


# --- Kurztext-Datenbank (rule_text.json) -------------------------------------
# 'overrides' = vom Nutzer kuratierte Kartentexte (max. 2 Zeilen), gewinnen
# IMMER — auch gegen den Export-Text, der sonst mitten im Satz abgeschnitten
# wuerde. 'summaries'/'learned' sind NUR-Fallback fuer Regeln OHNE Text im
# Export (OWB, Waffen-/Universalregeln); 'learned' waechst nicht mehr.
RULE_TEXT_PATH = os.path.join(BASE_DIR, "rule_text.json")
SHORT_LEN = 180
OVERRIDE_MAX_LEN = 150   # 2 Zeilen auf der Kartenrueckseite (7.6pt, 136mm)


def load_rule_text():
    if os.path.exists(RULE_TEXT_PATH):
        with open(RULE_TEXT_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {"summaries": {}, "learned": {}, "overrides": {}}


RT = load_rule_text()
RT_DIRTY = False


def save_rule_text():
    if not RT_DIRTY:
        return
    out = {k: v for k, v in RT.items() if not k.startswith("_") or k == "_comment"}
    with open(RULE_TEXT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)


def override_text(name: str) -> str:
    """Vom Nutzer kuratierter Kartentext (rule_text.json 'overrides',
    mit Klammer-Fallback) oder ''."""
    ov = RT.get("overrides", {})
    if name in ov:
        return ov[name]
    base = base_rule_name(name)
    if base != name and base in ov:
        return ov[base]
    return ""


def short_text(name: str, full: str) -> str:
    """Kurzfassung einer Regel. Ein kuratierter 'overrides'-Text gewinnt
    immer (bewusste Nutzer-Entscheidung, passt in 2 Zeilen). Sonst ist die
    Export-JSON die Quelle der Wahrheit: liefert sie einen Text, wird dieser
    frisch gekuerzt angezeigt -- nichts wird eingefroren. Nur ohne Export-Text
    greift die Bibliothek (summaries -> learned -> Glossar)."""
    ov = override_text(name)
    if ov:
        return ov
    if full and full.strip():
        return short_effect(full, SHORT_LEN)
    return _rule_summary(name)


# --- Glossar (rule_glossary.json) --------------------------------------------
# Erklaerungen fuer Waffen-/Universal-Sonderregeln, die NewRecruit NICHT
# exportiert (nur Namen im Waffenprofil). Quelle: tow.whfb.app/special-rules.
RULE_GLOSSARY_PATH = os.path.join(BASE_DIR, "rule_glossary.json")


def load_glossary():
    if os.path.exists(RULE_GLOSSARY_PATH):
        with open(RULE_GLOSSARY_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("glossary", {})
    return {}


GLOSSARY = load_glossary()


def base_rule_name(name: str) -> str:
    """Regelname ohne (X)-Klammer, z.B. 'Armour Bane (2)' -> 'Armour Bane'."""
    return re.sub(r"\s*\(.*?\)", "", name or "").strip()


def glossary_lookup(name: str):
    """Erklaerung einer (Waffen-)Sonderregel oder None."""
    if name in GLOSSARY:
        return GLOSSARY[name]
    return GLOSSARY.get(base_rule_name(name))


def build_plan(units):
    """Erzeugt {(phase, sub): {name:[effekt,[einheiten]]}} und passive Liste."""
    slots = {}
    passive = {}  # name -> [effekt, [einheiten]]

    def add_passive(name, effekt, unit):
        p = passive.setdefault(name, [effekt, []])
        if unit not in p[1]:
            p[1].append(unit)

    def add(phase, sub, name, effekt, unit):
        if phase == "Passiv":
            add_passive(name, effekt, unit)
            return
        slots.setdefault((phase, sub), {})
        e = slots[(phase, sub)].setdefault(name, [effekt, []])
        if unit not in e[1]:
            e[1].append(unit)

    for u in units:
        for r in u.special_rules:
            phase, sub = classify_rule(r.name, r.text)
            add(phase, sub, r.name, short_text(r.name, r.text), u.name)
        for s in u.spells:
            ph = spell_phase(s.type)
            meta = ", ".join(filter(None, [
                f"Cast {s.casting}" if s.casting else "", s.rng]))
            eff = (meta + " – " if meta else "") + short_text(s.name, s.effect)
            if ph:
                add(ph[0], ph[1], s.name, eff, u.name)
            else:
                add_passive(s.name, eff, u.name)
        # Fernkampfwaffen -> Einheit darf in der Shooting-Phase schiessen,
        # auch ohne eigene Sonderregel (Reichweite enthaelt eine Zahl).
        for w in u.weapons:
            if re.search(r"\d", w.r or ""):
                parts = [f"R {w.r}", f"S {w.s}", f"AP {w.ap}"]
                eff = ", ".join(p for p in parts if not p.endswith("-"))
                add("Shooting", "Choose Target", w.name, eff, u.name)
    return slots, passive


def render_plan_document(army_name, total, units, doc_title=None) -> str:
    slots, passive = build_plan(units)
    rows = ""
    for phase, subs in SEQUENCE:
        phase_rows = ""
        first = True
        for sub in subs:
            entries = slots.get((phase, sub), {})
            if entries:
                aktion = "<br>".join(
                    f"<b>{esc(n)}:</b> {hl(v[0])}" if v[0] else f"<b>{esc(n)}</b>"
                    for n, v in entries.items())
                # Einheiten der ganzen Zelle: jede nur einmal nennen
                cell_units = []
                for v in entries.values():
                    for x in v[1]:
                        if x not in cell_units:
                            cell_units.append(x)
                einheit = ", ".join(esc(x) for x in cell_units)
            else:
                aktion = einheit = ""
            ph_cell = (f"<td class='ph' rowspan='{len(subs)}'>{esc(phase)}</td>"
                       if first else "")
            phase_rows += (f"<tr>{ph_cell}<td class='sub'>{esc(sub)}</td>"
                           f"<td class='akt'>{aktion}</td>"
                           f"<td class='unit'>{einheit}</td></tr>")
            first = False
        rows += phase_rows

    # Nicht einsortierte / rein passive Regeln werden im Plan bewusst NICHT
    # gelistet (stehen ohnehin auf den Karten). Der Plan zeigt nur, was in einer
    # Phase aktiv passiert.

    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>{esc(doc_title or f"{army_name} – Ablaufplan")}</title>
<style>{PLAN_CSS}</style></head>
<body>
<h1>{esc(army_name)} <span class='pts'>({total} Pkt)</span> – Ablaufplan</h1>
<table class="plan">
  <tr><th>Phase</th><th>Unterphase</th><th>Aktion &amp; Sonderfertigkeit</th><th>Einheit</th></tr>
  {rows}
</table>
<p class="note">Automatisch erzeugt: Zauber nach Typ, Sonderregeln per Stichwort-Zuordnung (best-effort).
Vor dem Spiel kurz gegenprüfen.</p>
</body></html>"""


PLAN_CSS = """
@page { size: A4 portrait; margin: 12mm; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: 'Segoe UI', Arial, sans-serif; margin:0; color:#1c2b33;
  font-size: 9.5pt; }
h1 { font-size: 16pt; margin: 0 0 4mm; }
h1 .pts { color:#888; font-weight:400; font-size: 11pt; }
h2 { font-size: 11pt; margin: 5mm 0 2mm; border-bottom:1px solid #aaa; }
table.plan { border-collapse: collapse; width: 100%; }
table.plan th, table.plan td { border:1px solid #99a; padding:2px 5px;
  vertical-align: top; text-align:left; }
table.plan th { background:#2b4d5e; color:#fff; font-size:9pt; }
td.ph { background:#dfe8ec; font-weight:700; width:18mm; vertical-align:middle; }
td.sub { background:#f1f4f6; width:34mm; font-weight:600; }
td.akt { line-height:1.3; }
td.akt .hl { background:#ffe9a8; color:#1c2b33; font-weight:700;
  padding:0 1px; border-radius:2px; }
td.unit { width:30mm; color:#335; font-size:8.5pt; }
ul.passive { columns:2; column-gap:8mm; margin:0; padding-left:5mm;
  font-size:8.5pt; line-height:1.35; }
ul.passive li { break-inside:avoid; margin-bottom:1mm; }
.pu { color:#777; }
.note { font-size:7.5pt; color:#888; margin-top:5mm; }
"""


# --- HTML-Rendering -----------------------------------------------------------
def esc(x) -> str:
    return html.escape(str(x or ""))


# Hebt spielentscheidende Stellen im Regeltext hervor:
#  - Wuerfelausdruecke (D6, 2D6, D3+1 ...), optional mit folgendem Schluesselwort
#    (hits, wounds, attacks, Strength) -> "2D6 hits", "D3 wounds"
#  - Reichweiten (12") , Staerke (S5 / S+2 / Strength 5), "4+ to wound"
#  - "kein Rettungswurf"-Phrasen (no armour save, no save, no armour roll ...)
HL_RE = re.compile(
    r"\b\d*D\d+(?:[+-]\d+)?(?:\s+(?:[Hh]its?|[Ww]ounds?|[Aa]ttacks?|[Ss]trength|[Tt]oughness))?"
    r"|\d+\"(?:\s*range)?"
    r"|\bS\+?\d+\b"
    r"|(?i:strength\s+\d+)"
    r"|\d\+\s+to\s+(?i:hit|wound|cast|be\s+hit)"
    r"|(?i:no\s+(?:armou?r\s+)?(?:saves?|rolls?)(?:\s+of\s+any\s+kind)?(?:\s+allowed)?)"
    r"|(?i:without\s+(?:an?\s+)?(?:armou?r\s+)?save)"
    r"|(?i:armou?r\s+saves?\s+(?:are\s+)?(?:not\s+allowed|ignored))"
    r"|(?i:ignor(?:e|es|ing)\s+(?:all\s+)?armou?r\s+saves?)"
)


def hl(text) -> str:
    """Escapen UND wichtige Stellen (Wuerfel/Reichweite/Staerke/kein-Save) hervorheben.

    Escaping ohne Quote-Umwandlung, damit Reichweiten wie 12\" erhalten bleiben
    (hl() wird nur fuer Textinhalt verwendet, nie in HTML-Attributen)."""
    return HL_RE.sub(lambda m: f"<span class='hl'>{m.group(0)}</span>",
                     html.escape(str(text or ""), quote=False))


def render_statline(u: Unit) -> str:
    rows = ""
    multi = len(u.models) > 1
    for m in u.models:
        cells = "".join(f"<td>{esc(m.stats[k])}</td>" for k in STAT_KEYS)
        label = f"<td class='mname'>{esc(m.name)}</td>" if multi else \
                "<td class='mname'></td>"
        rows += f"<tr>{label}{cells}</tr>"
    head = "<th></th>" + "".join(f"<th>{k}</th>" for k in STAT_KEYS)
    return f"<table class='stats'><tr>{head}</tr>{rows}</table>"


def render_weapons(u: Unit) -> str:
    if not u.weapons:
        return ""
    rows = ""
    for w in u.weapons:
        rows += (f"<tr><td class='wn'>{esc(w.name)}</td><td>{esc(w.r)}</td>"
                 f"<td>{esc(w.s)}</td><td>{esc(w.ap)}</td>"
                 f"<td class='wrules'>{esc(w.rules) if w.rules not in ('-','') else ''}</td></tr>")
    return ("<table class='weapons'><tr><th>Waffe</th><th>R</th><th>S</th>"
            f"<th>AP</th><th>Sonderregeln</th></tr>{rows}</table>")


def render_front(u: Unit) -> str:
    meta = []
    if u.troop_type:
        meta.append(esc(u.troop_type))
    if u.base_size:
        meta.append(f"Base {esc(u.base_size)}")
    if u.model_count:
        meta.append(f"{u.model_count} Modelle")
    meta_html = " &middot; ".join(meta)

    save_html = ""
    if u.save:
        nk = (f"<span class='shieldnk'>({esc(u.save_melee)})*</span>"
              if u.save_melee else "")
        save_html = ("<div class='shield'>"
                     "<span class='shieldlbl'>Total<br>Armour</span>"
                     f"<span class='shieldval'>{esc(u.save)}</span>{nk}</div>")

    save_parts = ""
    if u.save_parts:
        save_parts = ("<div class='saveparts'>Save: "
                      + ", ".join(esc(p) for p in u.save_parts) + "</div>")
    if u.save_melee:
        save_parts += ("<div class='saveparts parrynote'>* Parry "
                       "(Schild + Einhandwaffe): Total Armour im Nahkampf "
                       f"+1 &rarr; {esc(u.save_melee)}</div>")

    rule_names = ""
    if u.special_rules:
        rule_names = ("<div class='rulenames'><b>Sonderregeln:</b> "
                      + ", ".join(esc(r.name) for r in u.special_rules) + "</div>")

    items = ""
    if u.magic_items:
        items = ("<div class='items'><b>Ausr&uuml;stung/Magie:</b> "
                 + ", ".join(esc(i.name) for i in u.magic_items) + "</div>")

    command = ""
    if u.command:
        command = ("<div class='command'><b>Kommando:</b> "
                   + ", ".join(esc(c) for c in u.command) + "</div>")

    spells = ""
    if u.spells:
        spells = ("<div class='spelllist'><b>Zauber:</b> "
                  + ", ".join(esc(s.name) for s in u.spells) + "</div>")

    return f"""
    <div class="card front"><div class="fit">
      <div class="cardhead">
        <div class="title">{esc(u.name)}</div>
        <div class="pts">{u.points} Pkt</div>
      </div>
      <div class="cat">{esc(u.category)} &nbsp; {meta_html}</div>
      <div class="statrow">
        {render_statline(u)}
        {save_html}
      </div>
      {save_parts}
      {render_weapons(u)}
      {command}
      {items}
      {spells}
      {rule_names}
    </div></div>"""


def render_back(u: Unit) -> str:
    blocks = ""
    for r in u.special_rules:
        if r.text:
            blocks += (f"<div class='rule'><span class='rn'>{esc(r.name)}:</span> "
                       f"<span class='rt'>{hl(short_text(r.name, r.text))}</span></div>")
        else:
            blocks += f"<div class='rule'><span class='rn'>{esc(r.name)}</span></div>"

    for i in u.magic_items:
        if i.text:
            blocks += (f"<div class='rule item'><span class='rn'>{esc(i.name)}:</span> "
                       f"<span class='rt'>{hl(short_text(i.name, i.text))}</span></div>")

    for s in u.spells:
        info = " &middot; ".join(filter(None, [
            f"GW {esc(s.casting)}" if s.casting else "",
            esc(s.type), esc(s.rng)]))
        num = (f"<span class='spellnum'>{esc(s.number)}</span> "
               if s.number else "")
        blocks += (f"<div class='rule spell'><span class='rn'>{num}{esc(s.name)}</span>"
                   f"<span class='spellmeta'>{info}</span>"
                   f"<div class='rt'>{hl(short_text(s.name, s.effect))}</div></div>")

    # Auffang-Eimer: unbekannte Typen, gruppiert unter ihrer typeName-Ueberschrift
    last_group = None
    for group, name, text in u.other:
        if group != last_group:
            blocks += f"<div class='grouphd'>{esc(group)}</div>"
            last_group = group
        blocks += (f"<div class='rule other'><span class='rn'>{esc(name)}:</span> "
                   f"<span class='rt'>{hl(short_text(name, text))}</span></div>")

    # Waffen-Sonderregeln (Helblaster, Multiple Shots ...): Erklaerung aus dem
    # Glossar. Was bereits oben als Sonderregel erklaert ist, wird uebersprungen.
    shown = {base_rule_name(r.name).casefold() for r in u.special_rules}
    wpn_blocks = ""
    for wr in u.weapon_rules:
        if base_rule_name(wr).casefold() in shown:
            continue
        desc = glossary_lookup(wr)
        if desc:
            wpn_blocks += (f"<div class='rule wpn'><span class='rn'>{esc(wr)}:</span> "
                           f"<span class='rt'>{hl(desc)}</span></div>")
        else:
            wpn_blocks += (f"<div class='rule wpn'><span class='rn'>{esc(wr)}</span> "
                           f"<span class='lookup'>– nachschlagen</span></div>")
    if wpn_blocks:
        blocks += "<div class='grouphd'>Waffenregeln</div>" + wpn_blocks

    if not blocks:
        blocks = "<div class='rule'><i>Keine Sonderregeln</i></div>"

    return f"""
    <div class="card back"><div class="fit">
      <div class="cardhead"><div class="title">{esc(u.name)}</div>
        <div class="pts back">Regeln</div></div>
      <div class="rules">{blocks}</div>
    </div></div>"""


CSS = """
@page { size: A4 portrait; margin: 0; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; background:#ddd; }
.page {
  width: 210mm; height: 297mm; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 4mm;
  page-break-after: always; }
.page:last-child { page-break-after: auto; }
.card {
  width: 148mm; height: 105mm; padding: 5mm 6mm;
  background: #1f5066; color: #f3ede0; overflow: hidden;
  border: 1px solid #0d2b38; page-break-inside: avoid; position: relative;
}
.card.back { background: #244a2c; }
.fit { width: 100%; transform-origin: top left; }
.cardhead { display:flex; justify-content:space-between; align-items:baseline;
  border-bottom: 2px solid #d8c79b; padding-bottom:2mm; margin-bottom:2mm; }
.title { font-size: 18pt; font-weight: 700; letter-spacing:.3px; }
.pts { font-size: 12pt; font-weight:700; color:#f0d27a; }
.cat { font-size: 8.5pt; color:#cfe0e8; margin-bottom: 2.5mm; font-style:italic; }
.statrow { display:flex; align-items:flex-start; gap:4mm; }
table.stats { border-collapse: collapse; flex:1; }
table.stats th, table.stats td {
  border:1px solid #d8c79b; padding:1px 4px; text-align:center; font-size:10pt; }
table.stats th { background:#d8c79b; color:#1f3a47; font-weight:700; }
table.stats td.mname { text-align:left; font-size:8pt; max-width:24mm; }
.shield {
  width:19mm; height:22mm; flex:0 0 auto; display:flex; flex-direction:column;
  align-items:center; justify-content:flex-start; padding-top:1.6mm;
  color:#1f3a47; background:#c9cdd0;
  clip-path: polygon(0 0,100% 0,100% 60%,50% 100%,0 60%); }
.shieldlbl { font-size:5.2pt; font-weight:700; line-height:1.05;
  letter-spacing:.2px; text-transform:uppercase; text-align:center; }
.shieldval { font-weight:800; font-size:13pt; line-height:1; margin-top:.3mm; }
.shieldnk  { font-weight:700; font-size:6pt; line-height:1; margin-top:.4mm; }
.parrynote { margin-top:-1.2mm; }
.saveparts { font-size:7.5pt; color:#bcd; margin:1mm 0 2mm; }
table.weapons { border-collapse:collapse; width:100%; margin:1.5mm 0; }
table.weapons th, table.weapons td {
  border:1px solid #4a7a8c; padding:1px 4px; font-size:8pt; }
table.weapons th { background:#3a6678; }
table.weapons td.wn { font-weight:600; }
table.weapons td.wrules { font-size:7pt; }
.command,.items,.spelllist,.rulenames {
  font-size:8pt; margin:1.2mm 0; line-height:1.25; }
.rulenames { margin-top:auto; }
/* Spaltenzahl der Rueckseite: 1 = besser lesbar, 2 = kompakter (weniger Schrumpfen) */
.rules { font-size:7.6pt; line-height:1.3; columns:1; column-gap:6mm; }
.rule { margin-bottom:1.6mm; break-inside:avoid; }
.rn { font-weight:700; color:#f0d27a; }
.rule.item .rn { color:#9ad; }
.rule.spell .rn { color:#e8a; }
.rule.other .rn { color:#cda; }
.rule.wpn .rn { color:#f0b27a; }
.rule.wpn .lookup { font-size:7pt; color:#9ab; font-style:italic; }
.rt .hl { color:#ffdf6b; font-weight:700; }
.grouphd { font-weight:700; font-size:7.2pt; letter-spacing:.5px;
  text-transform:uppercase; color:#bcd; border-top:1px solid #4a7a8c;
  margin:1.6mm 0 1mm; padding-top:1mm; break-after:avoid; }
.spellmeta { font-size:7pt; color:#cea; margin-left:3px; }
.spellnum { display:inline-block; min-width:1.2em; text-align:center;
  font-weight:800; color:#1f3a47; background:#e8a; border-radius:3px;
  padding:0 2px; margin-right:2px; font-size:7pt; }
/* Schnellreferenz-Karte (statische Kernregeln) */
.refwrap { display:flex; gap:3mm; align-items:flex-start; }
.refcol { flex:1; min-width:0; }
.reftbl { border-collapse:collapse; width:100%; margin:0 0 1mm; }
.reftbl caption { font-weight:700; font-size:7.4pt; text-align:left;
  text-transform:uppercase; letter-spacing:.4px; color:#f0d27a; padding:1.5mm 0 .6mm; }
.card.back .reftbl caption { color:#bfe3c4; }
.reftbl th, .reftbl td { border:1px solid #4a7a8c; text-align:center;
  font-size:6.4pt; padding:0; line-height:1.5; }
.card.back .reftbl th, .card.back .reftbl td { border-color:#3f6e49; }
.reftbl th { background:#3a6678; color:#fff; font-weight:700; }
.card.back .reftbl th { background:#3a6e48; }
.reftbl td.rh { background:#3a6678; color:#fff; font-weight:700; }
.card.back .reftbl td.rh { background:#3a6e48; }
.reftbl td.no { color:#7da; opacity:.45; }
.refnote { font-size:6.6pt; color:#bcd; margin:.4mm 0 1.5mm; line-height:1.3; }
.card.back .refnote { color:#bfe3c4; }
.refblock { margin-bottom:1.4mm; font-size:7.2pt; line-height:1.3; break-inside:avoid; }
.refblock .rh2 { font-weight:700; color:#f0d27a; }
.card.back .refblock .rh2 { color:#9be0a6; }
.refblock .hl { color:#ffdf6b; font-weight:700; }
/* A4-Version der Schnellreferenz: dieselbe Karte, auf A4 hochskaliert und um
   90 Grad gedreht -> der Inhalt liegt quer auf dem A4-Blatt (Querformat).
   Die Rueckseite dreht gegenlaeufig (-90), damit beim Duplexdruck (Wenden an
   der langen Kante) beide Seiten gleich herum lesbar sind. */
.page.a4ref .card { transform: rotate(90deg) scale(1.97); }
.page.a4ref.vs .card { transform: rotate(-90deg) scale(1.97); }
@media print { body { background:#fff; } }
/* Tintensparender Schwarz-Weiss-Modus: helle Karte, dunkle Schrift.
   Wird per Klasse 'bw' am <html> der Vorder-/Rueckseiten-Dokumente aktiviert. */
.bw .card, .bw .card.back { background:#fff !important; color:#111 !important; }
.bw .card * { color:#111 !important; background-color:transparent !important;
  border-color:#777 !important; }
.bw .cardhead { border-bottom-color:#111 !important; }
.bw .title, .bw .pts, .bw .rn, .bw .reftbl caption,
.bw .refblock .rh2 { color:#000 !important; font-weight:700; }
.bw table.stats th, .bw table.weapons th, .bw table.plan th, .bw td.ph, .bw td.sub,
.bw .reftbl th, .bw .reftbl td.rh, .bw .shield { background:#e7e7e7 !important; }
.bw .shield { border:1px solid #111 !important; }
.bw .hl { color:#000 !important; font-weight:700; text-decoration:underline; }
.bw .reftbl td.no { color:#777 !important; }
"""


# Verkleinert bei Bedarf den Inhalt jeder Karte, damit nichts abgeschnitten wird.
FIT_JS = """
function fitCards(){
  document.querySelectorAll('.card').forEach(function(card){
    var fit = card.querySelector('.fit'); if(!fit) return;
    fit.style.transform=''; fit.style.width='';
    var cs=getComputedStyle(card);
    var availH=card.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    var availW=card.clientWidth  - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    // Rueckseite IMMER einspaltig (2 Spalten waeren zu klein zum Lesen).
    // Passt der Inhalt nicht, wird nur die Schrift herunterskaliert.
    var rules=card.querySelector('.rules');
    if(rules) rules.style.columnCount='1';
    var k=Math.min(availH/fit.scrollHeight, availW/fit.scrollWidth, 1);
    if(k<1){ fit.style.transform='scale('+k.toFixed(3)+')';
             fit.style.width=(100/k)+'%'; }
  });
}
window.addEventListener('load', fitCards);
window.addEventListener('beforeprint', fitCards);
"""


# --- Schnellreferenz-Karte ---------------------------------------------------
# Statische Kernregeln (aendern sich nie). Werte gegen die offizielle TOW-
# Referenz geprueft: tow.whfb.app/quick-reference (Treffertabellen, Kampfergebnis)
# und tow.whfb.app/the-movement-phase/determine-charge-range (Charge);
# Break/Flee/Panic aus dem TOW-Regelbuch (Kampf- bzw. Psychologie-Phase).

# To-Hit Nahkampf: Zeile = WS Angreifer, Spalte = WS Verteidiger (1..10)
HIT_MELEE = [
    [4,4,5,5,5,5,5,5,5,5],
    [3,4,4,4,5,5,5,5,5,5],
    [2,3,4,4,4,4,5,5,5,5],
    [2,3,3,4,4,4,4,4,5,5],
    [2,2,3,3,4,4,4,4,4,4],
    [2,2,3,3,3,4,4,4,4,4],
    [2,2,2,3,3,3,4,4,4,4],
    [2,2,2,3,3,3,3,4,4,4],
    [2,2,2,2,3,3,3,3,4,4],
    [2,2,2,2,3,3,3,3,3,4],
]
# To-Wound: Zeile = Staerke, Spalte = Widerstand (1..10); 0 = kann nicht verwunden
WOUND = [
    [4,5,6,6,6,6,0,0,0,0],
    [3,4,5,6,6,6,6,0,0,0],
    [2,3,4,5,6,6,6,6,0,0],
    [2,2,3,4,5,6,6,6,6,0],
    [2,2,2,3,4,5,6,6,6,6],
    [2,2,2,2,3,4,5,6,6,6],
    [2,2,2,2,2,3,4,5,6,6],
    [2,2,2,2,2,2,3,4,5,6],
    [2,2,2,2,2,2,2,3,4,5],
    [2,2,2,2,2,2,2,2,3,4],
]
# Schuss-To-Hit nach Ballistic Skill 1..10 (BS6+ trifft auf 2+ mit Wiederholung)
HIT_SHOOT = [6,5,4,3,2,2,2,2,2,2]


def _grid_html(caption, corner, matrix, accent_diag=True):
    head = "".join(f"<th>{c}</th>" for c in range(1, 11))
    rows = ""
    for i, row in enumerate(matrix):
        cells = ""
        for j, v in enumerate(row):
            if v == 0:
                cells += "<td class='no'>–</td>"
            else:
                cells += f"<td>{v}+</td>"
        rows += f"<tr><td class='rh'>{i+1}</td>{cells}</tr>"
    return (f"<table class='reftbl'><caption>{caption}</caption>"
            f"<tr><th>{corner}</th>{head}</tr>{rows}</table>")


def render_reference_front() -> str:
    melee = _grid_html("To Hit – Nahkampf (WS Angr. ▸ / WS Vert. ▾)", "A\\V", HIT_MELEE)
    wound = _grid_html("To Wound (Stärke ▸ / Widerstand ▾)", "S\\T", WOUND)
    shoot_head = "".join(f"<th>{b}</th>" for b in range(1, 11))
    shoot_row = "".join(f"<td>{v}+</td>" for v in HIT_SHOOT)
    shoot = (f"<table class='reftbl'><caption>To Hit – Schießen (nach BS)</caption>"
             f"<tr><th>BS</th>{shoot_head}</tr>"
             f"<tr><td class='rh'>D6</td>{shoot_row}</tr></table>")
    mods = ("<div class='refnote'><b>Schuss-Modifikatoren:</b> "
            "−1 Bewegt &amp; Schießen · −1 Lange Reichweite · −1 Stand &amp; Shoot · "
            "−1 Ziel in Teildeckung · −2 Ziel in voller Deckung. "
            "BS&nbsp;6+ trifft auf 2+ und darf Fehlwürfe wiederholen. "
            "Natürliche 1 verwundet nie.</div>")
    return f"""
    <div class="card front"><div class="fit">
      <div class="cardhead"><div class="title">Schnellreferenz – Kampf</div>
        <div class="pts">Würfeltabellen</div></div>
      {melee}
      <div class="refwrap">
        <div class="refcol">{wound}</div>
      </div>
      {shoot}
      {mods}
    </div></div>"""


def _refblock(title, body):
    return f"<div class='refblock'><span class='rh2'>{title}:</span> {body}</div>"


def render_reference_back() -> str:
    blocks = ""
    blocks += _refblock("Leadership-Test",
        "2W6 würfeln; <span class='hl'>≤ Leadership</span> = bestanden.")
    blocks += _refblock("Charge",
        "Charge-Reichweite = <span class='hl'>Movement + Charge-Wurf</span> "
        "(2W6, niedrigeren streichen → höchster Würfel). Swiftstride: 3W6, niedrigsten streichen, +3\".")
    blocks += _refblock("Flucht / Verfolgung",
        "Flieht <span class='hl'>2W6\"</span>; Verfolgung <span class='hl'>2W6\"</span>. "
        "Erreicht die Verfolgung die Fliehenden, sind sie vernichtet. "
        "Über die Tischkante = vernichtet.")
    blocks += _refblock("Restraint-Test",
        "Leadership-Test bestehen, um <i>nicht</i> zu verfolgen/nachzurücken "
        "(stattdessen gratis neu ausrichten).")
    blocks += _refblock("Rally",
        "Zu Beginn ihres Zuges machen fliehende Einheiten einen Rally-Test "
        "(Leadership-Test); bestanden = sammeln &amp; neu formieren.")
    blocks += _refblock("Break-Test (Kampf verloren)",
        "2W6 + (Kampfergebnis-Differenz). "
        "<b>Roher Wurf &gt; LD</b> → Einheit bricht &amp; flieht. "
        "<b>Roh ≤ LD, modifiziert &gt; LD</b> → Fall Back in Good Order. "
        "<b>Modifiziert ≤ LD</b> (oder Pasch 1) → Give Ground.")
    blocks += _refblock("Panic-Test",
        "Auslöser: <span class='hl'>25%+ Verluste</span> in einer Phase außerhalb des Nahkampfs; "
        "befreundete Einheit (US&nbsp;5+) <span class='hl'>innerhalb 6\"</span> bricht/flieht; "
        "befreundete Einheit innerhalb 6\" vernichtet. 2W6 ≤ LD = bestanden.")
    cr = ("<table class='reftbl'><caption>Kampfergebnis (+Punkte)</caption>"
          "<tr><th>Faktor</th><th>Pkt</th></tr>"
          "<tr><td class='rh'>Verursachte Wunden</td><td>+1 je</td></tr>"
          "<tr><td class='rh'>Glied-Bonus</td><td>+1 je Glied</td></tr>"
          "<tr><td class='rh'>Standarte</td><td>+1</td></tr>"
          "<tr><td class='rh'>Armee-Standarte (BSB)</td><td>+1</td></tr>"
          "<tr><td class='rh'>Flankenangriff</td><td>+1</td></tr>"
          "<tr><td class='rh'>Rückenangriff</td><td>+2</td></tr>"
          "<tr><td class='rh'>Höherer Stand (High Ground)</td><td>+1</td></tr>"
          "<tr><td class='rh'>Overkill (Herausforderung)</td><td>+1 je Überwunde</td></tr>"
          "<tr><td class='rh'>Höhere Unit Strength (Masse)</td><td>+1</td></tr>"
          "</table>")
    return f"""
    <div class="card back"><div class="fit">
      <div class="cardhead"><div class="title">Schnellreferenz – Würfe</div>
        <div class="pts back">Abläufe</div></div>
      {blocks}
      {cr}
    </div></div>"""


def render_reference_document() -> str:
    # Seiten 1+2: A6-Karte (fuers Karten-Deck). Seiten 3+4: dieselbe Referenz
    # als A4-Querformat-Blatt (hochskaliert, siehe CSS .a4ref) - wird beim
    # Drucken/PDF-Export automatisch mit ausgegeben.
    front = render_reference_front()
    back = render_reference_back()
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>Schnellreferenz – Kernregeln</title>
<style>{CSS}</style></head>
<body>
<div class="page">{front}</div>
<div class="page">{back}</div>
<div class="page a4ref">{front}</div>
<div class="page a4ref vs">{back}</div>
<script>{FIT_JS}</script>
</body></html>"""


def render_document(army_name, total, units, doc_title=None) -> str:
    # 2 Karten pro A4-Blatt. Pro Paar: ein Blatt mit beiden Vorderseiten,
    # danach ein Blatt mit den beiden Rueckseiten in gleicher Position.
    # Beim Duplexdruck (Wenden an der langen Kante) liegen Front/Back deckungsgleich.
    pages = ""
    for i in range(0, len(units), 2):
        pair = units[i:i + 2]
        fronts = "".join(render_front(u) for u in pair)
        backs = "".join(render_back(u) for u in pair)
        pages += f'<div class="page">{fronts}</div>'
        pages += f'<div class="page">{backs}</div>'
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>{esc(doc_title or f"{army_name} – Unit Cards ({total} Pkt)")}</title>
<style>{CSS}</style></head>
<body>
{pages}
<script>{FIT_JS}</script>
</body></html>"""


def process_file(path: str, outdir: str):
    data = json.load(open(path, encoding="utf-8"))
    if is_owb(data):
        slug = data.get("army", "")
        print(f"  Old World Builder erkannt – hole Statwerte fuer '{slug}' "
              f"live von tow.whfb.app ...")
        stat_units = fetch_owb_stat_units(slug)
        lores = {o.get("activeLore") for grp in OWB_CATEGORIES
                 for o in data.get(grp[0], []) or [] if o.get("activeLore")}
        lore_spells = {}
        for lore in sorted(lores):
            print(f"    Lore-Zauber '{lore}' ...")
            lore_spells[lore] = fetch_owb_lore_spells(lore)
        army_name, total, units = units_from_owb(data, stat_units, lore_spells)
    else:
        army_name, total, units = units_from_roster(
            data, fallback_name=os.path.basename(path))
    # Dokumenttitel = Name der Eingabedatei: der Browser schlaegt beim
    # Drucken/PDF-Speichern den Seitentitel als Dateinamen vor.
    base = os.path.splitext(os.path.basename(path))[0]
    doc = render_document(army_name, total, units, doc_title=base)
    out = os.path.join(outdir, base + ".html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"  {len(units):2d} Karten  ->  {out}")
    # Ablaufplan als eigene Datei
    plan = render_plan_document(army_name, total, units,
                                doc_title=base + "_plan")
    plan_out = os.path.join(outdir, base + "_plan.html")
    with open(plan_out, "w", encoding="utf-8") as fh:
        fh.write(plan)
    print(f"      Ablaufplan  ->  {plan_out}")
    return out


def collect_lists(args):
    """Loest CLI-Argumente zu JSON-Dateien auf. Jedes Argument darf eine Datei
    ODER ein Ordner sein. Ohne Argumente: alle Listen aus lists/."""
    targets = args or [DEFAULT_INPUT_DIR]
    files = []
    for t in targets:
        if os.path.isdir(t):
            files += sorted(glob.glob(os.path.join(t, "*.json")))
        else:
            files.append(t)
    # Windows-Downloadmarker rausfiltern, Duplikate vermeiden
    seen, result = set(), []
    for f in files:
        if f.endswith("Zone.Identifier") or f in seen:
            continue
        seen.add(f)
        result.append(f)
    return result


def main():
    outdir = OUTPUT_DIR
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(DEFAULT_INPUT_DIR, exist_ok=True)
    files = collect_lists([a for a in sys.argv[1:] if a])
    if not files:
        print(f"Keine JSON-Liste gefunden. Lege deine NewRecruit-Exporte in:"
              f"\n  {DEFAULT_INPUT_DIR}\nund starte erneut.")
        return
    for f in files:
        print(f"Verarbeite: {f}")
        try:
            process_file(f, outdir)
        except Exception as e:  # noqa: BLE001
            print(f"  FEHLER: {e}")
    # Schnellreferenz-Karte (statische Kernregeln) – einmal pro Lauf
    ref_out = os.path.join(outdir, "Schnellreferenz.html")
    with open(ref_out, "w", encoding="utf-8") as fh:
        fh.write(render_reference_document())
    print(f"Schnellreferenz  ->  {ref_out}")
    save_rule_phases()  # neu gelernte Phasen-Zuordnungen sichern
    save_rule_text()    # neu gekuerzte Regeltexte sichern


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warhammer Card Creator – Testsuite.

Läuft vor JEDEM Commit (hooks/pre-commit, aktivieren mit
`git config core.hooksPath hooks`) und in der CI. Regeln:
kein Commit ohne grüne Tests; jeder Fix bekommt einen Regressionstest.

Aufruf:  python3 run_tests.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((True, name, ""))
        print(f"  ✓ {name}")
    except Exception as e:
        RESULTS.append((False, name, str(e)))
        print(f"  ✗ {name}: {e}")


# ── 1. Syntax + Lint ─────────────────────────────────────────────────────────
PY_FILES = ["generate_cards.py", "run_tests.py"]


def t_py_syntax():
    import py_compile
    for f in PY_FILES:
        py_compile.compile(f, doraise=True)


def t_py_lint():
    if importlib.util.find_spec("pyflakes") is None:
        raise RuntimeError("pyflakes fehlt (pip install pyflakes)")
    r = subprocess.run([sys.executable, "-m", "pyflakes", *PY_FILES],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError((r.stdout or r.stderr).strip())


def t_js_syntax():
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node fehlt (für js/app.js-Syntaxprüfung)")
    r = subprocess.run([node, "--check", "js/app.js"],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip())
    # Das in die Karten eingebettete Skript (FIT_JS) ebenfalls prüfen.
    import generate_cards as gc
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(gc.FIT_JS)
        tmp = fh.name
    try:
        r = subprocess.run([node, "--check", tmp],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError("FIT_JS: " + r.stderr.strip())
    finally:
        os.unlink(tmp)


# ── 2. Regel-Datenbanken ─────────────────────────────────────────────────────
def t_rule_data():
    rp = json.load(open("rule_phases.json", encoding="utf-8"))
    for key in ("sequence", "rules", "heuristic"):
        if key not in rp:
            raise RuntimeError(f"rule_phases.json: '{key}' fehlt")
    if not rp["sequence"]:
        raise RuntimeError("rule_phases.json: sequence leer")
    rt = json.load(open("rule_text.json", encoding="utf-8"))
    for key in ("summaries", "learned", "overrides"):
        if not isinstance(rt.get(key), dict):
            raise RuntimeError(f"rule_text.json: '{key}' fehlt/kein Objekt")
    # Overrides sind kuratierte Kartentexte: muessen in 2 Zeilen passen.
    import generate_cards as gc
    for name, text in rt["overrides"].items():
        if len(text) > gc.OVERRIDE_MAX_LEN:
            raise RuntimeError(
                f"override '{name}' zu lang ({len(text)} > "
                f"{gc.OVERRIDE_MAX_LEN} Zeichen, passt nicht in 2 Zeilen)")
    gl = json.load(open("rule_glossary.json", encoding="utf-8"))
    if not isinstance(gl.get("glossary"), dict) or not gl["glossary"]:
        raise RuntimeError("rule_glossary.json: 'glossary' fehlt/leer")


# ── 3. Kurztext-Priorität ────────────────────────────────────────────────────
def t_short_text_priority():
    """Regressionstest: Ein kuratierter 'overrides'-Text gewinnt IMMER
    (auch gegen den Export, inkl. (X)-Klammer-Fallback). Sonst ist die
    Export-JSON Quelle der Wahrheit (nichts friert ein); ohne Export-Text
    greifen summaries -> learned -> Glossar."""
    import generate_cards as gc
    gc.RT.setdefault("learned", {})["__TEST__"] = "Alte eingefrorene Fassung."
    gc.RT.setdefault("summaries", {})["__TEST2__"] = "Handgepflegte Fassung."
    gc.RT.setdefault("overrides", {})["__TEST3__"] = "Kuratierte Kartenfassung."
    try:
        got = gc.short_text("__TEST__", "Neuer Text aus dem Export. Rest.")
        if got != "Neuer Text aus dem Export.":
            raise RuntimeError(f"Export-Text gewinnt nicht: {got!r}")
        if gc.short_text("__TEST__", "") != "Alte eingefrorene Fassung.":
            raise RuntimeError("learned-Fallback kaputt")
        if gc.short_text("__TEST2__", "") != "Handgepflegte Fassung.":
            raise RuntimeError("summaries-Fallback kaputt")
        got = gc.short_text("__TEST3__", "Langer Text aus dem Export. Rest.")
        if got != "Kuratierte Kartenfassung.":
            raise RuntimeError(f"override gewinnt nicht gegen Export: {got!r}")
        got = gc.short_text("__TEST3__ (-2)", "Text aus dem Export. Rest.")
        if got != "Kuratierte Kartenfassung.":
            raise RuntimeError(f"override-Klammer-Fallback kaputt: {got!r}")
        glos_name = next(iter(gc.GLOSSARY))
        if not gc.short_text(glos_name, ""):
            raise RuntimeError("Glossar-Fallback kaputt")
    finally:
        gc.RT["learned"].pop("__TEST__", None)
        gc.RT["summaries"].pop("__TEST2__", None)
        gc.RT["overrides"].pop("__TEST3__", None)


# ── 3b. Parry: nur Infanterie zu Fuß ────────────────────────────────────────
def t_parry_rules():
    """Regressionstest: Parry (*) nur für (leichte) Infanterie zu Fuß mit
    Schild + Einhandwaffe. Reittier oder monströse Infanterie -> kein Parry."""
    import generate_cards as gc

    def unit(tt, mount=False):
        u = gc.Unit(name="T", troop_type=tt, save="4+", has_mount=mount)
        u.armour_items = [("Shield", "")]
        return u

    if gc.parry_save(unit("Regular infantry")) != "3+":
        raise RuntimeError("Parry für Infanterie zu Fuß kaputt")
    if gc.parry_save(unit("Light infantry")) != "3+":
        raise RuntimeError("Parry für leichte Infanterie kaputt")
    if gc.parry_save(unit("Regular infantry", mount=True)) != "":
        raise RuntimeError("Parry trotz Reittier")
    if gc.parry_save(unit("Monstrous infantry")) != "":
        raise RuntimeError("Parry trotz monströser Infanterie")
    if gc.parry_save(unit("Heavy cavalry")) != "":
        raise RuntimeError("Parry trotz Kavallerie")


# ── 3c. Rüstungs-Modifikatoren aus Sonderregeln ─────────────────────────────
def t_armour_modifiers():
    """Regressionstest: Sonderregeln wie Armoured Hide (X) verbessern den
    Rüstungswurf (ohne Klammer: 1); ohne Rüstung zählt 7+ als Basis
    (Schild allein -> 6+); Gromril Armour (Re-Roll 1er) wird als Hinweis
    gelistet, ändert den Wert aber nicht."""
    import generate_cards as gc

    def sel(rules, armour):
        profiles = [{"typeName": "Unit", "name": "T", "characteristics": [
            {"$text": "Regular infantry", "name": "Troop Type"}]}]
        profiles += [{"typeName": "Armour", "name": n, "characteristics": [
            {"$text": d, "name": "Description"}]} for n, d in armour]
        profiles += [{"typeName": "Special Rule", "name": n,
                      "characteristics": [{"$text": d, "name": "Description"}]}
                     for n, d in rules]
        return {"type": "unit", "name": "T", "profiles": profiles}

    hide = ("Armoured Hide (2)", "The hide of some creatures forms natural "
            "armour and improves their armour value ( and that of their "
            "rider). Note that a model that wears no armour is considerer "
            "to have an armour value of 7+.")
    u = gc.build_unit(sel([hide], [("Testpanzer", "Armour Value of 5+")]))
    if u.save != "3+":
        raise RuntimeError(f"Armoured Hide (2) + 5+ müsste 3+ sein: {u.save}")
    u = gc.build_unit(sel([hide], []))
    if u.save != "5+":
        raise RuntimeError(f"Armoured Hide (2) ohne Rüstung müsste 5+ "
                           f"sein (Basis 7+): {u.save}")
    u = gc.build_unit(sel([(hide[0].split(" (")[0], hide[1])], []))
    if u.save != "6+":
        raise RuntimeError(f"Armoured Hide ohne Klammer müsste 1 verbessern "
                           f"(7+ -> 6+): {u.save}")
    gromril = ("Testgromril", "A model with this special rule may re-roll "
               "any roll of a natural 1 made when making an Armour Save roll")
    u = gc.build_unit(sel([gromril], [("Testpanzer", "Armour Value of 5+")]))
    if u.save != "5+":
        raise RuntimeError(f"Re-Roll-Regel darf den Wert nicht ändern: {u.save}")
    if not any("neu würfeln" in p for p in u.save_parts):
        raise RuntimeError(f"Re-Roll-Hinweis fehlt in save_parts: {u.save_parts}")


# ── 4. Ende-zu-Ende: Kartengenerierung ───────────────────────────────────────
FIXTURE = os.path.join("tests", "fixtures", "testliste.json")


def t_generate_cards():
    """Synthetische Mini-Liste -> Karten + Ablaufplan. Prüft auch:
    <title> = Name der Eingabedatei (PDF-Dateinamen-Vorschlag des Browsers)
    und dass die Regel-DBs beim Generieren NICHT verändert werden."""
    import generate_cards as gc
    mtimes = {f: os.path.getmtime(f)
              for f in ("rule_text.json", "rule_phases.json",
                        "rule_glossary.json")}
    with tempfile.TemporaryDirectory() as td:
        out = gc.process_file(FIXTURE, td)
        html = open(out, encoding="utf-8").read()
        if "<title>testliste</title>" not in html:
            raise RuntimeError("<title> ist nicht der Eingabedateiname")
        if html.count('class="page"') < 2:
            raise RuntimeError("weniger als 2 Seiten (Vorder-/Rückseiten)")
        for needle in ("Testheld", "Testtruppe",
                       "Erster Satz der Testregel, der auf der Karte landet."):
            if needle not in html:
                raise RuntimeError(f"fehlt auf den Karten: {needle!r}")
        if "wegfallen" in html:
            raise RuntimeError("Kurztext nicht auf den ersten Satz gekürzt")
        # Parry: Testtruppe (Schild + Einhandwaffe, 6+ -1 = 5+) muss den
        # Nahkampfbonus zeigen; Testheld (Schild, aber NUR Zweihandwaffe,
        # 5+ -1 = 4+) darf ihn NICHT bekommen.
        if "(4+)*" not in html:
            raise RuntimeError("Parry-Bonus (4+)* fehlt im Total-Armour-Schild")
        if "* Parry" not in html:
            raise RuntimeError("Parry-Fußnote fehlt")
        if "(3+)*" in html:
            raise RuntimeError("Parry fälschlich trotz Zweihandwaffe (Testheld)")
        # Testreiter (Schild + Einhandwaffe, ABER Reittier, 4+ -1 = 3+):
        # beritten kämpft nicht zu Fuß -> kein Parry-Bonus (2+)*.
        if "(2+)*" in html:
            raise RuntimeError("Parry fälschlich trotz Reittier (Testreiter)")
        if "Testpferd" not in html:
            raise RuntimeError("Reittier-Statline (Testpferd) fehlt")
        # Flexible Kartenhöhe + Druck-Auswahl: data-u-Paare und skip-CSS
        if 'data-u="0"' not in html or "MAX_H" not in html:
            raise RuntimeError("data-u/Höhen-Logik fehlt in den Karten")
        if ".rule.skip" not in html:
            raise RuntimeError("skip-CSS (Zauber-/Regelauswahl) fehlt")
        plan_path = os.path.join(td, "testliste_plan.html")
        if not os.path.exists(plan_path):
            raise RuntimeError("Ablaufplan fehlt")
        if "<title>testliste_plan</title>" not in open(
                plan_path, encoding="utf-8").read():
            raise RuntimeError("Plan-<title> falsch")
    for f, m in mtimes.items():
        if os.path.getmtime(f) != m:
            raise RuntimeError(f"{f} wurde beim Generieren verändert!")


def t_reference():
    import generate_cards as gc
    html = gc.render_reference_document()
    if "Schnellreferenz" not in html or "<title>" not in html:
        raise RuntimeError("Schnellreferenz-Dokument unvollständig")


def t_spell_reference():
    """Zauberkarten (alle Lehren): synthetische tow-Daten -> Karten mit
    vollem Zaubertext, anklickbaren Blöcken und flexibler Höhe (data-u).
    KEIN Netzwerkzugriff im Test."""
    import generate_cards as gc
    body = {"nodeType": "document", "content": [
        {"nodeType": "text", "value":
         "Type Testtyp Casting Value 8+ Range 18\" "
         "Der Testzauber trifft die Zieleinheit mit D6 Testtreffern."}]}
    lore = [{"fields": {"name": "Testblitz", "type": "Signature Spell",
                        "castingValue": 8, "range": "18\"", "body": body}},
            {"fields": {"name": "Testwelle", "type": "3",
                        "castingValue": 10, "range": "24\"", "body": body}}]
    html = gc.render_spell_reference([("Testlehre", lore)])
    for needle in ("Testlehre", "Testblitz", "Testwelle",
                   "Testtreffern", "data-u=\"L0\"", "class=\"hint\""):
        if needle not in html:
            raise RuntimeError(f"Zauberkarten: {needle!r} fehlt")
    if "Casting Value" in html:
        raise RuntimeError("Zauberkarten: Meta-Präfix nicht abgetrennt")


# ── Runner ───────────────────────────────────────────────────────────────────
def main():
    print("Warhammer Card Creator – Testsuite")
    print("=" * 50)
    print("[1] Syntax + Lint")
    check("py-syntax", t_py_syntax)
    check("py-lint", t_py_lint)
    check("js-syntax", t_js_syntax)
    print("[2] Regel-Daten")
    check("regel-daten", t_rule_data)
    print("[3] Kurztexte")
    check("kurztext-prioritaet", t_short_text_priority)
    check("parry-nur-fussvolk", t_parry_rules)
    check("ruestungs-modifikatoren", t_armour_modifiers)
    print("[4] Generierung")
    check("karten-generierung", t_generate_cards)
    check("schnellreferenz", t_reference)
    check("zauberkarten", t_spell_reference)

    print("=" * 50)
    failed = [r for r in RESULTS if not r[0]]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} Tests grün")
    if failed:
        print("FEHLGESCHLAGEN:")
        for _, name, err in failed:
            print(f"  ✗ {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

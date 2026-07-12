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


# ── 2. Regel-Datenbanken ─────────────────────────────────────────────────────
def t_rule_data():
    rp = json.load(open("rule_phases.json", encoding="utf-8"))
    for key in ("sequence", "rules", "heuristic"):
        if key not in rp:
            raise RuntimeError(f"rule_phases.json: '{key}' fehlt")
    if not rp["sequence"]:
        raise RuntimeError("rule_phases.json: sequence leer")
    rt = json.load(open("rule_text.json", encoding="utf-8"))
    for key in ("summaries", "learned"):
        if not isinstance(rt.get(key), dict):
            raise RuntimeError(f"rule_text.json: '{key}' fehlt/kein Objekt")
    gl = json.load(open("rule_glossary.json", encoding="utf-8"))
    if not isinstance(gl.get("glossary"), dict) or not gl["glossary"]:
        raise RuntimeError("rule_glossary.json: 'glossary' fehlt/leer")


# ── 3. Kurztext-Priorität ────────────────────────────────────────────────────
def t_short_text_priority():
    """Regressionstest: Die Export-JSON ist Quelle der Wahrheit. Ein Text aus
    dem Export gewinnt IMMER gegen die Bibliothek (nichts friert ein);
    ohne Export-Text greifen summaries -> learned -> Glossar."""
    import generate_cards as gc
    gc.RT.setdefault("learned", {})["__TEST__"] = "Alte eingefrorene Fassung."
    gc.RT.setdefault("summaries", {})["__TEST2__"] = "Handgepflegte Fassung."
    try:
        got = gc.short_text("__TEST__", "Neuer Text aus dem Export. Rest.")
        if got != "Neuer Text aus dem Export.":
            raise RuntimeError(f"Export-Text gewinnt nicht: {got!r}")
        if gc.short_text("__TEST__", "") != "Alte eingefrorene Fassung.":
            raise RuntimeError("learned-Fallback kaputt")
        if gc.short_text("__TEST2__", "") != "Handgepflegte Fassung.":
            raise RuntimeError("summaries-Fallback kaputt")
        glos_name = next(iter(gc.GLOSSARY))
        if not gc.short_text(glos_name, ""):
            raise RuntimeError("Glossar-Fallback kaputt")
    finally:
        gc.RT["learned"].pop("__TEST__", None)
        gc.RT["summaries"].pop("__TEST2__", None)


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
    print("[4] Generierung")
    check("karten-generierung", t_generate_cards)
    check("schnellreferenz", t_reference)

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

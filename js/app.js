/* Warhammer Card Generator – Browser-Frontend (Pyodide).
 * Laedt den unveraenderten Python-Generator (generate_cards.py) samt seiner
 * Datendateien in Pyodides virtuelles Dateisystem und ruft die Render-Funktionen
 * direkt auf. Es wird nichts hochgeladen – alles laeuft lokal im Browser.
 */
"use strict";

// Dateien, die der Generator beim Import aus seinem BASE_DIR (= /app) liest.
const PY_MODULE = "generate_cards.py";
const DATA_FILES = ["rule_text.json", "rule_phases.json", "rule_glossary.json"];
const APP_DIR = "/app";

const els = {
  drop:   document.getElementById("drop"),
  file:   document.getElementById("file"),
  files:  document.getElementById("files"),
  pick:   document.getElementById("pick"),
  gen:    document.getElementById("gen"),
  ref:    document.getElementById("ref"),
  spells: document.getElementById("spells"),
  spellcards: document.getElementById("spellcards"),
  refmenu: document.getElementById("refmenu"),
  lorepanel: document.getElementById("lorepanel"),
  lorelist:  document.getElementById("lorelist"),
  lorego:    document.getElementById("lorego"),
  loreall:   document.getElementById("loreall"),
  lorenone:  document.getElementById("lorenone"),
  print:  document.getElementById("print"),
  bw:     document.getElementById("bw"),
  bwwrap: document.getElementById("bwwrap"),
  status: document.getElementById("status"),
  out:    document.getElementById("out"),
  outpanel: document.getElementById("outpanel"),
};

let pyodide = null;
let gen = null;            // das importierte Python-Modul
const rosters = [];        // [{name, data}] der eingelesenen Listen

function setStatus(msg, kind = "") {
  els.status.textContent = msg;
  els.status.className = "status" + (kind ? " " + kind : "");
}

async function fetchText(path) {
  // Cache-Bust, damit nach Updates immer die frische Version geladen wird.
  const res = await fetch(`./${path}?v=${Date.now()}`);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.text();
}

async function boot() {
  try {
    setStatus("Lade Python-Laufzeit (Pyodide) …", "busy");
    pyodide = await loadPyodide();

    setStatus("Lade Generator-Code …", "busy");
    const [moduleSrc, ...dataSrcs] = await Promise.all([
      fetchText(PY_MODULE),
      ...DATA_FILES.map(fetchText),
    ]);

    // Generator + Datendateien ins virtuelle FS unter /app schreiben.
    pyodide.FS.mkdirTree(APP_DIR);
    pyodide.FS.writeFile(`${APP_DIR}/${PY_MODULE}`, moduleSrc);
    DATA_FILES.forEach((name, i) => {
      pyodide.FS.writeFile(`${APP_DIR}/${name}`, dataSrcs[i]);
    });

    // /app importierbar machen und Modul laden (BASE_DIR zeigt dann auf /app,
    // die vorhandenen load_*-Funktionen finden ihre JSONs dort).
    pyodide.runPython(`import sys\nif ${JSON.stringify(APP_DIR)} not in sys.path: sys.path.insert(0, ${JSON.stringify(APP_DIR)})`);
    gen = pyodide.pyimport("generate_cards");

    setStatus("Bereit. Wähle eine Liste.", "");
    els.ref.disabled = false;
    els.spells.disabled = false;
    els.spellcards.disabled = false;
    refreshGenButton();  // falls schon eine Liste vor dem Laden gewaehlt wurde
  } catch (e) {
    console.error(e);
    setStatus("Fehler beim Laden: " + e.message, "err");
  }
}

function showHtml(html) {
  els.out.srcdoc = html;
  els.outpanel.classList.remove("hidden");
  els.print.classList.remove("hidden");
  els.bwwrap.classList.remove("hidden");
  els.out.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Schwarz-weiss-Modus (helle Karte, dunkle Schrift) auf die Vorschau anwenden.
// Klasse 'bw' am <html> des iframe-Dokuments; das CSS-Theme steckt im Dokument.
function applyBw() {
  const doc = els.out.contentDocument;
  if (doc && doc.documentElement)
    doc.documentElement.classList.toggle("bw", els.bw.checked);
}

async function readFiles(fileList) {
  rosters.length = 0;
  els.pick.innerHTML = "";
  const problems = [];
  for (const f of fileList) {
    try {
      const txt = await f.text();
      const data = JSON.parse(txt);
      const isOwb = !data.roster &&
        ["characters", "core", "special", "rare"].some(k => k in data);
      if (!data.roster && !isOwb)
        throw new Error("weder NewRecruit ('roster') noch Old World Builder");
      // fname = Eingabedateiname -> wird <title> und damit der Vorschlag
      // des Browsers beim PDF-Speichern
      const fname = f.name.replace(/\.(owb\.)?json$/i, "");
      const name = (data.roster && data.roster.name) || data.name || fname;
      rosters.push({ name, fname, data, isOwb, army: data.army || "" });
    } catch (e) {
      problems.push(`${f.name}: ${e.message}`);
    }
  }
  // Auswahl-Dropdown nur bei mehreren Listen zeigen.
  rosters.forEach((r, i) => {
    const o = document.createElement("option");
    o.value = String(i); o.textContent = r.name;
    els.pick.appendChild(o);
  });
  els.pick.classList.toggle("hidden", rosters.length < 2);

  const ok = rosters.length;
  els.files.innerHTML = ok
    ? `<b>${ok}</b> Liste(n) geladen: ${rosters.map(r => r.name).join(", ")}`
      + (problems.length ? `<br><span style="color:#ff9a8a">Übersprungen: ${problems.join("; ")}</span>` : "")
    : `<span style="color:#ff9a8a">Keine gültige Liste. ${problems.join("; ")}</span>`;

  refreshGenButton();
  if (ok) setStatus(gen ? `Bereit – „Karten erzeugen“ klicken.`
                        : `Liste geladen – warte auf Python-Laufzeit …`, "busy");
}

function refreshGenButton() {
  els.gen.disabled = !(rosters.length && gen);
}

// Old World Builder liefert keine Statwerte/Zauber -> live von tow.whfb.app holen.
// buildId wird live aus der Startseite gelesen (selbstheilend bei Deploys).
// tow.whfb.app sendet 'Access-Control-Allow-Origin: *', daher im Browser erlaubt.
let towBuildId = null;
async function towPageProps(path) {
  if (!towBuildId) {
    const home = await (await fetch("https://tow.whfb.app/")).text();
    towBuildId = (home.match(/"buildId":"([^"]+)"/) || [])[1] || null;
  }
  if (!towBuildId) return {};
  const res = await fetch(`https://tow.whfb.app/_next/data/${towBuildId}/${path}.json`);
  if (!res.ok) return {};
  return (await res.json()).pageProps || {};
}

async function fetchOwbStats(armySlug) {
  if (!armySlug) return [];
  try { return (await towPageProps(`army/${armySlug}`)).units || []; }
  catch (e) { console.warn("tow Statabruf:", e); return []; }
}

// Die 7 Zauber je gewaehlter Lore (Signature + 6, in Reihenfolge) -> {slug: spells}.
async function fetchOwbLoreSpells(data) {
  const slugs = new Set();
  for (const cat of ["characters", "core", "special", "rare", "mercenaries", "allies"])
    for (const o of (data[cat] || [])) if (o.activeLore) slugs.add(o.activeLore);
  const map = {};
  for (const slug of slugs) {
    try { map[slug] = (await towPageProps(`cards/${slug}`)).spells || []; }
    catch (e) { console.warn("tow Lore:", slug, e); map[slug] = []; }
  }
  return map;
}

async function generate() {
  if (!gen || !rosters.length) return;
  const idx = Math.max(0, Number(els.pick.value) || 0);
  const r = rosters[idx];
  els.gen.disabled = true;
  try {
    let statUnits = [], loreSpells = {};
    if (r.isOwb) {
      setStatus(`Old World Builder – hole Statwerte & Zauber für „${r.army}“ live von tow.whfb.app …`, "busy");
      [statUnits, loreSpells] = await Promise.all([
        fetchOwbStats(r.army), fetchOwbLoreSpells(r.data)]);
      if (!statUnits.length)
        setStatus("Keine Statwerte von tow.whfb.app – Karten ohne Statline.", "err");
    }
    setStatus(`Erzeuge Karten für „${r.name}“ …`, "busy");
    // JS-Objekt -> Python; HTML zurueck als JS-String.
    const pyData = pyodide.toPy(r.data);
    const pyStats = pyodide.toPy(statUnits);
    const pyLore = pyodide.toPy(loreSpells);
    const html = gen.build_cards_html(pyData, r.name, pyStats, pyLore, r.fname);
    pyData.destroy?.(); pyStats.destroy?.(); pyLore.destroy?.();
    showHtml(html);
    const nLore = Object.values(loreSpells).filter(s => s.length).length;
    setStatus(`Fertig: „${r.name}“`
      + (r.isOwb ? ` · ${statUnits.length} Statprofile`
          + (nLore ? ` · ${nLore} Lore(s) mit Zaubern` : "") + " live von tow.whfb.app" : ""), "");
  } catch (e) {
    console.error(e);
    setStatus("Fehler beim Erzeugen: " + e.message, "err");
  } finally {
    els.gen.disabled = false;
  }
}

function showReference() {
  if (!gen) return;
  try {
    setStatus("Erzeuge Schnellreferenz …", "busy");
    showHtml(gen.render_reference_document());
    setStatus("Schnellreferenz angezeigt.", "");
  } catch (e) {
    console.error(e);
    setStatus("Fehler: " + e.message, "err");
  }
}

// --- Zauberkarten mit Lehren-Auswahl -----------------------------------------
// Ablauf: Menüpunkt klicken -> Lehren-Index von tow.whfb.app -> Checkboxen
// (Regelbuch-Schulen "(Standard)" vorausgewählt) -> "erstellen" holt nur die
// gewählten Lehren und rendert A6-Lehren-Karten ODER einzelne Spielkarten.
let loreIndex = null;      // [{name, slug, standard}]
const loreCache = {};      // slug -> Zauberliste
let loreSingle = false;    // false = je Lehre (A6), true = Spielkarten

async function openLoreSelect(single) {
  if (!gen) return;
  loreSingle = single;
  try {
    if (!loreIndex) {
      setStatus("Hole Zauberlehren-Liste von tow.whfb.app …", "busy");
      loreIndex = ((await towPageProps("cards")).magicLores || [])
        .map(l => l.fields || {}).filter(f => f.slug)
        .map(f => ({ name: f.name || f.slug, slug: f.slug,
                     standard: !f.slug.startsWith("lore-of-") }));
      if (!loreIndex.length) throw new Error("keine Zauberlehren von tow.whfb.app erhalten");
      els.lorelist.innerHTML = "";
      for (const l of loreIndex) {
        const lab = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.value = l.slug; cb.checked = l.standard;
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(" " + l.name + " "));
        if (l.standard) {
          const s = document.createElement("span");
          s.className = "std"; s.textContent = "(Standard)";
          lab.appendChild(s);
        }
        els.lorelist.appendChild(lab);
      }
    }
    els.lorego.textContent = single
      ? "Spielkarten erstellen" : "Lehren-Karten (A6) erstellen";
    els.lorepanel.classList.remove("hidden");
    els.lorepanel.scrollIntoView({ behavior: "smooth", block: "start" });
    setStatus("Lehren auswählen, dann „erstellen“ klicken.", "");
  } catch (e) {
    console.error(e);
    setStatus("Fehler: " + e.message, "err");
  }
}

async function buildSpellDocs() {
  if (!gen || !loreIndex) return;
  const sel = [...els.lorelist.querySelectorAll("input:checked")].map(c => c.value);
  if (!sel.length) { setStatus("Keine Lehre ausgewählt.", "err"); return; }
  els.lorego.disabled = true;
  try {
    setStatus(`Hole ${sel.length} Lehre(n) live von tow.whfb.app …`, "busy");
    await Promise.all(sel.map(async slug => {
      if (!loreCache[slug]) {
        try { loreCache[slug] = (await towPageProps(`cards/${slug}`)).spells || []; }
        catch (e) { console.warn("tow Lore:", slug, e); loreCache[slug] = []; }
      }
    }));
    const data = loreIndex.filter(l => sel.includes(l.slug))
      .map(l => [l.name, loreCache[l.slug]]);
    const py = pyodide.toPy(data);
    showHtml(loreSingle ? gen.render_spell_playing_cards(py)
                        : gen.render_spell_reference(py));
    py.destroy?.();
    setStatus(`Zauberkarten (${loreSingle ? "Spielkarten" : "je Lehre"}): `
      + `${sel.length} Lehre(n) von tow.whfb.app.`, "");
  } catch (e) {
    console.error(e);
    setStatus("Fehler bei den Zauberkarten: " + e.message, "err");
  } finally {
    els.lorego.disabled = false;
  }
}

function printOut() {
  const w = els.out.contentWindow;
  if (w) { w.focus(); w.print(); }
}

// --- Events ------------------------------------------------------------------
els.file.addEventListener("change", e => readFiles(e.target.files));
els.gen.addEventListener("click", generate);
els.ref.addEventListener("click", showReference);
els.spells.addEventListener("click", () => openLoreSelect(false));
els.spellcards.addEventListener("click", () => openLoreSelect(true));
els.lorego.addEventListener("click", buildSpellDocs);
els.loreall.addEventListener("click", () =>
  els.lorelist.querySelectorAll("input").forEach(c => { c.checked = true; }));
els.lorenone.addEventListener("click", () =>
  els.lorelist.querySelectorAll("input").forEach(c => { c.checked = false; }));
// Referenzen-Menü nach Auswahl schließen
els.refmenu.addEventListener("click", e => {
  if (e.target.closest("button")) els.refmenu.removeAttribute("open");
});
els.print.addEventListener("click", printOut);
els.bw.addEventListener("change", applyBw);
els.out.addEventListener("load", applyBw);  // nach jedem Neu-Rendern Zustand halten
els.ref.disabled = true;
els.spells.disabled = true;
els.spellcards.disabled = true;

["dragover", "dragenter"].forEach(ev =>
  els.drop.addEventListener(ev, e => { e.preventDefault(); els.drop.classList.add("hover"); }));
["dragleave", "drop"].forEach(ev =>
  els.drop.addEventListener(ev, e => { e.preventDefault(); els.drop.classList.remove("hover"); }));
els.drop.addEventListener("drop", e => {
  if (e.dataTransfer?.files?.length) readFiles(e.dataTransfer.files);
});

boot();

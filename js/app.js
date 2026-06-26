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
  print:  document.getElementById("print"),
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
  } catch (e) {
    console.error(e);
    setStatus("Fehler beim Laden: " + e.message, "err");
  }
}

function showHtml(html) {
  els.out.srcdoc = html;
  els.outpanel.classList.remove("hidden");
  els.print.classList.remove("hidden");
  els.out.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function readFiles(fileList) {
  rosters.length = 0;
  els.pick.innerHTML = "";
  const problems = [];
  for (const f of fileList) {
    try {
      const txt = await f.text();
      const data = JSON.parse(txt);
      if (!data.roster) throw new Error("kein 'roster' im JSON");
      const name = (data.roster.name) || f.name.replace(/\.json$/i, "");
      rosters.push({ name, data });
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

  els.gen.disabled = !(ok && gen);
  if (ok) setStatus(`Bereit – „Karten erzeugen“ klicken.`, "");
}

function generate() {
  if (!gen || !rosters.length) return;
  const idx = Math.max(0, Number(els.pick.value) || 0);
  const r = rosters[idx];
  try {
    setStatus(`Erzeuge Karten für „${r.name}“ …`, "busy");
    // JS-Objekt -> Python dict; HTML zurueck als JS-String.
    const pyData = pyodide.toPy(r.data);
    const html = gen.build_cards_html(pyData, r.name);
    pyData.destroy?.();
    showHtml(html);
    setStatus(`Fertig: „${r.name}“.`, "");
  } catch (e) {
    console.error(e);
    setStatus("Fehler beim Erzeugen: " + e.message, "err");
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

function printOut() {
  const w = els.out.contentWindow;
  if (w) { w.focus(); w.print(); }
}

// --- Events ------------------------------------------------------------------
els.file.addEventListener("change", e => readFiles(e.target.files));
els.gen.addEventListener("click", generate);
els.ref.addEventListener("click", showReference);
els.print.addEventListener("click", printOut);
els.ref.disabled = true;

["dragover", "dragenter"].forEach(ev =>
  els.drop.addEventListener(ev, e => { e.preventDefault(); els.drop.classList.add("hover"); }));
["dragleave", "drop"].forEach(ev =>
  els.drop.addEventListener(ev, e => { e.preventDefault(); els.drop.classList.remove("hover"); }));
els.drop.addEventListener("drop", e => {
  if (e.dataTransfer?.files?.length) readFiles(e.dataTransfer.files);
});

boot();

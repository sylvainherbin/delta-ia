// Harnais des tests du site (lot L3) : exécute le vrai docs/assets/app.js (avec config.js et textes.js) dans un DOM minimal,
// les fichiers servis depuis docs/ (ou des remplacements), et rend ce qui s'affiche après chaque ancre demandée.
// Entrée (stdin, JSON) : { langue: "en"|"fr", recherche: "?couche=commun"|"", ancres: ["#aujourdhui", …],
//   absents: ["data/etat.json", …] (chemins relatifs à docs/), remplacer: { "data/x.json": <json> }, stockage: {clé: valeur} }.
// Sortie (stdout, JSON) : { etapes: [{ ancre, texte, couche, titre }], lus: [chemins demandés], erreurs: [messages console.error] }.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { pathToFileURL } = require("node:url");

const DOCS = path.resolve(__dirname, "..", "docs");
const entree = JSON.parse(fs.readFileSync(0, "utf8"));
const langue = entree.langue || "en";
// `horloge` (ISO) fige l'heure vue par le site : les bannières de fraîcheur des passages ne dépendent plus du jour du test.
const HORLOGE = entree.horloge ? Date.parse(entree.horloge) : null;
if (HORLOGE !== null && Number.isNaN(HORLOGE)) throw new Error(`horloge invalide : ${entree.horloge}`);
class DateFixe extends Date {
  constructor(...a) { super(...(a.length ? a : [HORLOGE])); }
  static now() { return HORLOGE; }
}

class Noeud {
  constructor(tag, texte) {
    this.tagName = tag; this.enfants = []; this.attrs = {}; this.parent = null; this.ecouteurs = {};
    this.texteBrut = texte; this.className = ""; this.hidden = false; this.dataset = {};
    const soi = this;
    this.classList = {
      add: (c) => { const s = new Set(soi.className.split(" ").filter(Boolean)); s.add(c); soi.className = [...s].join(" "); },
      toggle: (c, v) => { const s = new Set(soi.className.split(" ").filter(Boolean)); (v === undefined ? !s.has(c) : v) ? s.add(c) : s.delete(c); soi.className = [...s].join(" "); },
      contains: (c) => soi.className.split(" ").includes(c),
    };
  }
  get firstChild() { return this.enfants[0] || null; }
  get lastChild() { return this.enfants[this.enfants.length - 1] || null; }
  append(...xs) {
    for (const x of xs) {
      if (x === null || x === undefined) continue;
      const n = typeof x === "string" ? new Noeud("#text", x) : x;
      if (n.tagName === "#fragment") { for (const e of [...n.enfants]) this.append(e); n.enfants = []; continue; }
      if (n.parent) n.parent.removeChild(n);
      n.parent = this; this.enfants.push(n);
    }
  }
  removeChild(n) { this.enfants = this.enfants.filter((e) => e !== n); n.parent = null; return n; }
  remove() { if (this.parent) this.parent.removeChild(this); }
  before() { /* annonces de console : hors du contenu observé */ }
  after(n) { if (this.parent) { const i = this.parent.enfants.indexOf(this); n.parent = this.parent; this.parent.enfants.splice(i + 1, 0, n); } }
  replaceWith(...xs) {
    const p = this.parent; if (!p) return;
    const i = p.enfants.indexOf(this); p.enfants.splice(i, 1); this.parent = null;
    const nouveaux = xs.map((x) => (typeof x === "string" ? new Noeud("#text", x) : x));
    for (const n of nouveaux) n.parent = p;
    p.enfants.splice(i, 0, ...nouveaux);
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = String(v); if (k.startsWith("data-")) this.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  addEventListener(type, cb) { this.ecouteurs[type] = cb; }
  set textContent(s) { this.enfants = [new Noeud("#text", String(s))]; }
  get textContent() { return this.tagName === "#text" ? this.texteBrut : this.enfants.map((e) => e.textContent).join(""); }
  set innerHTML(_) { throw new Error("innerHTML interdit"); }
  *parcours() { for (const e of this.enfants) { yield e; yield* e.parcours(); } }
  correspond(sel) {
    if (this.tagName === "#text") return false;
    const m = /^([a-z0-9]*)(\[([a-z-]+)\])?((\.[a-z0-9-]+)*)$/i.exec(sel);
    if (!m) return false;
    if (m[1] && this.tagName !== m[1]) return false;
    if (m[3] && this.getAttribute(m[3]) === null) return false;
    for (const c of (m[4] || "").split(".").filter(Boolean)) if (!this.classList.contains(c)) return false;
    return true;
  }
  querySelectorAll(sel) { return [...this.parcours()].filter((n) => n.correspond(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const racineDocument = new Noeud("html");
const main = new Noeud("main"); main.setAttribute("id", "contenu");
const etatAgents = new Noeud("div"); etatAgents.setAttribute("id", "etat-agents");
const couche = new Noeud("p"); couche.setAttribute("id", "couche-lue");
const lienLangue = new Noeud("a"); lienLangue.setAttribute("id", "choix-langue");
lienLangue.setAttribute("data-base", langue === "en" ? "fr/" : "../"); lienLangue.setAttribute("hreflang", langue === "en" ? "fr" : "en");
racineDocument.append(main, etatAgents, couche, lienLangue);

const lus = [], erreurs = [], ecouteursFenetre = {};
const stockage = new Map(Object.entries(entree.stockage || {}));
const location = { hash: "", search: entree.recherche || "", pathname: langue === "en" ? "/" : "/fr/" };
const document = {
  documentElement: { lang: langue, getAttribute: (k) => (k === "data-racine" ? (langue === "en" ? "" : "../") : null) },
  title: "",
  head: new Noeud("head"),
  createElement: (tag) => new Noeud(tag),
  createTextNode: (s) => new Noeud("#text", String(s)),
  createDocumentFragment: () => new Noeud("#fragment"),
  getElementById: (id) => [racineDocument, ...racineDocument.parcours()].find((n) => n.id === id) || null,
  querySelectorAll: (sel) => racineDocument.querySelectorAll(sel),
  querySelector: (sel) => racineDocument.querySelector(sel),
};
async function fetchSimule(url) {
  // l'URL est relative à la page : "../" sous /fr/ remonte à docs/
  const rel = path.posix.normalize(path.posix.join(langue === "en" ? "" : "fr", String(url).split("?")[0]));
  lus.push(rel);
  if ((entree.absents || []).includes(rel)) return { ok: false, status: 404, json: async () => { throw new Error("404"); } };
  if (entree.remplacer && Object.prototype.hasOwnProperty.call(entree.remplacer, rel)) {
    const v = entree.remplacer[rel];
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(v)) };
  }
  const f = path.join(DOCS, rel);
  if (!f.startsWith(DOCS) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) return { ok: false, status: 404, json: async () => { throw new Error("404"); } };
  const contenu = fs.readFileSync(f, "utf8");
  return { ok: true, status: 200, json: async () => JSON.parse(contenu) };
}
const window = { addEventListener: (type, cb) => { ecouteursFenetre[type] = cb; }, scrollTo() {}, open: () => null };
const contexte = vm.createContext({
  window, document, location, fetch: fetchSimule, URL, URLSearchParams, Intl, Date: HORLOGE === null ? Date : DateFixe, Promise, Math, JSON, Object, Array, Set, Map, Number, String, RegExp, Error,
  history: { replaceState() {} },
  localStorage: { getItem: (k) => (stockage.has(k) ? stockage.get(k) : null), setItem: (k, v) => stockage.set(k, String(v)), removeItem: (k) => stockage.delete(k) },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  navigator: { userAgent: "", platform: "", maxTouchPoints: 0 },
  performance: { now: () => Date.now() },
  AbortSignal: { timeout: () => null },
  setTimeout, clearTimeout,
  console: { log() {}, error: (...a) => erreurs.push(a.map(String).join(" ")) },
  __importerModeles: () => import(pathToFileURL(path.join(DOCS, "assets", "kb-modeles.mjs")).href),
});
contexte.globalThis = contexte;
window.window = window;
for (const f of ["config.js", "textes.js"]) {
  // ces deux fichiers posent window.DELTA_CONFIG et window.DELTA_TEXTES
  vm.runInContext(fs.readFileSync(path.join(DOCS, "assets", f), "utf8"), contexte);
}
const app = fs.readFileSync(path.join(DOCS, "assets", "app.js"), "utf8").replace('import("./kb-modeles.mjs")', "__importerModeles()");
const attendre = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const etapes = [];
  const ancres = entree.ancres && entree.ancres.length ? entree.ancres : ["#aujourdhui"];
  location.hash = ancres[0];
  vm.runInContext(app, contexte);
  await attendre(400);
  const releve = (ancre) => etapes.push({ ancre, texte: main.textContent, couche: couche.textContent, titre: document.title, langue_href: lienLangue.getAttribute("href") });
  releve(ancres[0]);
  for (const a of ancres.slice(1)) {
    location.hash = a;
    if (ecouteursFenetre.hashchange) ecouteursFenetre.hashchange();
    await attendre(500);
    releve(a);
  }
  process.stdout.write(JSON.stringify({ etapes, lus, erreurs }));
})().catch((e) => { console.error(e); process.exitCode = 1; });

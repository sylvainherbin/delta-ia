// Exécute le rendu et les filtres du site sur le catalogue public réel.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { developperModeles as developperMcp } from "../lib/modeles.js";
import { developperModeles } from "../../docs/assets/kb-modeles.mjs";
const app = fs.readFileSync(new URL("../../docs/assets/app.js", import.meta.url), "utf8");
const doc = JSON.parse(fs.readFileSync(new URL("../../docs/data/kb/modeles.json", import.meta.url), "utf8"));
// L3 : génération commune publiée (docs/commun/v1/<génération>/kb/modeles.json), même lecteur
const generation = JSON.parse(fs.readFileSync(new URL("../../docs/commun/v1/index.json", import.meta.url), "utf8")).generation;
const docCommun = JSON.parse(fs.readFileSync(new URL(`../../docs/commun/v1/${generation}/kb/modeles.json`, import.meta.url), "utf8"));
// dictionnaire français du site (docs/assets/textes.js) : t() d'app.js
const textesJs = fs.readFileSync(new URL("../../docs/assets/textes.js", import.meta.url), "utf8");
const FR = JSON.parse(textesJs.slice(textesJs.indexOf("window.DELTA_TEXTES = ") + 22, textesJs.lastIndexOf(";"))).fr;
const prendre = (debut, fin) => app.slice(app.indexOf(debut), app.indexOf(fin, app.indexOf(debut)));
class Noeud {
  constructor(tag) { this.tag = tag; this.enfants = []; this.attrs = {}; }
  append(...xs) { this.enfants.push(...xs); }
  set textContent(s) { this.enfants = [String(s)]; }
  get textContent() { return this.enfants.map((x) => typeof x === "string" ? x : x.textContent).join(""); }
  set innerHTML(_) { throw new Error("innerHTML interdit"); }
  setAttribute(k, v) { this.attrs[k] = v; }
  get lastChild() { return this.enfants.at(-1); }
}
function contexte() {
  const c = vm.createContext({ document: { createElement: (t) => new Noeud(t), createTextNode: (s) => String(s) }, Intl, Date });
  vm.runInContext(`const LANGUE = "fr"; const DICO = ${JSON.stringify(FR)};
    const t = (cle, vars) => { let s = DICO[cle]; if (typeof s !== "string") throw new Error("texte manquant : " + cle);
      return vars ? s.replace(/\\{(\\w+)\\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s; };
    const enCommun = () => false;
    ${prendre("function el(", "/* ---------- D105")}
    const badge = (type, text) => el("span", {class: type, text});
    const PRODUITS = {}, KB_CATEGORIES = {modeles: "Modèles"}, VERDICTS = {}, STATUTS = {};
    const dateAffichee = (s) => s;
    ${prendre("function noeudsEnLigne", "function carteMethode")}
    ${prendre("function carteModele", "function carteKb")}
    const sansAccents = s => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const kbFiltre = {q: "", tri: "nom"};
    const etat = {kb: {entrees: []}};
    ${prendre("function jourLocalIso", "// fichier léger")}
    ${prendre('const COLLATEUR_KB', 'const cleKb')}
    ${prendre("function filtrerKb", "// encart de l'onglet")}
    globalThis.api = {carteModele, rendreMarkdownMethode, filtrerKb, fusionnerParNomKb, comparerNomKb, kbFiltre, etat, sansAccents};`, c);
  return c.api;
}

test("site : toutes les cartes modèles se rendent en DOM, sans astérisques de formatage ni HTML actif", () => {
  const api = contexte();
  for (const e of developperModeles(doc)) {
    const carte = api.carteModele(e);
    assert.ok(carte.textContent.includes(e.nom));
    assert.ok(carte.textContent.includes(e.effet_effort));
    assert.ok(!carte.textContent.includes("*(défaut)*"));
    assert.ok(!/\*\(|\*\[/.test(carte.textContent));
  }
  const hostile = api.rendreMarkdownMethode("- <img src=x onerror=alert(1)> **source** `commande`");
  assert.ok(hostile.textContent.includes("<img src=x onerror=alert(1)>"));
  const tags = n => typeof n === "string" ? [] : [n.tag, ...n.enfants.flatMap(tags)];
  assert.ok(!tags(hostile).includes("img"));
});

test("site : classement mixte, filtre produit et catégorie portent sur les fiches développées", () => {
  const api = contexte();
  const modeles = developperModeles(doc).sort(api.comparerNomKb);
  const documentation = [{id: "doc", nom: "/effort", produit: "claude-code", categorie: "commandes", description: "Régler l’effort"}];
  const mixte = api.fusionnerParNomKb(documentation, modeles);
  const attendu = [...documentation, ...modeles].sort(api.comparerNomKb);
  assert.deepEqual(Array.from(mixte, e => e.id), attendu.map(e => e.id));
  for (const e of mixte) e._texte = api.sansAccents(`${e.nom} ${e.description} ${e.usage}`);
  api.etat.kb.entrees = mixte;
  api.kbFiltre.produit = "codex";
  assert.deepEqual(new Set(api.filtrerKb().map(e => e.modele)), new Set(["gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra", "gemini-4-argon", "gemini-3.8-flash", "antigravity-claude-sonnet-5-5", "antigravity-claude-opus-5-5", "gpt-oss-120b", "Qwen3.5-4B", "Qwen3.5-9B", "gpt-oss-20b", "Qwen3-Embedding-0.6B"]));
  api.kbFiltre.produit = "claude-code";
  assert.ok(api.filtrerKb().some(e => e.id === "doc"));
  assert.ok(api.filtrerKb().some(e => e.modele === "claude-sonnet-5-5"));
  assert.ok(!api.filtrerKb().some(e => e.executant === "codex"));
  api.kbFiltre.categorie = "modeles";
  assert.ok(api.filtrerKb().every(e => e.categorie === "modeles"));
});

test("développement : référence absente refusée, champs communs et alias de défaut conservés", () => {
  const es = developperModeles(doc);
  assert.deepEqual(developperMcp(doc), es);
  for (const e of es) {
    assert.equal(e.benchmarks, doc.modeles[e.modele].benchmarks);
    assert.ok(e.aliases.includes(`${e.modele}:${e.effort}`));
    assert.equal(e.aliases.includes(e.modele), e.effort_defaut);
    assert.ok(e.description.includes("### Tous les niveaux"));
    assert.ok(e.description.includes("Coût de `" + e.effort + "`"));
  }
  // erreur à clé, traduite par le dictionnaire du MCP et du site (relecture L3, À NOTER 1)
  assert.throws(() => developperModeles({...doc, modeles: {}}), (e) => e.cle === "modeles.absent" && e.vars.modele === doc.entrees[0].modele);
  assert.throws(() => developperModeles({...doc, schema_version: 1}), (e) => e.cle === "modeles.format");
});

test("L3 : aucun constat interne ni recommandation OPÉRER, ancien JSON mixte comme génération commune", () => {
  // l'ancien JSON publié les contient encore (garde : le test verrait leur retour)
  assert.ok(Object.values(doc.modeles).some((m) => (m.constats_internes || []).length));
  assert.ok(doc.entrees.some((e) => e.recommandation_operer));
  for (const [source, es] of [["ancien", developperModeles(doc)], ["commun", developperModeles(docCommun)]]) {
    assert.equal(es.length, docCommun.entrees.length, source);
    assert.deepEqual(developperMcp(source === "ancien" ? doc : docCommun), es, source);
    for (const e of es) {
      for (const k of ["constats_internes", "recommandation_operer", "recommandation"]) assert.ok(!(k in e), `${source} ${e.id} : ${k}`);
      const d = e.description || "";
      assert.ok(!d.includes("Constats internes datés") && !d.includes("Recommandation OPÉRER"), `${source} ${e.id}`);
    }
  }
  // génération commune : pas de texte rédigé, alias réduits au couple exact (et au modèle seul pour l'effort par défaut)
  for (const e of developperModeles(docCommun)) {
    assert.equal(e.description, null);
    assert.deepEqual(e.aliases, [`${e.modele}:${e.effort}`, ...(e.effort_defaut ? [e.modele] : [])]);
  }
  // la carte du site se rend aussi sur la génération commune, sans texte de description
  const api = contexte();
  for (const e of developperModeles(docCommun)) {
    const carte = api.carteModele(e);
    assert.ok(carte.textContent.includes(e.nom) && carte.textContent.includes(e.usage));
    assert.ok(!carte.textContent.includes("OPÉRER ("));
  }
  // les deux copies du lecteur restent identiques (hors commentaire d'en-tête)
  const sansEntete = (u) => fs.readFileSync(new URL(u, import.meta.url), "utf8").split("\n").slice(2).join("\n");
  assert.equal(sansEntete("../lib/modeles.js"), sansEntete("../../docs/assets/kb-modeles.mjs"));
});

// Exécute le rendu et les filtres du site sur le catalogue public réel.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { developperModeles as developperMcp } from "../lib/modeles.js";
import { developperModeles } from "../../docs/assets/kb-modeles.mjs";
const app = fs.readFileSync(new URL("../../docs/assets/app.js", import.meta.url), "utf8");
const doc = JSON.parse(fs.readFileSync(new URL("../../docs/data/kb/modeles.json", import.meta.url), "utf8"));
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
  vm.runInContext(`${prendre("function el(", "/* ---------- D105")}
    const badge = (type, text) => el("span", {class: type, text});
    const PRODUITS = {}, KB_CATEGORIES = {modeles: "Modèles"}, VERDICTS = {}, STATUTS = {};
    const dateFr = (s) => s;
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
  assert.throws(() => developperModeles({...doc, modeles: {}}), /modèle absent/);
});

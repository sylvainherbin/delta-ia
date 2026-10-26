// Lot L3 (deux couches) : lecteurs publics compatibles. Le serveur lit l'ancienne route (docs/data, format historique
// mixte ou vue compatible aux champs personnels nuls) et la génération commune réelle (docs/commun/v1), répond en anglais
// par défaut et en français sur demande, sans aucun avis personnel de repli.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const ICI = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.resolve(ICI, "../../docs");
const lireJson = (f) => JSON.parse(fs.readFileSync(path.join(DOCS, f), "utf8"));
const INDEX = lireJson("commun/v1/index.json");
const GEN = INDEX.generation;

// Serveur de docs/ : `remplacements` = chemin relatif à docs/ → objet, texte, ou null (404).
async function servir(remplacements = {}) {
  const srv = http.createServer((req, res) => {
    const nom = decodeURIComponent(req.url.split("?")[0]).replace(/^\//, "");
    if (Object.hasOwn(remplacements, nom)) {
      const v = remplacements[nom];
      if (v === null) { res.statusCode = 404; return res.end(); }
      return res.end(typeof v === "string" ? v : JSON.stringify(v));
    }
    const f = path.join(DOCS, nom);
    if (!f.startsWith(DOCS) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.statusCode = 404; return res.end(); }
    res.end(fs.readFileSync(f));
  });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  return { srv, base: `http://127.0.0.1:${srv.address().port}` };
}

let principal, mcp;
before(async () => {
  delete process.env.DELTA_LANGUE;
  delete process.env.DELTA_SOURCE;
  principal = await servir();
  process.env.DELTA_BASE_URL = `${principal.base}/data`;
  process.env.DELTA_COMMUN_URL = `${principal.base}/commun/v1`;
  mcp = await import("../api/mcp.js");
});
after(() => principal.srv.close());

const appeler = async (nom, args = {}, ctx = { langue: "en", source: "commun" }) =>
  (await mcp.traiter({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: nom, arguments: args } }, {}, ctx)).result;
const donnees = async (nom, args, ctx) => (await appeler(nom, args, ctx)).structuredContent;

// Avec d'autres fichiers servis : l'ancienne route et la route commune pointent vers un serveur dédié le temps de `fn`.
async function avec(remplacements, fn) {
  const s = await servir(remplacements);
  const avant = [process.env.DELTA_BASE_URL, process.env.DELTA_COMMUN_URL];
  process.env.DELTA_BASE_URL = `${s.base}/data`;
  process.env.DELTA_COMMUN_URL = `${s.base}/commun/v1`;
  try { await fn(); } finally { [process.env.DELTA_BASE_URL, process.env.DELTA_COMMUN_URL] = avant; s.srv.close(); }
}

test("génération commune réelle : les six appels sont lisibles, étiquetés commun, sans personnel", async () => {
  const appels = [["resume_du_jour", {}], ["chercher_reference", { requete: "/add-dir" }], ["fiche_reference", { id: "claude-code-commandes-add-dir" }],
    ["etat_versions", {}], ["a_tester", {}], ["nouveautes_base", {}]];
  for (const [nom, args] of appels) {
    const r = await appeler(nom, args);
    assert.equal(r.isError, false, `${nom} : ${r.content[0].text.slice(0, 200)}`);
    const d = r.structuredContent.donnees;
    assert.equal(d.source, "commun", nom);
    assert.equal(d.generation, GEN, nom);
    assert.equal(d.publie_le, INDEX.publie_le, nom);
    assert.equal(d.personnel, "absent", nom);
    assert.ok(["recente", "ancienne", "tres_ancienne"].includes(d.fraicheur), nom);
    assert.deepEqual(d.langues, ["en", "fr"], nom);
    const texte = JSON.stringify(r.structuredContent);
    for (const prive of ["pour_toi\":\"", "constats_internes", "recommandation_operer", "/home/"]) assert.equal(texte.includes(prive), false, `${nom} : ${prive}`);
  }
});

test("résumé commun : éléments factuels du jour, impact nul (null) sans liste faussement vide, identifiants de suivi", async () => {
  const s = await donnees("resume_du_jour");
  const veille = lireJson(`commun/v1/${GEN}/veille/claude.json`);
  const jour = veille.jours.map((j) => j.date).sort().at(-1);
  const attendus = veille.entrees.filter((e) => e.publications.some((p) => p.jour === jour)).length;
  const claude = s.perimetres.find((p) => p.perimetre === "claude");
  assert.equal(claude.date, jour);
  assert.equal(claude.total, attendus);
  assert.ok(claude.elements.length > 0 && claude.elements.length === Math.min(attendus, 30));
  assert.equal(claude.synthese, null);
  assert.match(claude.avis, /common factual summary not written yet/);
  for (const e of claude.elements) {
    assert.equal(e.impact, null);
    assert.ok(e.id && Array.isArray(e.kb_refs) && e.sources.every((x) => /^https?:\/\//.test(x.url)));
  }
  const date = veille.jours.map((j) => j.date).sort()[0];
  assert.equal((await donnees("resume_du_jour", { date })).perimetres.find((p) => p.perimetre === "claude").date, date);
});

test("résumé commun : plus de 30 éléments un même jour = troncature annoncée (total, affichees, avis)", async () => {
  const veille = lireJson(`commun/v1/${GEN}/veille/claude.json`);
  const pub = { ...veille.entrees[0].publications[0], jour: "2026-10-30" };
  const entrees = Array.from({ length: 41 }, (_, i) => ({ id: `x-${i}`, identite: `veille:claude:x-${i}`, empreinte: "0".repeat(64), publications: [pub] }));
  const doc = { ...veille, jours: [{ date: "2026-10-30", genere_le: null }], entrees, total: 41 };
  const octets = Buffer.from(JSON.stringify(doc));
  const manifeste = lireJson(`commun/v1/${GEN}/manifest.json`);
  manifeste.fichiers = manifeste.fichiers.map((f) => f.chemin === "veille/claude.json"
    ? { ...f, taille: octets.length, sha256: createHash("sha256").update(octets).digest("hex") } : f);
  const texteManifeste = JSON.stringify(manifeste);
  const index = { ...INDEX, manifest_sha256: createHash("sha256").update(texteManifeste).digest("hex") };
  await avec({ "commun/v1/index.json": index, [`commun/v1/${GEN}/manifest.json`]: texteManifeste, [`commun/v1/${GEN}/veille/claude.json`]: octets.toString() }, async () => {
    const claude = (await donnees("resume_du_jour")).perimetres.find((p) => p.perimetre === "claude");
    assert.equal(claude.total, 41);
    assert.equal(claude.affichees, 30);
    assert.equal(claude.elements.length, 30);
    assert.match(claude.avis, /30 of 41 items shown/);
  });
});

test("fiche commune : texte dans la langue demandée, repli anglais signalé, systèmes, avis personnel indisponible", async () => {
  const fr = (await donnees("fiche_reference", { id: "codex-parametres-windows-sandbox", langue: "fr" })).fiche;
  assert.equal(fr.description_langue, "fr");
  assert.equal(fr.description_repli, false);
  assert.equal(fr.description_statut, "automatique");
  assert.deepEqual(fr.systemes, ["windows"]);
  assert.equal(fr.verdict, null);
  assert.equal(fr.statut_usage, null);
  assert.match(fr.avis_personnel, /avis personnel indisponible/);
  const en = (await donnees("fiche_reference", { id: "claude-code-commandes-add-dir" })).fiche;
  const source = lireJson(`commun/v1/${GEN}/kb/claude/commandes.json`).entrees.find((e) => e.id === "claude-code-commandes-add-dir");
  assert.equal(en.description, source.textes.description.en.texte);
  assert.equal(en.description_langue, "en");
  assert.equal(en.description_statut, "source");
  // une langue absente de l'enveloppe rend l'anglais, annoncé comme repli
  const sansFr = structuredClone(lireJson(`commun/v1/${GEN}/kb/claude/commandes.json`));
  for (const e of sansFr.entrees) delete e.textes.description.fr;
  const octets = Buffer.from(JSON.stringify(sansFr));
  const manifeste = lireJson(`commun/v1/${GEN}/manifest.json`);
  manifeste.fichiers = manifeste.fichiers.map((f) => f.chemin === "kb/claude/commandes.json"
    ? { ...f, taille: octets.length, sha256: createHash("sha256").update(octets).digest("hex") } : f);
  const tm = JSON.stringify(manifeste);
  await avec({ "commun/v1/index.json": { ...INDEX, manifest_sha256: createHash("sha256").update(tm).digest("hex") },
    [`commun/v1/${GEN}/manifest.json`]: tm, [`commun/v1/${GEN}/kb/claude/commandes.json`]: octets.toString() }, async () => {
    const f = (await donnees("fiche_reference", { id: "claude-code-commandes-add-dir", langue: "fr" })).fiche;
    assert.equal(f.description_langue, "en");
    assert.equal(f.description_repli, true);
  });
});

test("référence commune : modèles sans constats ni recommandation OPÉRER, versions installées inconnues, essais absents", async () => {
  const m = (await donnees("fiche_reference", { id: "claude-haiku-5-5:medium" })).fiche;
  assert.equal(m.id, "modele-claude-haiku-5-5-medium");
  for (const absent of ["constats_internes", "recommandation_operer", "sources_internes"]) assert.equal(Object.hasOwn(m, absent) && m[absent]?.length > 0, false, absent);
  assert.equal(m.verdict, null);
  assert.equal(JSON.stringify(m).includes("verdict_operer"), false);
  const v = await donnees("etat_versions");
  assert.equal(v.outils.length, 5);
  for (const o of v.outils) { assert.equal(o.installee, null); assert.equal(o.statut, "inconnu"); assert.equal(o.releve_le, null); assert.match(o.note, /installed version unknown/); }
  assert.equal(v.outils.find((o) => o.outil === "Claude Code").derniere_publiee, lireJson(`commun/v1/${GEN}/versions.json`).entrees[0].derniere_publiee);
  const a = await donnees("a_tester");
  assert.deepEqual([a.total, a.actions.length, a.essais_base.total, a.curseur_suivant], [0, 0, 0, null]);
  assert.match(a.avis, /no personal trials/);
  const n = await donnees("nouveautes_base");
  assert.equal(n.disponible, false);
  assert.equal(n.total, null);
  assert.match(n.avis, new RegExp(GEN));
  // le statut d'usage est personnel : filtre refusé avec la marche à suivre (tool-design.md : l'erreur dit comment repartir)
  const r = await appeler("chercher_reference", { requete: "/model", statut: "utilise" });
  assert.equal(r.isError, true);
  assert.match(r.content[0].text, /^Invalid parameter: `statut` is unavailable on the common reference.*call again without `statut`/);
  // la recherche par nom exact passe par kb/noms.json commun (forme `{schema, noms}`)
  const c = await donnees("chercher_reference", { requete: "/add-dir" });
  assert.equal(c.resultats[0].id, "claude-code-commandes-add-dir");
  assert.equal(c.avis, undefined);
});

test("couche commune illisible : erreur de couche explicite, jamais de repli sur l'ancienne route", async () => {
  await avec({ "commun/v1/index.json": null }, async () => {
    for (const nom of ["resume_du_jour", "fiche_reference", "etat_versions", "a_tester", "nouveautes_base"]) {
      const r = await appeler(nom, nom === "fiche_reference" ? { id: "claude-code-commandes-model" } : {});
      assert.equal(r.isError, true, nom);
      assert.equal(r.content[0].text, "Common reference unavailable: index.json: HTTP 404", nom);
    }
    const fr = await appeler("etat_versions", { langue: "fr" });
    assert.equal(fr.content[0].text, "Référence commune indisponible : index.json : HTTP 404");
  });
  await avec({ "commun/v1/index.json": { ...INDEX, schema_version: 2 } }, async () => {
    assert.match((await appeler("etat_versions")).content[0].text, /^Common reference unavailable: index.json: unknown schema delta.manifest v2 \(expected delta.manifest v1\)/);
  });
  const fichier = lireJson(`commun/v1/${GEN}/versions.json`);
  await avec({ [`commun/v1/${GEN}/versions.json`]: { ...fichier, entrees: [] } }, async () => {
    assert.match((await appeler("etat_versions")).content[0].text, /versions.json: size or hash differs from the manifest/);
  });
  await avec({ [`commun/v1/${GEN}/manifest.json`]: { ...lireJson(`commun/v1/${GEN}/manifest.json`), langues: ["en"] } }, async () => {
    assert.match((await appeler("etat_versions")).content[0].text, /manifest.json: size or hash differs/);
  });
});

// Vue compatible de l'ancienne route (conception §6, L5) : mêmes chemins, champs personnels nuls, versions sans installée.
function vueCompatible() {
  const idx = lireJson("data/claude/index.json");
  const jour = idx.jours.map((j) => j.date).sort().at(-1);
  const q = lireJson(`data/claude/${jour}.json`);
  const neutre = { ...q, synthese: null, elements: q.elements.map((e) => ({ ...e, impact: null, pour_toi: null, action: null, projets_concernes: [] })) };
  const versions = lireJson("data/versions.json").map((l) => ({ outil: l.outil, derniere_publiee: l.derniere_publiee, version: null, statut: null, detectee_le: null }));
  const cmd = lireJson("data/kb/claude/commandes.json");
  const kb = { ...cmd, entrees: cmd.entrees.map((e) => ({ ...e, commentee: false, recommandation: null, statut_usage: null, description: null,
    textes: { description: { en: { texte: e.description_source, statut: "source" }, fr: { texte: `FR ${e.nom}`, statut: "automatique" } } } })) };
  return { jour, q, remplacements: { [`data/claude/${jour}.json`]: neutre, "data/versions.json": versions, "data/kb/claude/commandes.json": kb, "data/etat.json": null } };
}

test("ancienne route en vue compatible : impacts nuls non vidés, installée inconnue, aucun avis fabriqué", async () => {
  const { jour, q, remplacements } = vueCompatible();
  const ctx = { langue: "en", source: "ancienne_route" };
  await avec(remplacements, async () => {
    const claude = (await donnees("resume_du_jour", {}, ctx)).perimetres.find((p) => p.perimetre === "claude");
    assert.equal(claude.date, jour);
    assert.equal(claude.elements.length, q.elements.length);
    assert.equal(claude.tri, "publication");
    assert.ok(claude.elements.every((e) => e.impact === null && e.pour_toi === null));
    assert.equal(claude.compte.inconnu, q.elements.length);
    assert.match(claude.avis, /no personal impact/);
    const v = await donnees("etat_versions", {}, ctx);
    for (const o of v.outils) { assert.equal(o.installee, null); assert.equal(o.statut, "inconnu"); assert.match(o.note, /installed version not recorded/); }
    const f = (await donnees("fiche_reference", { id: "claude-code-commandes-model", langue: "fr" }, ctx)).fiche;
    assert.equal(f.verdict, "en attente de commentaire");
    assert.equal(f.pourquoi, null);
    assert.equal(f.description, "FR /model");
    assert.equal(f.description_langue, "fr");
    const d = (await donnees("chercher_reference", { requete: "/model" }, ctx)).donnees;
    assert.equal(d.source, "ancienne_route");
    assert.equal(d.personnel, "non_separe");
  });
});

test("ancienne route mixte : mêmes six appels lisibles, étiquette ancienne route, jamais « commun »", async () => {
  const ctx = { langue: "fr", source: "ancienne_route" };
  for (const [nom, args] of [["resume_du_jour", {}], ["chercher_reference", { requete: "/model" }], ["fiche_reference", { id: "claude-code-commandes-model" }],
    ["etat_versions", {}], ["a_tester", {}], ["nouveautes_base", {}]]) {
    const r = await appeler(nom, args, ctx);
    assert.equal(r.isError, false, nom);
    assert.equal(r.structuredContent.donnees.source, "ancienne_route", nom);
    assert.equal(JSON.stringify(r.structuredContent).includes("constats_internes"), false, nom);
  }
});

test("langue : anglais par défaut, français par l'adresse ou par appel, même contenu, valeur inconnue refusée", async () => {
  const srv = http.createServer((req, res) => mcp.default(req, res));
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  const url = `http://127.0.0.1:${srv.address().port}/`;
  const rpc = async (corps, suffixe = "") => (await (await fetch(url + suffixe, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(corps) })).json());
  try {
    const en = (await rpc({ jsonrpc: "2.0", id: 1, method: "tools/list" })).result.tools;
    const fr = (await rpc({ jsonrpc: "2.0", id: 1, method: "tools/list" }, "?langue=fr")).result.tools;
    assert.deepEqual(en.map((o) => o.name), fr.map((o) => o.name));
    for (const [a, b] of en.map((o, i) => [o, fr[i]])) {
      assert.match(a.description, /Call it/, a.name);
      assert.match(b.description, /À appeler/, b.name);
      assert.notEqual(a.title, b.title, a.name);
      assert.deepEqual(Object.keys(a.inputSchema.properties), Object.keys(b.inputSchema.properties), a.name);
      // grille (RELECTURE.md) : paramètre décrit, valeurs permises et défaut appliqué déclarés
      assert.deepEqual(a.inputSchema.properties.langue.enum, ["en", "fr"]);
      assert.equal(a.inputSchema.properties.langue.default, "en");
      assert.equal(b.inputSchema.properties.langue.default, "fr");
      // tool-design.md « says what it doesn't do » : chaque description dit ce que rend la référence commune
      assert.match(a.description, /common reference/i, a.name);
      assert.match(b.description, /référence commune/i, b.name);
    }
    const init = (await rpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }, "?source=commun")).result;
    assert.match(init.instructions, /Data source: commun\./);
    const appelHttp = (args, suffixe) => rpc({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "fiche_reference", arguments: args } }, suffixe);
    const a = (await appelHttp({ id: "../x" })).result.content[0].text;
    const b = (await appelHttp({ id: "../x" }, "?langue=fr")).result.content[0].text;
    const c = (await appelHttp({ id: "../x", langue: "fr" })).result.content[0].text;
    assert.equal(a, "Invalid parameter: invalid `id` (e.g. claude-code-commandes-model)");
    assert.equal(b, "Paramètre invalide : `id` invalide (ex. claude-code-commandes-model)");
    assert.equal(c, b);
    assert.equal((await appelHttp({ id: "x", langue: "de" })).result.content[0].text, "Invalid parameter: `langue` must be en or fr");
    // même contenu : les données ne changent pas avec la langue de l'interface (source commune par l'adresse)
    const f1 = (await appelHttp({ id: "claude-code-commandes-add-dir" }, "?source=commun")).result.structuredContent.fiche;
    const f2 = (await appelHttp({ id: "claude-code-commandes-add-dir", langue: "fr" }, "?source=commun")).result.structuredContent.fiche;
    for (const k of ["id", "nom", "usage", "source", "systemes"]) assert.deepEqual(f1[k], f2[k], k);
  } finally { srv.close(); }
});

test("dictionnaires : mêmes clés EN/FR, aucune valeur vide, toute clé utilisée par le serveur existe", async () => {
  const { TEXTES } = await import("../lib/textes.js");
  const en = Object.keys(TEXTES.en).sort(), fr = Object.keys(TEXTES.fr).sort();
  assert.deepEqual(en.filter((k) => !fr.includes(k)), [], "clés absentes du français");
  assert.deepEqual(fr.filter((k) => !en.includes(k)), [], "clés absentes de l'anglais");
  for (const l of ["en", "fr"]) for (const [k, v] of Object.entries(TEXTES[l])) {
    assert.ok(typeof v === "string" && v.trim(), `${l}.${k} vide`);
    assert.deepEqual((v.match(/\{\w+\}/g) || []).sort(), (TEXTES[l === "en" ? "fr" : "en"][k].match(/\{\w+\}/g) || []).sort(), `${k} : mêmes variables`);
  }
  // L4 (relecture L3, À NOTER 1) : le scan couvre aussi les modules partagés et locaux, et les deux lanceurs
  const code = ["../api/mcp.js", "../lib/couches.js", "../lib/modeles.js", "../lib/local.js", "../stdio.js", "../bureau.js"].map((f) => fs.readFileSync(new URL(f, import.meta.url), "utf8")).join("\n");
  const utilisees = new Set([...code.matchAll(/(?:\bt\([^,()]+,\s*|ErreurParametre\(|ErreurTexte\()"([a-z_.]+)"/g)].map((m) => m[1]));
  assert.ok(utilisees.size > 30, `${utilisees.size} clés repérées`);
  for (const k of utilisees) assert.ok(Object.hasOwn(TEXTES.en, k), `clé utilisée absente : ${k}`);
  // aucune phrase d'interface écrite en dur dans le serveur : plus de message français ou anglais hors dictionnaire
  for (const motif of [/ErreurParametre\("`/, /new Error\(`[^$]/, /new Error\("/, /"Paramètre invalide/, /"Données ORQYRA AI/, /: format inattendu/,
    /"format modèles/, /modèle absent :/, /"usage:/, /"invalid JSON"/]) assert.equal(motif.test(code), false, String(motif));
  // les clés des modules partagés et locaux (`ErreurModeles("…")`, `local.motif.<code>`) existent dans les deux langues
  for (const m of code.matchAll(/ErreurModeles\("([a-z_.]+)"/g)) assert.ok(Object.hasOwn(TEXTES.en, m[1]) && Object.hasOwn(TEXTES.fr, m[1]), m[1]);
  for (const m of code.matchAll(/motif: "([a-z_]+)"/g)) if (!["commun_modifie", "commun_indisponible", "fiche_absente", "commun_tres_ancien", "projection_absente", "bilan_absent", "projection_anterieure_au_bilan"].includes(m[1]))
    assert.ok(Object.hasOwn(TEXTES.en, `local.motif.${m[1]}`), m[1]);
});

test("adresses centralisées : copie du bootstrap, aucune adresse de Delta en dur dans le serveur", () => {
  const bootstrap = JSON.parse(fs.readFileSync(path.resolve(ICI, "../../scripts/deltalib/couches/bootstrap.json"), "utf8"));
  const copie = fs.readFileSync(new URL("../lib/config.js", import.meta.url), "utf8");
  const json = JSON.parse(copie.slice(copie.indexOf("(") + 1, copie.lastIndexOf(")")));
  for (const [k, v] of Object.entries(json)) assert.deepEqual(v, bootstrap[k], k);
  const adresses = [bootstrap.site_public_url, bootstrap.mcp_public_url, ...bootstrap.site_anciennes_urls].map((u) => new URL(u).host);
  for (const f of ["../api/mcp.js", "../api/stats.js", ...fs.readdirSync(new URL("../lib/", import.meta.url)).filter((x) => x !== "config.js").map((x) => `../lib/${x}`)]) {
    const s = fs.readFileSync(new URL(f, import.meta.url), "utf8");
    for (const h of adresses) assert.equal(s.includes(h), false, `${f} : ${h} en dur`);
  }
});

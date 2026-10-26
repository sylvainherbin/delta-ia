// Tests du serveur MCP Delta sur les vraies données du dépôt (docs/data servi en local).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DATA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/data");
let donnees, serveurMcp, url, handler, OUTILS;

// Tests historiques en français (même contenu que l'anglais, par défaut du serveur) ; tests L3 de langue plus bas.
process.env.DELTA_LANGUE = "fr";

before(async () => {
  donnees = http.createServer((req, res) => {
    const f = path.join(DATA, decodeURIComponent(req.url.split("?")[0]));
    if (!f.startsWith(DATA) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.statusCode = 404; return res.end(); }
    res.setHeader("Content-Type", "application/json"); res.end(fs.readFileSync(f));
  });
  await new Promise((r) => donnees.listen(0, "127.0.0.1", r));
  process.env.DELTA_BASE_URL = `http://127.0.0.1:${donnees.address().port}`;
  ({ default: handler, OUTILS } = await import("../api/mcp.js"));
  serveurMcp = http.createServer((req, res) => handler(req, res));
  await new Promise((r) => serveurMcp.listen(0, "127.0.0.1", r));
  url = `http://127.0.0.1:${serveurMcp.address().port}/`;
});
after(() => { donnees.close(); serveurMcp.close(); });

async function rpc(corps, methode = "POST") {
  const r = await fetch(url, { method: methode, headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
    body: methode === "POST" ? JSON.stringify(corps) : undefined });
  const texte = await r.text();
  return { statut: r.status, corps: texte ? JSON.parse(texte) : null };
}
const appel = (name, args = {}, id = 9) => rpc({ jsonrpc: "2.0", id, method: "tools/call", params: { name, arguments: args } });

test("initialize, notification et liste des outils", async () => {
  const init = await rpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "1" } } });
  assert.equal(init.statut, 200);
  assert.equal(init.corps.result.serverInfo.name, "delta");
  assert.deepEqual(init.corps.result.capabilities, { tools: { listChanged: false } });
  assert.equal((await rpc({ jsonrpc: "2.0", method: "notifications/initialized" })).statut, 202);
  const liste = await rpc({ jsonrpc: "2.0", id: 2, method: "tools/list" });
  const noms = liste.corps.result.tools.map((t) => t.name).sort();
  assert.deepEqual(noms, ["a_tester", "chercher_reference", "etat_versions", "fiche_reference", "nouveautes_base", "resume_du_jour"]);
  assert.equal(init.corps.result.serverInfo.version, "0.3.0");
  assert.equal(JSON.parse(fs.readFileSync(new URL("../package.json", import.meta.url), "utf8")).version, "0.3.0");
  for (const t of liste.corps.result.tools) assert.match(t.description, /À appeler/, `${t.name} : dire quand l'appeler`);
  for (const t of liste.corps.result.tools) assert.equal(t.annotations.readOnlyHint, true);
});

// Grille de relecture (mcp/RELECTURE.md) : les remarques du plugin mcp-server-dev retenues comme applicables.
test("grille de relecture : titres, annotations et paramètres décrits", async () => {
  const outils = (await rpc({ jsonrpc: "2.0", id: 2, method: "tools/list" })).corps.result.tools;
  for (const t of outils) {
    assert.ok(t.name.length <= 64, `${t.name} : nom de 64 caractères au plus`);
    assert.ok(typeof t.title === "string" && t.title !== t.name.replace(/_/g, " "), `${t.name} : titre lisible, pas le nom recopié`);
    for (const a of ["readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"]) assert.equal(typeof t.annotations[a], "boolean", `${t.name} : ${a}`);
    assert.equal(t.inputSchema.additionalProperties, false, `${t.name} : schéma fermé`);
    for (const [p, s] of Object.entries(t.inputSchema.properties)) assert.ok(s.description, `${t.name}.${p} : paramètre décrit`);
  }
  const schema = Object.fromEntries(outils.map((t) => [t.name, t.inputSchema.properties]));
  assert.equal(schema.chercher_reference.limite.default, 8);
  assert.equal(schema.nouveautes_base.jours.default, 7);
  assert.equal(schema.resume_du_jour.inclure_faibles.default, false);
  // Les motifs du schéma sont ceux que le serveur vérifie lui-même.
  assert.ok(new RegExp(schema.fiche_reference.id.pattern).test("claude-code-commandes-model"));
  assert.ok(!new RegExp(schema.fiche_reference.id.pattern).test("../x"));
  assert.match((await appel("fiche_reference", { id: "../x" })).corps.result.content[0].text, /^Paramètre invalide : `id`/);
  assert.ok(new RegExp(schema.resume_du_jour.date.pattern).test("2026-10-11"));
  assert.ok(!new RegExp(schema.resume_du_jour.date.pattern).test("11/10/2026"));
  assert.match((await appel("resume_du_jour", { date: "11/10/2026" })).corps.result.content[0].text, /^Paramètre invalide : `date`/);
});

test("fiche_reference : un identifiant inconnu renvoie vers chercher_reference", async () => {
  const r = (await appel("fiche_reference", { id: "entree-qui-n-existe-pas" })).corps.result;
  assert.equal(r.isError, true);
  assert.match(r.content[0].text, /aucune entrée entree-qui-n-existe-pas : chercher l'identifiant avec chercher_reference/);
});

test("lecture seule : aucun outil d'écriture ni de déclenchement", async () => {
  const noms = Object.keys(OUTILS).join(" ");
  assert.doesNotMatch(noms, /delta_run|lancer|passage|ecrire|commit|push|valider/);
  const source = fs.readFileSync(new URL("../api/mcp.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /child_process|writeFile|GITHUB_TOKEN|method:\s*"(PUT|DELETE|PATCH)"/);
  assert.equal((await rpc(null, "GET")).statut, 405);
});

test("resume_du_jour sur les données réelles", async () => {
  const r = await appel("resume_du_jour");
  const s = r.corps.result.structuredContent;
  assert.equal(r.corps.result.isError, false);
  assert.deepEqual(s.perimetres.map((p) => p.perimetre), ["claude", "openai", "actu"]);
  const claude = s.perimetres[0];
  assert.match(claude.date, /^\d{4}-\d{2}-\d{2}$/);
  assert.ok(claude.synthese && claude.elements.every((e) => ["fort", "moyen"].includes(e.impact)));
  assert.ok(s.avertissement.includes("jamais à exécuter"));
  assert.equal((await appel("resume_du_jour", { date: "23/09" })).corps.result.isError, true);
});

test("chercher_reference et fiche_reference", async () => {
  const r = (await appel("chercher_reference", { requete: "/model", produit: "claude-code" })).corps.result.structuredContent;
  assert.equal(r.resultats[0].id, "claude-code-commandes-model");
  assert.equal(r.resultats[0].syntaxe_ou_acces, "syntaxe");
  const f = (await appel("fiche_reference", { id: "claude-code-commandes-model" })).corps.result.structuredContent.fiche;
  assert.equal(f.usage, "/model [model]");
  assert.ok(f.pourquoi.includes("`s`"));
  assert.equal((await appel("chercher_reference", { requete: "" })).corps.result.isError, true);
  assert.equal((await appel("chercher_reference", { requete: "x", produit: "gemini" })).corps.result.isError, true);
  assert.equal((await appel("fiche_reference", { id: "../../secret" })).corps.result.isError, true);
});

test("etat_versions et a_tester", async () => {
  const v = (await appel("etat_versions")).corps.result.structuredContent;
  const noms = v.outils.map((o) => o.outil);
  // D75 : « Codex CLI (terminal) » ; l'ancien nom « … non utilisée) » reste accepté jusqu'au prochain /delta, qui réécrit versions.json.
  assert.equal(noms.length, 5);
  assert.deepEqual([noms[0], noms[1], noms[3], noms[4]], ["Claude Code", "Codex (app ChatGPT)", "ChatGPT Desktop", "Claude Desktop"]);
  assert.ok(noms[2].startsWith("Codex CLI (terminal"), noms[2]);
  const a = (await appel("a_tester")).corps.result;
  assert.equal(a.isError, false);
});

test("erreurs JSON-RPC", async () => {
  assert.equal((await rpc({ jsonrpc: "2.0", id: 3, method: "resources/list" })).corps.error.code, -32601);
  assert.equal((await rpc({ nimporte: 1 })).corps.error.code, -32600);
  assert.equal((await appel("lancer_delta")).corps.error.code, -32602);
  const lot = await rpc([{ jsonrpc: "2.0", id: 4, method: "ping" }, { jsonrpc: "2.0", method: "notifications/initialized" }]);
  assert.deepEqual(lot.corps, [{ jsonrpc: "2.0", id: 4, result: {} }]);
});

// ---------------------------------------------------------------------------------------------- D66 : journal
const CLES_JOURNAL = ["methode", "outil", "client", "duree_ms", "statut", "demarrage_froid", "nb_resultats", "cause_erreur"];

async function journal(t, fn) {
  const lignes = [];
  const espion = t.mock.method(console, "log", (s) => lignes.push(s));
  await fn();
  espion.mock.restore();
  return lignes.map((s) => { assert.equal(typeof s, "string"); assert.doesNotMatch(s, /\n/); return JSON.parse(s); });
}

test("journal D66 : une ligne par requête, clés exactes, aucun argument", async (t) => {
  const SECRET = "requete-tres-particuliere-xyz42";
  const lignes = await journal(t, async () => {
    await rpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "claude-ai", version: "0.1.0" } } });
    await rpc({ jsonrpc: "2.0", method: "notifications/initialized" });
    await rpc({ jsonrpc: "2.0", id: 2, method: "tools/list" });
    await appel("chercher_reference", { requete: SECRET, limite: 3 });
    await appel("chercher_reference", { requete: "worktree" });
    await appel("a_tester");
    await appel("fiche_reference", { id: "claude-code-commandes-" + SECRET });
    await appel(SECRET);
    await rpc({ jsonrpc: "2.0", id: 5, method: "ping" });
    await rpc({ jsonrpc: "2.0", id: 6, method: "resources/list" });
  });
  assert.equal(lignes.length, 10);
  for (const l of lignes) assert.deepEqual(Object.keys(l), CLES_JOURNAL);
  const brut = JSON.stringify(lignes);
  assert.ok(!brut.includes(SECRET) && !brut.includes("worktree") && !brut.includes("claude-code-commandes"), "aucun argument dans le journal");
  const [init, notif, liste, cherche0, cherche, aTester, fiche, inconnu, ping, autre] = lignes;
  assert.deepEqual(init.client, { name: "claude-ai", version: "0.1.0" });
  assert.equal(init.methode, "initialize"); assert.equal(init.outil, null);
  assert.deepEqual([notif.methode, notif.statut, notif.client], ["notifications/initialized", "ok", null]);
  assert.deepEqual([liste.methode, liste.outil, liste.nb_resultats], ["tools/list", null, null]);
  assert.deepEqual([cherche0.outil, cherche0.nb_resultats, cherche0.statut], ["chercher_reference", 0, "ok"]);
  assert.ok(cherche.nb_resultats > 0 && cherche.client === null);
  assert.equal(aTester.outil, "a_tester"); assert.equal(typeof aTester.nb_resultats, "number");
  assert.deepEqual([fiche.outil, fiche.nb_resultats], ["fiche_reference", null]);
  assert.deepEqual([inconnu.methode, inconnu.outil, inconnu.statut], ["tools/call", "inconnu", -32602]);
  assert.deepEqual([ping.methode, autre.methode, autre.statut], ["ping", "resources/list", -32601]);
  for (const l of lignes) { assert.equal(typeof l.duree_ms, "number"); assert.equal(l.demarrage_froid, false); }
});

test("journal D66 : méthodes MCP connues nommées, autres notifications « notification », le reste « autre »", async (t) => {
  const SECRET = "methode-tres-particuliere-xyz42";
  const lignes = await journal(t, async () => {
    for (const m of ["notifications/initialized", "notifications/cancelled"]) await rpc({ jsonrpc: "2.0", method: m, params: { requestId: SECRET } });
    await rpc({ jsonrpc: "2.0", method: "notifications/" + SECRET });
    await rpc({ jsonrpc: "2.0", id: 1, method: "resources/list" });
    await rpc({ jsonrpc: "2.0", id: 2, method: "resources/templates/list" });
    await rpc({ jsonrpc: "2.0", id: 3, method: "prompts/list" });
    await rpc({ jsonrpc: "2.0", id: 4, method: "completion/" + SECRET });
    await rpc({ jsonrpc: "2.0", id: 5, method: "notifications/" + SECRET });  // avec id : c'est une requête, pas une notification
    await rpc({ jsonrpc: "2.0", method: "completion/" + SECRET });
    await rpc({ nimporte: 1 });
  });
  assert.deepEqual(lignes.map((l) => [l.methode, l.statut]), [
    ["notifications/initialized", "ok"], ["notifications/cancelled", "ok"], ["notification", "ok"],
    ["resources/list", -32601], ["resources/templates/list", -32601], ["prompts/list", -32601],
    ["autre", -32601], ["autre", -32601], ["autre", "ok"], ["autre", -32600]]);
  for (const l of lignes) assert.deepEqual(Object.keys(l), CLES_JOURNAL);
  assert.ok(!JSON.stringify(lignes).includes(SECRET), "ni nom de méthode inconnu ni paramètre dans le journal");
});

test("journal D66 : démarrage à froid sur la première requête de l'instance seulement", async (t) => {
  const { traiterJournalise } = await import("../api/mcp.js?instance-neuve");
  const lignes = await journal(t, async () => {
    await traiterJournalise({ jsonrpc: "2.0", id: 1, method: "ping" });
    await traiterJournalise({ jsonrpc: "2.0", id: 2, method: "ping" });
  });
  assert.deepEqual(lignes.map((l) => l.demarrage_froid), [true, false]);
});

test("journal D66 : JSON invalide", async (t) => {
  const lignes = await journal(t, async () => {
    await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: "{pas du json" });
  });
  assert.deepEqual(lignes.map((l) => [l.methode, l.statut]), [["autre", -32700]]);
});

test("journal D66 : un outil en erreur (isError) donne statut erreur_outil", async (t) => {
  const lignes = await journal(t, async () => {
    const r = await appel("chercher_reference", { requete: "" });
    assert.equal(r.corps.result.isError, true);
    await appel("fiche_reference", { id: "claude-code-commandes-inexistante" });
    await appel("chercher_reference", { requete: "worktree" });
  });
  assert.deepEqual(lignes.map((l) => [l.outil, l.statut]),
    [["chercher_reference", "erreur_outil"], ["fiche_reference", "erreur_outil"], ["chercher_reference", "ok"]]);
  assert.equal(lignes[0].nb_resultats, null);
});

test("a_tester : id, produit, date de publication et première source par action", async () => {
  const r = (await appel("a_tester")).corps.result;
  assert.equal(r.isError, false);
  for (const a of r.structuredContent.actions) {
    assert.deepEqual(Object.keys(a).sort(), ["id", "id_element", "date", "produit", "date_publication", "titre", "impact", "source"].sort());
    assert.match(a.id, /^action:(claude|openai|actu):/);
    const detail = (await appel("a_tester", { id: a.id })).corps.result.structuredContent.detail;
    assert.ok(detail.action);
    assert.equal(detail.id, a.id);
    assert.equal(typeof a.id, "string");
    assert.ok(a.source === null || (typeof a.source.url === "string" && typeof a.source.officielle === "boolean"));
  }
});

// ---------------------------------------------------------------------------------------------- M2 : nouveautés et essais de la base
const lireDonnee = (f) => JSON.parse(fs.readFileSync(path.join(DATA, f), "utf8"));
const CLES_LIGNE = ["id", "nom", "produit", "categorie", "syntaxe_ou_acces", "usage", "exemple", "verdict", "date_ajout"];

// Sert la base de données avec des fichiers remplacés (`null` = 404, chaîne = corps brut) sur une instance neuve du serveur.
async function avecDonnees(remplacements, fn) {
  const src = http.createServer((req, res) => {
    const nom = decodeURIComponent(req.url.split("?")[0]).replace(/^\//, "");
    if (nom in remplacements) {
      const v = remplacements[nom];
      if (v === null) { res.statusCode = 404; return res.end(); }
      res.setHeader("Content-Type", "application/json"); return res.end(typeof v === "string" ? v : JSON.stringify(v));
    }
    const f = path.join(DATA, nom);
    if (!f.startsWith(DATA) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.statusCode = 404; return res.end(); }
    res.setHeader("Content-Type", "application/json"); res.end(fs.readFileSync(f));
  });
  await new Promise((r) => src.listen(0, "127.0.0.1", r));
  const avant = process.env.DELTA_BASE_URL;
  process.env.DELTA_BASE_URL = `http://127.0.0.1:${src.address().port}`;
  try {
    const m = await import(`../api/mcp.js?donnees=${Math.random()}`);  // module neuf : cache de lecture vide, BASE relue
    await fn((nom, args = {}) => m.traiter({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: nom, arguments: args } }));
  } finally { process.env.DELTA_BASE_URL = avant; src.close(); }
}

test("nouveautes_base : champs, fenêtre, plafond de 30 et défaut de 7 jours", async () => {
  const r = (await appel("nouveautes_base")).corps.result;
  assert.equal(r.isError, false);
  const s = r.structuredContent;
  assert.ok(s.avertissement.includes("jamais à exécuter"));
  assert.equal(s.jours, 7);
  assert.ok(s.entrees.length <= 30 && s.affichees === s.entrees.length && s.total >= s.affichees);
  const recent = lireDonnee("kb/recent.json");
  const attendu = recent.entrees.filter((e) => e.date_ajout >= s.depuis);
  assert.equal(s.total, attendu.length);
  for (const e of s.entrees) { assert.deepEqual(Object.keys(e), CLES_LIGNE); assert.ok(e.date_ajout >= s.depuis); }
  assert.deepEqual(s.entrees.map((e) => e.id), attendu.slice(0, 30).map((e) => e.id));
  const large = (await appel("nouveautes_base", { jours: 30 })).corps.result.structuredContent;
  assert.equal(large.jours, 30);
  assert.ok(large.entrees.length <= 30 && large.total >= s.total);
});

test("nouveautes_base : jours hors de 1 à 30 ou non entier = erreur d'outil", async () => {
  for (const jours of [0, 31, 7.5, "7", null]) {
    const r = (await appel("nouveautes_base", { jours })).corps.result;
    assert.equal(r.isError, true, String(jours));
    assert.match(r.content[0].text, /^Paramètre invalide : `jours`/);
  }
});

test("nouveautes_base : textes bornés, filtre par date, fichier tronqué signalé", async () => {
  const aujourdhui = jourCourant(), ancien = new Date(Date.now() - 20 * 864e5).toISOString().slice(0, 10);
  const longue = "x".repeat(5000);
  const entrees = [...Array.from({ length: 40 }, (_, i) => ({ id: `claude-code-commandes-n${i}`, produit: "claude-code", categorie: "commandes", nom: `n${i}`,
      usage: longue, usage_nature: "syntaxe", exemple: longue, verdict: null, date_ajout: aujourdhui })),
    { id: "codex-commandes-vieux", produit: "codex", categorie: "commandes", nom: "vieux", usage: "/vieux", usage_nature: "etapes", exemple: null, verdict: "ignorer", date_ajout: ancien }];
  await avecDonnees({ "kb/recent.json": { genere_le: aujourdhui, tronque: true, plus_ancienne: aujourdhui, total: 41, entrees } }, async (outil) => {
    const s = (await outil("nouveautes_base", { jours: 7 })).result.structuredContent;
    assert.equal(s.total, 40); assert.equal(s.affichees, 30); assert.equal(s.entrees.length, 30);
    assert.ok(s.entrees[0].usage.length <= 403 && s.entrees[0].exemple.length <= 603);
    assert.equal(s.entrees[0].verdict, "en attente de commentaire");
    assert.match(s.avis, /tronqué/);
    const ouvert = (await outil("nouveautes_base", { jours: 30 })).result.structuredContent;
    assert.equal(ouvert.total, 41);
    assert.equal(ouvert.entrees.length, 30);
    assert.equal(ouvert.entrees[0].syntaxe_ou_acces, "syntaxe");
  });
});

test("nouveautes_base : fichier absent, illisible ou de forme inattendue = isError clair, jamais une liste vide", async () => {
  for (const [corps, motif] of [[null, /kb\/recent\.json : HTTP 404/], ["pas du json", /kb\/recent\.json : JSON illisible/], [{ entrees: "non" }, /kb\/recent\.json : format inattendu/]]) {
    await avecDonnees({ "kb/recent.json": corps }, async (outil) => {
      const r = (await outil("nouveautes_base")).result;
      assert.equal(r.isError, true);
      assert.match(r.content[0].text, /^Données ORQYRA AI indisponibles : /);
      assert.match(r.content[0].text, motif);
      assert.equal(r.structuredContent, undefined);
    });
  }
});

test("a_tester : pagination globale, actions puis base, aucune omission ni duplication", async () => {
  const restants = lireDonnee("kb/a-tester.json").entrees.filter(x => !x.essai);
  let curseur, total, actionsTotal;
  const actions = [], essais = [];
  do {
    const r = (await appel("a_tester", { limite: 20, ...(curseur ? { curseur } : {}) })).corps.result;
    assert.equal(r.isError, false);
    const s = r.structuredContent;
    assert.ok(s.affichees <= 20);
    assert.equal(s.affichees, s.actions.length + s.essais_base.entrees.length);
    if (total !== undefined) assert.equal(s.total, total);
    total = s.total; actionsTotal = s.actions_total;
    actions.push(...s.actions); essais.push(...s.essais_base.entrees);
    curseur = s.curseur_suivant;
  } while (curseur);
  assert.equal(actions.length, actionsTotal);
  assert.equal(new Set(actions.map(e => e.id)).size, actions.length);
  assert.deepEqual(essais.map(e => e.id), restants.map(e => e.id));
  assert.equal(total, actions.length + restants.length);
  if (restants.length) {
    const detail = (await appel("a_tester", { id: restants[0].id })).corps.result;
    const directe = (await appel("fiche_reference", { id: restants[0].id })).corps.result;
    assert.equal(detail.isError, false);
    assert.deepEqual(detail.structuredContent.fiche, directe.structuredContent.fiche);
  }
});

test("a_tester : un essai déclaré fait par une mission (D119) n'est plus proposé", async () => {
  const fichier = lireDonnee("kb/a-tester.json");
  const [premier, ...reste] = fichier.entrees;
  const doc = { ...fichier, entrees: [{ ...premier, essai: "2026-10-11" }, ...reste] };
  await avecDonnees({ "kb/a-tester.json": JSON.stringify(doc) }, async (outil) => {
    const e = (await outil("a_tester")).result.structuredContent.essais_base;
    assert.equal(e.total, fichier.entrees.filter((x) => !x.essai).length - (premier.essai ? 0 : 1));
    assert.ok(!e.entrees.some((x) => x.id === premier.id));
  });
});

test("a_tester : fichier des essais absent ou illisible = isError clair, actions non rendues comme complètes", async () => {
  for (const [corps, motif] of [[null, /kb\/a-tester\.json : HTTP 404/], ["{", /kb\/a-tester\.json : JSON illisible/]]) {
    await avecDonnees({ "kb/a-tester.json": corps }, async (outil) => {
      const r = (await outil("a_tester")).result;
      assert.equal(r.isError, true);
      assert.match(r.content[0].text, motif);
    });
  }
});

test("fiche_reference rend exemple_origine avec l'exemple, null sans exemple", async () => {
  const entrees = [];
  for (const c of ["commandes", "fonctionnalites", "parametres", "skills"]) for (const p of ["claude", "openai"]) for (const e of lireDonnee(`kb/${p}/${c}.json`).entrees) if (!e.retiree) entrees.push(e);
  const avec = entrees.find((e) => e.exemple && e.exemple_origine), sans = entrees.find((e) => !e.exemple);
  assert.ok(avec && sans, "la base réelle doit offrir les deux cas");
  const f = (await appel("fiche_reference", { id: avec.id })).corps.result.structuredContent.fiche;
  assert.equal(f.exemple, avec.exemple); assert.equal(f.exemple_origine, avec.exemple_origine);
  const g = (await appel("fiche_reference", { id: sans.id })).corps.result.structuredContent.fiche;
  assert.deepEqual([g.exemple, g.exemple_origine], [null, null]);
});

test("méthodes locales (D121) : la consultation croisée se trouve, se lit en entier avec ses sources officielles", async () => {
  const enum_ = OUTILS.chercher_reference.inputSchema.properties.categorie.enum;
  assert.ok(enum_.includes("methodes"));
  const trouve = async (args) => (await appel("chercher_reference", args)).corps.result.structuredContent;
  for (const args of [{ requete: "consultation croisée" }, { requete: "ask-codex ask-claude", categorie: "methodes" }, { requete: "consulter", produit: "codex" }, { requete: "consulter", produit: "claude-code" }]) {
    const r = await trouve(args);
    const m = r.resultats.find((x) => x.id === "methode-consultation-croisee");
    assert.ok(m, JSON.stringify(args)); assert.equal(m.categorie, "methodes");
  }
  assert.equal((await trouve({ requete: "consulter", produit: "chatgpt" })).resultats.some((x) => x.id === "methode-consultation-croisee"), false);
  assert.equal((await trouve({ requete: "consultation croisée" })).resultats[0].id, "methode-consultation-croisee", "le slug de la méthode compte dans le nom");
  const f = (await appel("fiche_reference", { id: "methode-consultation-croisee" })).corps.result.structuredContent.fiche;
  assert.deepEqual(f.produits, ["claude-code", "codex"]);
  assert.equal(f.origine, "locale"); assert.equal(f.certitude, "officiel"); assert.equal(f.verifie_le, "2026-10-13");
  assert.ok(f.description.includes("codex exec -s read-only"));
  assert.ok(f.sources.length >= 6 && f.sources.every((x) => x.url.startsWith("https://") && x.libelle));
  assert.ok(f.sources.some((x) => x.url === "https://code.claude.com/docs/en/headless"));
  assert.equal(f.versions["codex"], "0.162.1");
  assert.equal(JSON.stringify(f).includes("/home/"), false);
});

test("méthodes locales (D121) : fichier absent signalé ou retirée ignorée, le reste de la base répond", async () => {
  const m = lireDonnee("kb/methodes.json");
  await avecDonnees({ "kb/methodes.json": null }, async (outil) => {
    const r = (await outil("chercher_reference", { requete: "consultation croisée" })).result.structuredContent;
    assert.equal(r.resultats.some((x) => x.id === "methode-consultation-croisee"), false);
    assert.deepEqual(r.categories_non_lues, [{ categorie: "methodes", raison: "HTTP 404" }]);
    assert.equal((await outil("chercher_reference", { requete: "/model", produit: "claude-code" })).result.structuredContent.resultats[0].id, "claude-code-commandes-model");
  });
  await avecDonnees({ "kb/methodes.json": { ...m, entrees: m.entrees.map((e) => ({ ...e, retiree: true })) } }, async (outil) => {
    assert.equal((await outil("fiche_reference", { id: "methode-consultation-croisee" })).result.isError, true);
  });
});

test("chercher_reference : le nom exact de kb/noms.json passe avant le plein texte", async () => {
  const noms = lireDonnee("kb/noms.json");
  const ids = noms["/model"];
  assert.ok(ids.length >= 1);
  const r = (await appel("chercher_reference", { requete: "  /MODEL " })).corps.result.structuredContent;
  assert.deepEqual(r.resultats.slice(0, ids.length).map((x) => x.id).sort(), [...ids].sort());
  assert.equal(r.avis, undefined);
  // un nom exact devient premier même quand le plein texte le classerait plus bas (aucun mot du texte ne contient « zzexact »)
  const fausse = { "zzexact": ["claude-code-commandes-model"] };
  await avecDonnees({ "kb/noms.json": fausse }, async (outil) => {
    const s = (await outil("chercher_reference", { requete: "zzexact" })).result.structuredContent;
    assert.deepEqual(s.resultats.map((x) => x.id), ["claude-code-commandes-model"]);
    const f = (await outil("chercher_reference", { requete: "zzexact", produit: "codex" })).result.structuredContent;
    assert.equal(f.total, 0);
    const proto = (await outil("chercher_reference", { requete: "constructor" })).result;
    assert.equal(proto.isError, false);
  });
});

test("chercher_reference : sans kb/noms.json, plein texte seul et avis (jamais muet)", async () => {
  for (const corps of [null, "illisible", []]) {
    await avecDonnees({ "kb/noms.json": corps }, async (outil) => {
      const r = (await outil("chercher_reference", { requete: "/model", produit: "claude-code" })).result;
      assert.equal(r.isError, false);
      assert.equal(r.structuredContent.resultats[0].id, "claude-code-commandes-model");
      assert.match(r.structuredContent.avis, /^index des noms indisponible \(.+\) : recherche plein texte seule$/);
    });
  }
});

test("modèles × efforts : chercher_reference et fiche_reference couvrent les 17 modèles et résolvent les alias", async () => {
  const enum_ = OUTILS.chercher_reference.inputSchema.properties.categorie.enum;
  assert.ok(enum_.includes("modeles"));
  const trouve = async (args) => (await appel("chercher_reference", args)).corps.result.structuredContent;
  for (const [requete, idAttendu] of [
    ["claude-haiku-5-5", "modele-claude-haiku-5-5-medium"],
    ["gpt-6.1-sol", "modele-gpt-6-1-sol-low"],
    ["gemini-4-argon", "modele-gemini-4-argon-high"],
    ["Qwen3.5-4B", "modele-qwen3-5-4b-sans-reflexion"],
  ]) {
    const r = await trouve({ requete, categorie: "modeles" });
    assert.ok(r.total >= 1, requete);
    assert.equal(r.resultats[0].id, idAttendu, requete);
    assert.equal(r.resultats[0].categorie, "modeles");
    assert.ok(r.resultats[0].cout_quota && r.resultats[0].forfait, requete);
  }
  // résolution directe par id canonique ou par alias (modèle seul → effort par défaut, modèle:effort → couple exact)
  const haikuDefaut = (await appel("fiche_reference", { id: "claude:claude-haiku-5-5" })).corps.result.structuredContent.fiche;
  assert.equal(haikuDefaut.id, "modele-claude-haiku-5-5-medium");
  assert.equal(haikuDefaut.effort, "medium");
  assert.equal(haikuDefaut.effort_defaut, true);
  assert.equal(haikuDefaut.date_releve, "2026-10-20");
  assert.ok(haikuDefaut.niveaux_effort_disponibles.length === 5);
  assert.ok(haikuDefaut.benchmarks.some((b) => b.nom.includes("GDPval-AA") && b.verifie === true));
  assert.ok(haikuDefaut.benchmarks.every((b) => b.verifie === true && b.extrait));

  const sonnetAgyHigh = (await appel("fiche_reference", { id: "antigravity:claude-sonnet-5-5:high" })).corps.result.structuredContent.fiche;
  assert.equal(sonnetAgyHigh.id, "modele-antigravity-claude-sonnet-5-5-high");
  assert.ok(sonnetAgyHigh.sources_internes.some((c) => c.date === "2026-10-19" && c.constat.includes("21 min")));

  // L3 : l'ancien JSON mixte porte encore constats internes et recommandation OPÉRER ; la réponse publique ne les rend pas.
  const brut = lireDonnee("kb/modeles.json");
  assert.ok(brut.modeles["Qwen3.5-4B"].constats_internes.some((c) => c.constat.includes("Modèles locaux lents et faibles")), "fixture d'ancien format mixte");
  assert.ok(brut.entrees.some((e) => e.recommandation_operer?.pourquoi?.includes("extraction en un seul appel")), "fixture d'ancien format mixte");
  const qwenLocal = (await appel("fiche_reference", { id: "Qwen3.5-4B" })).corps.result.structuredContent.fiche;
  assert.equal(qwenLocal.id, "modele-qwen3-5-4b-sans-reflexion");
  const texte = JSON.stringify(qwenLocal);
  for (const absent of ["constats_internes", "recommandation_operer", "Modèles locaux lents et faibles", "extraction en un seul appel", "Constats internes datés", "Recommandation OPÉRER", "verdict_operer"])
    assert.equal(texte.includes(absent), false, absent);
  assert.equal(qwenLocal.verdict, null);
  assert.equal(texte.includes("/home/"), false);
});

test("modèles × efforts : fichier absent signalé ou retirée ignorée, le reste de la base répond", async () => {
  const m = lireDonnee("kb/modeles.json");
  await avecDonnees({ "kb/modeles.json": null }, async (outil) => {
    const r = (await outil("chercher_reference", { requete: "claude-haiku-5-5", categorie: "modeles" })).result.structuredContent;
    assert.equal(r.total, 0);
    assert.deepEqual(r.categories_non_lues, [{ categorie: "modeles", raison: "HTTP 404" }]);
    assert.match(r.avis, /recherche incomplète.*modeles/);
    assert.equal((await outil("chercher_reference", { requete: "/model", produit: "claude-code" })).result.structuredContent.resultats[0].id, "claude-code-commandes-model");
  });
  await avecDonnees({ "kb/modeles.json": { ...m, entrees: m.entrees.map((e) => ({ ...e, retiree: true })) } }, async (outil) => {
    assert.equal((await outil("fiche_reference", { id: "modele-claude-haiku-5-5-medium" })).result.isError, true);
  });
});

// Requêtes réelles d'agents (transcripts du 12/10/2026) qui rendaient zéro avec le ET strict : produit, catégorie, début attendu.
const REQUETES_REELLES = [
  ["commande /model", "claude-code", "commandes", "claude-code-commandes-model"],
  ["/compact compacter contexte", "claude-code", undefined, "claude-code-commandes-compact"],
  ["permissions allow Bash settings.json", "claude-code", undefined, "claude-code-parametres-permissions"],
  ["permissions.allow Bash wildcard", "claude-code", undefined, "claude-code-parametres-permissions-allow"],
  ["Stop SessionEnd SubagentStop", "claude-code", undefined, "claude-code-parametres-hook-subagentstop"],
  ["remote control connecter session", "claude-code", undefined, "claude-code-commandes-remote-control"],
  ["subagents agents personnalisés", "claude-code", undefined, null],
  ["claude -p headless output-format json json-schema automatisation", "claude-code", undefined, null],
  ["codex exec non interactif JSON schema automatisation", "codex", undefined, "codex-fonctionnalites-page-non-interactive-mode"],
  ["Fable limite hebdomadaire séparée", "claude", undefined, null],
];

test("chercher_reference : repli par nombre de mots trouvés sur dix requêtes réelles à zéro, avis dit", async () => {
  let replis = 0;
  for (const [requete, produit, categorie, premier] of REQUETES_REELLES) {
    const r = (await appel("chercher_reference", { requete, produit, ...(categorie ? { categorie } : {}) })).corps.result.structuredContent;
    assert.ok(r.total > 0 && r.resultats.length > 0, `« ${requete} » rend au moins une fiche`);
    if (r.avis !== undefined) {
      assert.match(r.avis, /résultats partiels possibles : couverture des mots/, requete);
      replis += 1;
    }
    if (premier) assert.ok(r.resultats.some(e => e.id === premier), `cible toujours visible : ${requete}`);
  }
  assert.ok(replis > 0, "le repli reste explicite ; les familles lexicales peuvent éviter un repli ancien");
  // une requête hors base reste à zéro, sans avis de résultats partiels
  const hors = (await appel("chercher_reference", { requete: "Groq Cerebras" })).corps.result.structuredContent;
  assert.deepEqual([hors.total, hors.resultats.length, hors.avis], [0, 0, undefined]);
});

function base(entrees, noms = {}) {
  const vide = ["fonctionnalites", "skills", "plugins", "mcp", "parametres", "raccourcis"];
  const r = { "kb/noms.json": noms, "kb/claude/commandes.json": { entrees }, "kb/openai/commandes.json": { entrees: [] }, "kb/methodes.json": { entrees: [] }, "kb/modeles.json": { schema_version: 2, modeles: {}, entrees: [] } };
  for (const c of vide) { r[`kb/claude/${c}.json`] = { entrees: [] }; r[`kb/openai/${c}.json`] = { entrees: [] }; }
  return r;
}
const fiche3 = (id, nom, usage) => ({ id, nom, produit: "claude-code", categorie: "commandes", usage, description: null, commentee: false });
const BASE3 = [fiche3("a", "alpha-un", "alpha beta gamma"), fiche3("b", "beta-deux", "beta delta"), fiche3("c", "gamma-trois", "gamma")];

test("chercher_reference : couverture et titre, seuil des partiels et filtres", async () => {
  await avecDonnees(base(BASE3), async (outil) => {
    const cherche = async (requete, args = {}) => (await outil("chercher_reference", { requete, ...args })).result.structuredContent;
    const strict = await cherche("beta gamma");  // une fiche contient les deux mots : pas de repli
    assert.equal(strict.resultats[0].id, "a");
    assert.equal(strict.total, 3);  // les correspondances partielles restent consultables
    assert.match(strict.avis, /résultats partiels possibles/);
    // repli : au moins la moitié des mots retenus, arrondie au supérieur
    const seuil2 = await cherche("alpha beta gamma zzz");  // 4 mots, seuil 2 : seule « a » en a 3
    assert.deepEqual([seuil2.resultats.map((x) => x.id), seuil2.total], [["a"], 1]);
    assert.match(seuil2.avis, /^résultats partiels possibles : couverture des mots/);
    const seuil3 = await cherche("beta delta gamma zzz");  // seuil 2 : a (beta, gamma) et b (beta, delta), pas c
    assert.deepEqual(seuil3.resultats.map((x) => x.id).sort(), ["a", "b"]);
    assert.equal(seuil3.total, 2);
    const trois = await cherche("alpha qqq www");  // 3 mots, seuil 2 : un seul mot trouvé ne suffit pas
    assert.deepEqual([trois.total, trois.avis], [0, undefined]);
    const un = await cherche("alpha zzz");  // 2 mots, seuil 1
    assert.deepEqual(un.resultats.map((x) => x.id), ["a"]);
    // classement par nombre de mots trouvés : a (3) avant b (2) avant c (1)
    const classe = await cherche("alpha beta delta gamma zzzz", { limite: 8 });
    assert.deepEqual(classe.resultats.map((x) => x.id), ["a", "b", "c"].filter((i) => classe.resultats.some((x) => x.id === i)));
    assert.deepEqual((await cherche("alpha beta delta gamma zzzz", { limite: 1 })).resultats.map((x) => x.id), ["a"]);
    assert.equal((await cherche("alpha beta delta gamma zzzz", { limite: 1 })).total, classe.total);
    // mots vides et mots d'un caractère écartés : « le de » ne retient rien, « le de alpha » retient « alpha »
    assert.equal((await cherche("le de")).total, 0);
    assert.deepEqual((await cherche("le de alpha")).resultats.map((x) => x.id), ["a"]);
    assert.deepEqual((await cherche("the of alpha")).resultats.map((x) => x.id), ["a"]);
    // préfixe « - » ou « / » : cherché aussi sans lui
    assert.deepEqual((await cherche("/alpha zzz")).resultats.map((x) => x.id), ["a"]);
    assert.deepEqual((await cherche("--delta zzz")).resultats.map((x) => x.id), []);  // « -delta » n'est pas dans le texte
    assert.deepEqual((await cherche("-delta zzz")).resultats.map((x) => x.id), ["b"]);
    // les filtres s'appliquent aussi au repli
    assert.equal((await cherche("alpha zzz", { produit: "codex" })).total, 0);
  });
});

test("chercher_reference : chaque mot est essayé contre kb/noms.json, le nom de la requête entière reste premier", async () => {
  await avecDonnees(base(BASE3, { "/alpha": ["c"], "alpha zzz": ["b"] }), async (outil) => {
    const cherche = async (requete) => (await outil("chercher_reference", { requete })).result.structuredContent;
    // « commande /alpha » : aucun mot de « commande » dans la base ; le nom exact « /alpha » désigne « c », devant « a » (mot trouvé dans le texte)
    const mot = await cherche("commande /alpha");
    assert.deepEqual(mot.resultats.map((x) => x.id), ["c", "a"]);
    assert.match(mot.avis, /résultats partiels/);
    // nom exact de la requête entière : il passe avant tout, sans avis de repli
    const entier = await cherche("alpha zzz");
    assert.equal(entier.resultats[0].id, "b");
    assert.equal(entier.avis, undefined);
  });
});

test("chercher_reference : repli et index des noms indisponible, deux avis dits", async () => {
  await avecDonnees({ ...base(BASE3), "kb/noms.json": null }, async (outil) => {
    const r = (await outil("chercher_reference", { requete: "alpha zzz" })).result.structuredContent;
    assert.deepEqual(r.resultats.map((x) => x.id), ["a"]);
    assert.match(r.avis, /^index des noms indisponible \(.+\) : recherche plein texte seule ; résultats partiels possibles/);
  });
});

test("chercher_reference et fiche_reference : catégories non lues signalées explicitement avec leur raison", async () => {
  const donnees = {
    ...base(BASE3),
    "kb/claude/skills.json": null,  // HTTP 404
    "kb/openai/mcp.json": "{tronque",  // JSON illisible
    "kb/methodes.json": { entrees: "pas-un-tableau" },  // format inattendu
  };
  await avecDonnees(donnees, async (outil) => {
    const attendu = [
      { categorie: "claude/skills", raison: "HTTP 404" },
      { categorie: "openai/mcp", raison: "JSON illisible" },
      { categorie: "methodes", raison: "format inattendu" },
    ];
    const r = (await outil("chercher_reference", { requete: "beta gamma" })).result.structuredContent;
    assert.equal(r.resultats[0].id, "a");
    assert.deepEqual(r.categories_non_lues, attendu);
    assert.match(r.avis, /recherche incomplète — catégories non lues : claude\/skills \(HTTP 404\), openai\/mcp \(JSON illisible\), methodes \(format inattendu\)/);
    // Même quand la recherche ne trouve aucun résultat, l'incomplétude est signalée
    const vide = (await outil("chercher_reference", { requete: "introuvable" })).result.structuredContent;
    assert.equal(vide.total, 0);
    assert.deepEqual(vide.categories_non_lues, attendu);
    assert.match(vide.avis, /^recherche incomplète — catégories non lues : claude\/skills \(HTTP 404\)/);
    // fiche_reference : une fiche présente dans une catégorie lue reste servie ; une fiche absente renvoie une erreur d'indisponibilité
    const ok = await outil("fiche_reference", { id: "a" });
    assert.equal(ok.result.isError, false);
    assert.equal(ok.result.structuredContent.fiche.id, "a");
    const ko = await outil("fiche_reference", { id: "absente" });
    assert.equal(ko.result.isError, true);
    assert.match(ko.result.content[0].text, /^Données ORQYRA AI indisponibles : catégories non lues \(claude\/skills \(HTTP 404\), openai\/mcp \(JSON illisible\), methodes \(format inattendu\)\)/);
  });
});

test("compteur D100 et journal D66 couvrent nouveautes_base et a_tester sans changement", async (t) => {
  await avecUpstash(t, async ({ hash }) => {
    const lignes = await journal(t, async () => {
      await appel("nouveautes_base", { jours: 3 });
      await appel("nouveautes_base", { jours: 99 });
      await appel("a_tester");
      await attendre();
    });
    assert.equal(lignes.length, 3);
    for (const l of lignes) assert.deepEqual(Object.keys(l), CLES_JOURNAL);
    assert.deepEqual(lignes.map((l) => [l.outil, l.statut]), [["nouveautes_base", "ok"], ["nouveautes_base", "erreur_outil"], ["a_tester", "ok"]]);
    assert.ok(!JSON.stringify(lignes).includes("\"jours\""), "aucun argument dans le journal");
    const h = Object.fromEntries(hash.get(`mcp:j:${jourCourant()}`));
    assert.deepEqual(h, { "req:tools/call": 3, "outil:nouveautes_base": 2, "erreur:nouveautes_base": 1, "cause:nouveautes_base/param.jours": 1, "outil:a_tester": 1 });
    assert.ok(!Object.keys(h).some((k) => k.includes("jours") || k.includes("99")));
  });
});

// ---------------------------------------------------------------------------------------------- compteur agrégé (amende D66)
// Faux Upstash : serveur HTTP local qui journalise les appels /pipeline et tient les hash en mémoire.
const CLES_ENV = ["KV_REST_API_URL", "KV_REST_API_TOKEN"];

async function avecUpstash(t, fn, { mode = "ok" } = {}) {
  const appels = [], hash = new Map();
  const faux = http.createServer(async (req, res) => {
    const morceaux = []; for await (const m of req) morceaux.push(m);
    const commandes = JSON.parse(Buffer.concat(morceaux).toString("utf8"));
    appels.push({ chemin: req.url, auth: req.headers.authorization, commandes });
    if (mode === "500") { res.statusCode = 500; return res.end("{}"); }
    if (mode === "bloque") return;  // ne répond jamais : le délai de 500 ms doit couper
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(commandes.map(([cmd, cle, champ, n]) => {
      if (cmd === "HINCRBY") { const h = hash.get(cle) ?? new Map(); hash.set(cle, h); h.set(champ, (h.get(champ) || 0) + n); return { result: h.get(champ) }; }
      if (cmd === "HGETALL") return { result: [...(hash.get(cle) ?? new Map())].flatMap(([k, v]) => [k, String(v)]) };
      return { result: 1 };
    })));
  });
  await new Promise((r) => faux.listen(0, "127.0.0.1", r));
  const avant = Object.fromEntries(CLES_ENV.map((k) => [k, process.env[k]]));
  process.env.KV_REST_API_URL = `http://127.0.0.1:${faux.address().port}`;
  process.env.KV_REST_API_TOKEN = "jeton-de-test";
  try { await fn({ appels, hash }); } finally {
    for (const k of CLES_ENV) { if (avant[k] === undefined) delete process.env[k]; else process.env[k] = avant[k]; }
    faux.closeAllConnections(); faux.close();
  }
}

const jourCourant = () => new Date().toISOString().slice(0, 10);
const attendre = async () => (await import("../lib/compteur.js")).compteursEnCours();
const initialiser = (nom) => rpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: nom, version: "9.9.9-precise" } } });

test("compteur : incréments pour initialize, tools/call avec et sans résultat, erreur", async (t) => {
  await avecUpstash(t, async ({ appels, hash }) => {
    await initialiser("claude-ai");
    await attendre();
    await appel("chercher_reference", { requete: "terme-qui-ne-donne-rien-xyz42" });
    await appel("chercher_reference", { requete: "worktree" });
    await appel("fiche_reference", { id: "claude-code-commandes-inexistante" });
    await appel("lancer_delta");
    await rpc({ jsonrpc: "2.0", id: 5, method: "ping" });
    await attendre();
    const h = Object.fromEntries(hash.get(`mcp:j:${jourCourant()}`));
    assert.deepEqual(h, {
      "req:initialize": 1, "client:claude-ai": 1,
      "req:tools/call": 4, "outil:chercher_reference": 2, "zero:chercher_reference": 1,
      "outil:fiche_reference": 1, "erreur:fiche_reference": 1, "cause:fiche_reference/param.id_inconnu": 1, "outil:inconnu": 1, "erreur:inconnu": 1,
      "req:ping": 1 });
    assert.equal(appels.length, 6, "un appel pipeline par requête MCP");
    for (const a of appels) {
      assert.equal(a.chemin, "/pipeline"); assert.equal(a.auth, "Bearer jeton-de-test");
      assert.deepEqual(a.commandes.at(-1), ["EXPIRE", `mcp:j:${jourCourant()}`, 400 * 86400]);
    }
  });
});

test("compteur : un lot est compté en un seul appel pipeline, notifications comprises", async (t) => {
  await avecUpstash(t, async ({ appels, hash }) => {
    await rpc([{ jsonrpc: "2.0", id: 4, method: "ping" }, { jsonrpc: "2.0", method: "notifications/initialized" }]);
    await attendre();
    assert.equal(appels.length, 1);
    assert.deepEqual(Object.fromEntries(hash.get(`mcp:j:${jourCourant()}`)), { "req:ping": 1, "req:notifications/initialized": 1 });
  });
});

test("compteur : méthodes nommées, notifications comptées, erreurs réelles distinctes des méthodes non prises en charge", async (t) => {
  await avecUpstash(t, async ({ hash }) => {
    await rpc({ jsonrpc: "2.0", method: "notifications/initialized" });
    await rpc({ jsonrpc: "2.0", method: "notifications/cancelled" });
    await rpc({ jsonrpc: "2.0", method: "notifications/roots/list_changed" });
    await rpc({ jsonrpc: "2.0", id: 1, method: "resources/list" });
    await rpc({ jsonrpc: "2.0", id: 2, method: "resources/templates/list" });
    await rpc({ jsonrpc: "2.0", id: 3, method: "prompts/list" });
    await rpc({ jsonrpc: "2.0", id: 4, method: "logging/setLevel" });
    await rpc({ nimporte: 1 });
    await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: "{pas du json" });
    await appel("fiche_reference", { id: "claude-code-commandes-inexistante" });
    await attendre();
    assert.deepEqual(Object.fromEntries(hash.get(`mcp:j:${jourCourant()}`)), {
      "req:notifications/initialized": 1, "req:notifications/cancelled": 1, "req:notification": 1,
      "req:resources/list": 1, "erreur:resources/list": 1, "req:resources/templates/list": 1, "erreur:resources/templates/list": 1,
      "req:prompts/list": 1, "erreur:prompts/list": 1, "req:autre": 3, "erreur:autre": 1, "erreur:invalide": 2,
      "req:tools/call": 1, "outil:fiche_reference": 1, "erreur:fiche_reference": 1, "cause:fiche_reference/param.id_inconnu": 1 });
  });
});

test("compteur : aucun argument, requête, IP, User-Agent, session ni version dans les clés", async (t) => {
  const SECRET = "requete-tres-particuliere-xyz42";
  await avecUpstash(t, async ({ appels }) => {
    await fetch(url, { method: "POST", headers: { "content-type": "application/json", "user-agent": "agent-secret-ua", "mcp-session-id": "session-secrete" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", clientInfo: { name: "client<script>é/" + "x".repeat(60), version: "9.9.9-precise" } } }) });
    await appel("chercher_reference", { requete: SECRET, limite: 3 });
    await appel("fiche_reference", { id: "claude-code-commandes-" + SECRET });
    await appel(SECRET);
    await attendre();
    const brut = JSON.stringify(appels.map((a) => a.commandes));
    for (const interdit of [SECRET, "worktree", "agent-secret-ua", "session-secrete", "9.9.9", "127.0.0.1", "claude-code-commandes", "<script>", "é"]) assert.ok(!brut.includes(interdit), interdit);
    const champsEcrits = appels.flatMap((a) => a.commandes).filter((c) => c[0] === "HINCRBY").map((c) => c[2]);
    const client = champsEcrits.find((c) => c.startsWith("client:"));
    assert.ok(client.length <= "client:".length + 40, client);
    for (const c of champsEcrits) assert.match(c, /^(req|outil|zero|erreur|client|cause):[A-Za-z0-9._ \/-]+$/);
  });
});

test("compteur : stockage absent = aucun appel, /stats inactif", async (t) => {
  const stats = (await import("../api/stats.js")).default;
  const avant = Object.fromEntries(CLES_ENV.map((k) => [k, process.env[k]]));
  for (const k of CLES_ENV) delete process.env[k];
  const appels = [];
  const reel = globalThis.fetch;
  const espion = t.mock.method(globalThis, "fetch", (u, o) => { appels.push(String(u)); return reel(u, o); });
  try {
    await appel("ping"); await rpc({ jsonrpc: "2.0", id: 1, method: "ping" });
    await attendre();
    assert.deepEqual(appels.filter((u) => !u.startsWith("http://127.0.0.1")), [], "aucun appel hors serveur de test");
    const { corps, statut, entetes } = await lireStatsHttp(stats, "/stats");
    assert.equal(statut, 200); assert.deepEqual(corps, { statut: "inactif" });
    assert.equal(entetes["cache-control"], "no-store");
  } finally {
    espion.mock.restore();
    for (const k of CLES_ENV) if (avant[k] !== undefined) process.env[k] = avant[k];
  }
});

test("compteur : erreur ou lenteur du stockage = réponse MCP intacte, une ligne « echec »", async (t) => {
  for (const mode of ["500", "bloque"]) {
    await avecUpstash(t, async () => {
      const lignes = await journal(t, async () => {
        const debut = Date.now();
        const r = await rpc({ jsonrpc: "2.0", id: 7, method: "ping" });
        assert.deepEqual(r.corps, { jsonrpc: "2.0", id: 7, result: {} });
        assert.ok(Date.now() - debut < 400, "la réponse n'attend pas le stockage");
        await attendre();
      });
      assert.deepEqual(lignes.filter((l) => l.compteur).map((l) => l), [{ compteur: "echec" }]);
      assert.equal(lignes.filter((l) => l.methode).length, 1);
    }, { mode });
  }
});

async function lireStatsHttp(gestionnaire, chemin, methode = "GET") {
  const srv = http.createServer((req, res) => gestionnaire(req, res));
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  try {
    const r = await fetch(`http://127.0.0.1:${srv.address().port}${chemin}`, { method: methode });
    const texte = await r.text();
    return { statut: r.status, corps: texte ? JSON.parse(texte) : null, entetes: Object.fromEntries(r.headers) };
  } finally { srv.closeAllConnections(); srv.close(); }
}

test("/stats : agrégats par jour, total, bornes de jours, CORS et cache", async (t) => {
  const stats = (await import("../api/stats.js")).default;
  await avecUpstash(t, async ({ appels }) => {
    await initialiser("claude-ai");
    await appel("chercher_reference", { requete: "terme-qui-ne-donne-rien-xyz42" });
    await appel("chercher_reference", { requete: "worktree" });
    await appel("chercher_reference", { requete: "", produit: "prive" });
    await attendre();
    appels.length = 0;
    const r = await lireStatsHttp(stats, "/stats?jours=3");
    assert.equal(r.statut, 200);
    assert.deepEqual(Object.keys(r.corps), ["statut", "genere_le", "jours", "total"]);
    assert.equal(r.corps.statut, "ok");
    assert.equal(r.corps.jours.length, 3);
    assert.equal(r.corps.jours.at(-1).jour, jourCourant());
    assert.deepEqual(Object.keys(r.corps.jours[0]), ["jour", "req", "outils", "zero", "erreurs", "clients", "causes_erreurs"]);
    assert.deepEqual(r.corps.jours[0].req, {});
    const auj = r.corps.jours.at(-1);
    assert.deepEqual(auj.req, { initialize: 1, "tools/call": 3 });
    assert.deepEqual(auj.outils, { chercher_reference: 3 });
    assert.deepEqual(auj.zero, { chercher_reference: 1 });
    assert.deepEqual(auj.clients, { "claude-ai": 1 });
    assert.deepEqual(r.corps.total.outils, { chercher_reference: 3 });
    assert.deepEqual(auj.causes_erreurs, { "chercher_reference/param.requete": 1 });
    assert.deepEqual(r.corps.total.causes_erreurs, auj.causes_erreurs);
    assert.equal(r.entetes["cache-control"], "public, max-age=300");
    assert.equal(r.entetes["access-control-allow-origin"], "*");
    assert.deepEqual(appels.map((a) => a.commandes.map((c) => c[0])), [["HGETALL", "HGETALL", "HGETALL"]], "lecture seule : HGETALL en pipeline");
    for (const [q, n] of [["", 30], ["?jours=500", 90], ["?jours=0", 1], ["?jours=abc", 30]]) {
      assert.equal((await lireStatsHttp(stats, "/stats" + q)).corps.jours.length, n, q);
    }
    assert.equal((await lireStatsHttp(stats, "/stats", "POST")).statut, 405);
    assert.equal((await lireStatsHttp(stats, "/stats", "OPTIONS")).statut, 204);
  });
});

test("/stats : stockage en erreur = 502 sans détail ; GET /mcp reste 405", async (t) => {
  const stats = (await import("../api/stats.js")).default;
  await avecUpstash(t, async () => {
    const r = await lireStatsHttp(stats, "/stats");
    assert.equal(r.statut, 502); assert.equal(r.corps.statut, "erreur");
    assert.equal(r.entetes["cache-control"], "no-store");
  }, { mode: "500" });
  assert.equal((await rpc(null, "GET")).statut, 405);
});

test("vercel.json : /stats réécrit vers /api/stats, cache no-store ailleurs seulement", () => {
  const v = JSON.parse(fs.readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  assert.deepEqual(v.rewrites.map((r) => [r.source, r.destination]), [["/mcp", "/api/mcp"], ["/stats", "/api/stats"]]);
  const re = new RegExp("^" + v.headers[0].source.replace("/(", "/(") + "$");
  assert.ok(re.test("/mcp") && !re.test("/stats"));
});

test("modèles : alias partagé signale les candidats, identifiant canonique prioritaire", async () => {
  for (const id of ["claude-sonnet-5-5", "claude-sonnet-5-5:high", "claude-opus-5-5:medium"]) {
    const r = (await appel("fiche_reference", { id })).corps.result;
    assert.equal(r.isError, false);
    assert.equal(r.structuredContent.ambigu, true);
    const candidats = r.structuredContent.candidats;
    assert.equal(candidats.length, 2);
    assert.deepEqual(new Set(candidats.map((c) => c.executant)), new Set(["claude", "antigravity"]));
    assert.match(r.structuredContent.avis, /identifiant canonique/);
    for (const c of candidats) assert.equal((await appel("fiche_reference", { id: c.id })).corps.result.structuredContent.fiche.id, c.id);
  }
  const s = (await appel("chercher_reference", { requete: "claude-sonnet-5-5:high" })).corps.result.structuredContent;
  assert.match(s.avis, /alias ambigu/);
  assert.equal(s.resultats.filter((e) => e.effort === "high").length, 2);
});

test("recherche mixte : effort, quota et model effort gardent les fiches de documentation", async () => {
  const docs = [
    { id: "doc-effort", nom: "/effort", produit: "claude-code", categorie: "commandes", usage: "effort", description: "Réglage du model effort et quota", commentee: false },
  ];
  const modeles = { m: { nom_modele: "Claude Sonnet", produit: "claude-code", categorie: "modeles", executant: "claude", aliases_effort: [], description_commune: "model effort quota", commentee: true } };
  const entrees = Array.from({ length: 24 }, (_, i) => ({ modele: "m", effort: i % 2 ? "medium" : "high", id: `model-${i}`, nom: `Claude Sonnet effort ${i}`, categorie: "modeles", description: "model effort quota" }));
  const donnees = base(docs);
  donnees["kb/modeles.json"] = { schema_version: 2, modeles, entrees };
  // Plus de vingt fiches modèles commentées rivalisent avec une fiche de documentation non commentée.
  await avecDonnees(donnees, async (outil) => {
    for (const requete of ["effort", "quota", "model effort"]) {
      const r = (await outil("chercher_reference", { requete, produit: "claude-code", limite: 20 })).result.structuredContent;
      assert.equal(r.total, 25, requete);
      assert.ok(r.resultats.some((e) => e.id === "doc-effort"), requete);
      assert.match(r.avis, /résultats affichés sur 25 correspondances/, requete);
    }
    const effortSansProduit = (await outil("chercher_reference", { requete: "effort", limite: 20 })).result.structuredContent;
    assert.ok(effortSansProduit.resultats.some((e) => e.id === "doc-effort"), "effort sans filtre produit conserve sa documentation");
  });
  for (const requete of ["effort", "model effort"]) {
    const r = (await appel("chercher_reference", { requete, produit: "claude-code", limite: 20 })).corps.result.structuredContent;
    assert.ok(r.resultats.some((e) => e.categorie !== "modeles"), requete);
  }
  const quota = (await appel("chercher_reference", { requete: "quota", produit: "claude-code", limite: 20 })).corps.result.structuredContent;
  assert.ok(quota.resultats.some((e) => e.categorie !== "modeles"), "les données vivantes rendent une fiche de documentation pour quota");
  assert.equal(quota.resultats.length, 20, "quota avec claude-code remplit la limite de 20 sur les données vivantes");
});

test("recherche mixte : remplit la limite et ne plafonne les modèles que si des fiches documentaires restent", async () => {
  for (const [nbDocs, nbModeles] of [[30, 3], [1, 30], [2, 30], [30, 30], [5, 30], [25, 30]]) {
    const docs = Array.from({ length: nbDocs }, (_, i) => ({
      id: `doc-${i}`, nom: `documentation quota ${i}`, produit: "claude-code", categorie: "commandes",
      usage: "quota", description: "documentation quota", commentee: false,
    }));
    const modeles = { m: { nom_modele: "Claude Sonnet", produit: "claude-code", categorie: "modeles", executant: "claude", aliases_effort: [], description_commune: "quota", commentee: true } };
    const entrees = Array.from({ length: nbModeles }, (_, i) => ({
      modele: "m", effort: "medium", id: `model-${i}`, nom: `Modele quota ${i}`,
      categorie: "modeles", description: "quota", commentee: true,
    }));
    const donnees = base(docs);
    donnees["kb/modeles.json"] = { schema_version: 2, modeles, entrees };
    await avecDonnees(donnees, async (outil) => {
      const r = (await outil("chercher_reference", { requete: "quota", produit: "claude-code", limite: 20 })).result.structuredContent;
      assert.equal(r.total, nbDocs + nbModeles);
      assert.equal(r.resultats.length, Math.min(20, nbDocs + nbModeles));
      const nbModelesRetenus = r.resultats.filter((e) => e.categorie === "modeles").length;
      if ([1, 2, 5].includes(nbDocs)) assert.equal(nbModelesRetenus, 20 - nbDocs);
      if (nbDocs === 25) assert.equal(nbModelesRetenus, 10);
      if (nbDocs <= 5) assert.equal(r.resultats.filter((e) => e.categorie !== "modeles").length, nbDocs);
      if (nbDocs === 25) assert.equal(r.resultats.filter((e) => e.categorie !== "modeles").length, 10);
    });
  }

  const docs = [{ id: "doc-one", nom: "documentation", produit: "claude-code", categorie: "commandes", usage: "quota", description: "quota", commentee: false }];
  const modeles = { m: { nom_modele: "Claude Sonnet", produit: "claude-code", categorie: "modeles", executant: "claude", aliases_effort: [], description_commune: "quota", commentee: true } };
  const donnees = base(docs);
  donnees["kb/modeles.json"] = { schema_version: 2, modeles, entrees: [{ modele: "m", effort: "medium", id: "model-first", nom: "Claude Sonnet quota", categorie: "modeles", description: "quota", commentee: true }] };
  await avecDonnees(donnees, async (outil) => {
    const r = (await outil("chercher_reference", { requete: "quota", produit: "claude-code", limite: 1 })).result.structuredContent;
    assert.equal(r.resultats.length, 1);
    assert.equal(r.resultats[0].id, "model-first", "la limite 1 garde le modèle classé premier");
  });
});

// Mission lot 1 : contrats observables, données longues et erreurs de reprise.
test("a_tester : volume borné, limites, curseurs et détail non tronqué", async () => {
  const date = new Date().toISOString().slice(0, 10);
  const longs = Array.from({ length: 101 }, (_, i) => ({ id: `action-${i}`, titre: 'Titre '.repeat(300),
    produit: 'codex', impact: 'fort', action: { etapes: ['étape '.repeat(20000)] } }));
  const remplacements = { 'claude/index.json': { jours: [{ date }] }, [`claude/${date}.json`]: { elements: longs },
    'openai/index.json': { jours: [] }, 'actu/index.json': { jours: [] }, 'kb/a-tester.json': { entrees: [] } };
  await avecDonnees(remplacements, async outil => {
    const s = (await outil('a_tester')).result.structuredContent;
    assert.equal(s.total, 101); assert.equal(s.affichees, 5);
    assert.ok(JSON.stringify(s).length < 6000);
    const max = (await outil('a_tester', { limite: 20 })).result.structuredContent;
    assert.equal(max.affichees, 20); assert.ok(JSON.stringify(max).length < 18000);
    const detail = (await outil('a_tester', { id: s.actions[0].id })).result.structuredContent.detail;
    assert.deepEqual(detail.action, longs[0].action);
    assert.deepEqual((await outil('a_tester', { curseur: s.curseur_suivant })).result.structuredContent.actions.map(e => e.id),
      longs.slice(5, 10).map((_, i) => `action:claude:${date}:${i + 5}`));
    // Le curseur ne dépend ni de l'instance HTTP ni de la taille de page précédente.
    await avecDonnees(remplacements, async autre => {
      const suivante = (await autre('a_tester', { curseur: s.curseur_suivant, limite: 2 })).result.structuredContent;
      assert.equal(suivante.affichees, 2);
      assert.deepEqual(suivante.actions.map(e => e.id), longs.slice(5, 7).map((_, i) => `action:claude:${date}:${i + 5}`));
    });
    for (const args of [{ limite: 0 }, { limite: 21 }, { limite: 1.5 }, { limite: '5' }, { limite: null },
      { curseur: '' }, { curseur: 'v1:0000000000000000:5' }, { curseur: s.curseur_suivant.replace(/:\d+$/, ':99999') },
      { id: '../secret' }, { id: 'inexistant' }, { id: s.actions[0].id, curseur: s.curseur_suivant }]) {
      const r = (await outil('a_tester', args)).result;
      assert.equal(r.isError, true, JSON.stringify(args)); assert.match(r.content[0].text, /^Paramètre invalide/);
    }
    // Un autre contenu ne peut pas accepter le même curseur, même avec le même nombre d'actions.
    await avecDonnees({ ...remplacements, [`claude/${date}.json`]: { elements: [...longs].reverse() } }, async autre => {
      const r = (await autre('a_tester', { curseur: s.curseur_suivant })).result;
      assert.equal(r.isError, true); assert.match(r.content[0].text, /périmé.*sans curseur/);
    });
  });
  await avecDonnees({ ...remplacements, [`claude/${date}.json`]: { elements: [] } }, async outil => {
    const s = (await outil('a_tester')).result.structuredContent;
    assert.equal(s.total, 0); assert.equal(s.curseur_suivant, null);
  });
  await avecDonnees({ ...remplacements, 'openai/index.json': null }, async outil => {
    const r = (await outil('a_tester')).result;
    assert.equal(r.isError, true);
    assert.match(r.content[0].text, /openai\/index.json : HTTP 404/);
    assert.equal(r.structuredContent, undefined);
  });
});

test("validité : mêmes états dans chercher_reference et fiche_reference, date de commentaire distincte de maj_le", async () => {
  const entries = [
    { id: 'valide', contexte_sections: { profil: { sha1: 'actuel' } }, attendu: ['actuelle', false, []] },
    { id: 'modifiee', contexte_sections: { profil: { sha1: 'ancien' } }, attendu: ['perimee', true, ['profil']] },
    { id: 'disparue', contexte_sections: { absente: { sha1: 'ancien' } }, attendu: ['perimee', true, ['absente']] },
    { id: 'depreciee', contexte_sections: { retraite: { sha1: 'actuel' } }, attendu: ['perimee', true, ['retraite']] },
    { id: 'ancienne', contexte_sections: null, attendu: ['anterieure_d64', null, []] },
    { id: 'vide', contexte_sections: {}, attendu: ['actuelle', false, []] },
    { id: 'malformee', contexte_sections: { profil: null }, attendu: ['perimee', true, ['profil']] },
    { id: 'sans-empreinte', contexte_sections: { absente: {} }, attendu: ['perimee', true, ['absente']] },
    { id: 'invalide', contexte_sections: 'incorrect', attendu: ['inconnue', null, []] },
    { id: 'sans-commentaire', commentee: false, attendu: ['non_commentee', null, []] },
  ].map(e => ({ ...fiche3(e.id, e.id, 'validite'), commentee: true, maj_le: '2026-10-24',
    historique: [{ date: '2026-10-01', changement: 'commentée' }, { date: '2026-10-10', changement: 'commentaire révisé' },
      { date: '2026-10-24', changement: 'source modifiée' }], ...e }));
  const donnees = base(entries);
  donnees['kb/claude/commandes.json'] = { entrees: entries, contexte_sections: { profil: 'actuel', retraite: 'actuel' }, contexte_deprecies: ['retraite'] };
  await avecDonnees(donnees, async outil => {
    const resumes = (await outil('chercher_reference', { requete: 'validite', limite: 20 })).result.structuredContent.resultats;
    for (const e of entries) {
      const f = (await outil('fiche_reference', { id: e.id })).result.structuredContent.fiche;
      const r = resumes.find(x => x.id === e.id);
      for (const forme of [f, r]) {
        assert.deepEqual([forme.validite, forme.perimee, forme.sections_perimees], e.attendu, e.id);
        assert.equal(forme.verifie_le, '2026-10-10');
      }
    }
  });
  await avecDonnees(base([fiche3('inconnue', 'inconnue', 'validite')]), async outil => {
    const f = (await outil('fiche_reference', { id: 'inconnue' })).result.structuredContent.fiche;
    assert.equal(f.verifie_le, null); assert.equal(f.perimee, null);
  });
});

test("recherche : titre, proximité, mots vides et filtres combinés sans changer les appels existants", async () => {
  const fiches = [fiche3('loin', 'A quelconque', `alpha ${'bruit '.repeat(100)} beta`),
    fiche3('proche', 'B quelconque', 'alpha beta'), fiche3('titre', 'alpha beta', 'description'),
    { ...fiche3('autre', 'alpha beta', ''), produit: 'codex', statut_usage: 'utilise' }];
  await avecDonnees(base(fiches), async outil => {
    const chercher = async args => (await outil('chercher_reference', args)).result.structuredContent;
    assert.deepEqual((await chercher({ requete: 'alpha beta', produit: 'claude-code' })).resultats.map(e => e.id), ['titre', 'proche', 'loin']);
    assert.deepEqual((await chercher({ requete: 'comment alpha avec beta pour mon projet', produit: 'claude-code' })).resultats.slice(0, 3).map(e => e.id), ['titre', 'proche', 'loin']);
    assert.deepEqual((await chercher({ requete: 'alpha beta', produit: 'codex', categorie: 'commandes', statut: 'utilise' })).resultats.map(e => e.id), ['autre']);
    assert.equal((await chercher({ requete: 'alpha beta', produit: 'claude-code', statut: 'utilise' })).total, 0);
    assert.equal((await outil('chercher_reference', { requete: 'alpha', statut: 'faux' })).result.isError, true);
  });
});

test("recherche : corpus de 12 questions de mission, noms exacts stables et gain sur le cas contexte", async () => {
  const corpus = lireDonnee('../../mcp/test/requetes-reelles.json');
  let dansHuit = 0;
  for (const { attendus, ...args } of corpus) {
    const r = (await appel('chercher_reference', args)).corps.result.structuredContent;
    const rang = r.resultats.findIndex(e => attendus.includes(e.id)) + 1;
    if (rang) dansHuit++;
    if (/^[/]|^--/.test(args.requete)) assert.equal(rang, 1, args.requete);
    if (args.requete === 'réduire contexte mission') assert.ok(rang > 0 && rang <= 5, `commande de contexte dans les cinq premières fiches (${rang})`);
  }
  assert.ok(dansHuit >= 8, `${dansHuit}/12 cibles parmi les huit premiers résultats (avant : 4/12)`);
});

// Lot 2 : consultation courte sur l'ancienne route (sans version de catalogue : rien n'est gardé en cache), résumé tiré du
// texte de l'éditeur, jamais du commentaire personnel de l'ancienne route.
test("consultation courte sur l'ancienne route : sans cache, résumés courts, références et monde KNOW", async () => {
  const r = (await appel("chercher_reference", { requete: "/add-dir", forme: "consultation" })).corps.result;
  assert.equal(r.isError, false, r.content[0].text);
  const c = r.structuredContent;
  assert.deepEqual([c.forme, c.catalogue.version, c.cache.statut, c.cache.cle], ["consultation", null, "sans_version", null]);
  assert.match(c.avis, /pas de version de catalogue/);
  assert.ok(c.affichees >= 1 && c.affichees <= 3);
  const f = c.resultats[0];
  assert.equal(f.id, "claude-code-commandes-add-dir");
  assert.deepEqual(f.know_world, { fichier: "claude/commandes.json", id: "claude-code-commandes-add-dir" });
  const brut = JSON.parse(fs.readFileSync(path.join(DATA, "kb/claude/commandes.json"), "utf8")).entrees.find((e) => e.id === f.id);
  if (brut.commentee && brut.description) assert.equal(f.resume.startsWith(brut.description.slice(0, 40)), false, "pas le commentaire personnel");
  assert.equal("personnel" in f, false);
});

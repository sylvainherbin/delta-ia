// Tests du serveur MCP Delta sur les vraies données du dépôt (docs/data servi en local).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DATA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/data");
let donnees, serveurMcp, url, handler, OUTILS;

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
  assert.deepEqual(noms, ["a_tester", "chercher_reference", "etat_versions", "fiche_reference", "resume_du_jour"]);
  for (const t of liste.corps.result.tools) assert.equal(t.annotations.readOnlyHint, true);
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
const CLES_JOURNAL = ["methode", "outil", "client", "duree_ms", "statut", "demarrage_froid", "nb_resultats"];

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
  assert.deepEqual([notif.methode, notif.statut, notif.client], ["autre", "ok", null]);
  assert.deepEqual([liste.methode, liste.outil, liste.nb_resultats], ["tools/list", null, null]);
  assert.deepEqual([cherche0.outil, cherche0.nb_resultats, cherche0.statut], ["chercher_reference", 0, "ok"]);
  assert.ok(cherche.nb_resultats > 0 && cherche.client === null);
  assert.equal(aTester.outil, "a_tester"); assert.equal(typeof aTester.nb_resultats, "number");
  assert.deepEqual([fiche.outil, fiche.nb_resultats], ["fiche_reference", null]);
  assert.deepEqual([inconnu.methode, inconnu.outil, inconnu.statut], ["tools/call", "inconnu", -32602]);
  assert.deepEqual([ping.methode, autre.methode, autre.statut], ["ping", "autre", -32601]);
  for (const l of lignes) { assert.equal(typeof l.duree_ms, "number"); assert.equal(l.demarrage_froid, false); }
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
    assert.deepEqual(Object.keys(a), ["id", "date", "produit", "date_publication", "titre", "impact", "action", "source"]);
    assert.equal(typeof a.id, "string");
    assert.ok(a.source === null || (typeof a.source.url === "string" && typeof a.source.officielle === "boolean"));
  }
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
      "outil:fiche_reference": 1, "erreur:fiche_reference": 1, "outil:inconnu": 1, "erreur:inconnu": 1,
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
    assert.deepEqual(Object.fromEntries(hash.get(`mcp:j:${jourCourant()}`)), { "req:ping": 1, "req:autre": 1 });
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
    for (const c of champsEcrits) assert.match(c, /^(req|outil|zero|erreur|client):[A-Za-z0-9._ \/-]+$/);
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
    await attendre();
    appels.length = 0;
    const r = await lireStatsHttp(stats, "/stats?jours=3");
    assert.equal(r.statut, 200);
    assert.deepEqual(Object.keys(r.corps), ["statut", "genere_le", "jours", "total"]);
    assert.equal(r.corps.statut, "ok");
    assert.equal(r.corps.jours.length, 3);
    assert.equal(r.corps.jours.at(-1).jour, jourCourant());
    assert.deepEqual(Object.keys(r.corps.jours[0]), ["jour", "req", "outils", "zero", "erreurs", "clients"]);
    assert.deepEqual(r.corps.jours[0].req, {});
    const auj = r.corps.jours.at(-1);
    assert.deepEqual(auj.req, { initialize: 1, "tools/call": 2 });
    assert.deepEqual(auj.outils, { chercher_reference: 2 });
    assert.deepEqual(auj.zero, { chercher_reference: 1 });
    assert.deepEqual(auj.clients, { "claude-ai": 1 });
    assert.deepEqual(r.corps.total.outils, { chercher_reference: 2 });
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

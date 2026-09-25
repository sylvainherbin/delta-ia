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
  assert.deepEqual(v.outils.map((o) => o.outil), ["Claude Code", "Codex (app ChatGPT)", "Codex CLI (terminal, non utilisée)", "ChatGPT Desktop", "Claude Desktop"]);
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

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

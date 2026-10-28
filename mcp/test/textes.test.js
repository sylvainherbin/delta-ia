// Mutation isolée : les textes servis et l'aide doivent suivre le défaut réel, même s'il change.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const MCP = fileURLToPath(new URL("../", import.meta.url));
let copie, mcp, profil;
before(async () => {
  copie = fs.mkdtempSync(path.join(os.tmpdir(), "delta-p15d-"));
  for (const fichier of ["api", "lib", "bureau.js", "stdio.js", "package.json"])
    fs.cpSync(path.join(MCP, fichier), path.join(copie, fichier), { recursive: true });
  // Le même témoin s'applique à P15c, avant l'extraction de la constante de l'API.
  const fichier = path.join(copie, fs.existsSync(path.join(copie, "lib/consultation.js")) ? "lib/consultation.js" : "api/mcp.js");
  const source = fs.readFileSync(fichier, "utf8");
  const declaration = /export const LIMITE_CONSULTATION = \d+;/g;
  assert.equal([...source.matchAll(declaration)].length, 1, "une seule constante à modifier");
  const references = /export const MAX_REFERENCES_CONSULTATION = \d+;/g;
  assert.equal([...source.matchAll(references)].length, 1, "une seule borne de références à modifier");
  fs.writeFileSync(fichier, source.replace(declaration, "export const LIMITE_CONSULTATION = 4;")
    .replace(references, "export const MAX_REFERENCES_CONSULTATION = 2;"));
  mcp = await import(pathToFileURL(path.join(copie, "api/mcp.js")));
  assert.equal(mcp.LIMITE_CONSULTATION, 4);
  profil = path.join(copie, "profil.json");
  fs.writeFileSync(profil, JSON.stringify({ schema: "delta.instance", version: 1, identite: "p15d", home: copie }));
});
after(() => { if (copie) fs.rmSync(copie, { recursive: true, force: true }); });

for (const langue of ["fr", "en"]) {
  test(`P15d : descriptions servies avec la constante à 4 en ${langue}`, async () => {
    for (const source of ["ancienne_route", "commun", "local"]) for (const surface of [undefined, "compatible", "service", "reference"]) {
      const r = await mcp.traiter({ jsonrpc: "2.0", id: 1, method: "tools/list" }, {}, { langue, source, surface });
      const outil = r.result.tools.find(o => /(?:^|_)chercher_reference$/.test(o.name));
      assert.ok(outil, `${source} ${surface}`);
      assert.ok(outil.description.includes(langue === "fr"
        ? "consultation courte et ponctuelle : 4 résumés (5 au plus)"
        : "short one-off consultation: 4 summaries (5 at most)"), outil.description);
      assert.ok(outil.description.includes(langue === "fr"
        ? "2 références au plus"
        : "up to 2 references"), outil.description);
      assert.ok(outil.inputSchema.properties.limite.description.includes(langue === "fr"
        ? "consultation : 4 par défaut, 5 au plus"
        : "consultation: 4 by default, 5 at most"), outil.inputSchema.properties.limite.description);
      assert.equal(outil.inputSchema.properties.limite.default, 8, "la forme liste garde son propre défaut");
    }
  });

  test(`P15d : aide du Bureau avec la constante à 4 en ${langue}`, () => {
    const r = spawnSync(process.execPath, [path.join(copie, "bureau.js"), "--instance", profil, "--langue", langue,
      "consulter", "contexte", "--limite", "0"], { encoding: "utf8" });
    assert.equal(r.status, 2, r.stderr);
    assert.equal(r.stdout, "");
    assert.equal(r.stderr, langue === "fr"
      ? "delta-bureau: consulter : --limite doit être un entier de 1 à 5 (défaut 4)\n"
      : "delta-bureau: consulter: --limite must be an integer from 1 to 5 (default 4)\n");
  });
}

test("P15e : la consultation applique la borne de références mutée à 2, sans réseau", async (t) => {
  const sources = Array.from({ length: 4 }, (_, i) => ({ url: `https://example.invalid/reference-${i}`, officielle: true }));
  const entree = { id: "p15e-temoin", nom: "p15e-temoin", produit: "codex", categorie: "commandes", sources };
  t.mock.method(globalThis, "fetch", async (url) => {
    const chemin = new URL(url).pathname;
    if (chemin.endsWith("/kb/noms.json")) return new Response(JSON.stringify({ "p15e-temoin": [entree.id] }));
    assert.match(chemin, /\/kb\/[^/]+(?:\/[^/]+)?\.json$/);
    return new Response(JSON.stringify({ entrees: chemin.endsWith("/kb/openai/commandes.json") ? [entree] : [] }));
  });
  const r = await mcp.traiter({ jsonrpc: "2.0", id: 1, method: "tools/call",
    params: { name: "chercher_reference", arguments: { requete: entree.nom, forme: "consultation" } } }, {},
  { langue: "fr", source: "ancienne_route" });
  assert.equal(r.result.isError, false, JSON.stringify(r));
  assert.equal(r.result.structuredContent.resultats.length, 1);
  assert.deepEqual(r.result.structuredContent.resultats[0].references, sources.slice(0, 2).map(s => ({ ...s, libelle: null })));
});

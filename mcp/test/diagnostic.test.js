import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import handler, { traiter, traiterJournalise } from "../api/mcp.js";
import { champs } from "../lib/compteur.js";

const appel = (argumentsOutil, name = "chercher_reference") => ({
  jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: argumentsOutil },
});

for (const [incident, cause] of [["HTTP 503", "lecture.http"], ["JSON invalide", "lecture.json"]]) {
  test(`diagnostic : résumé avec index ${incident}, par HTTP et sans compteur distant`, async (t) => {
    const journal = [], compteur = new Map();
    t.mock.method(console, "log", s => journal.push(JSON.parse(s)));
    // Le gestionnaire réel appelle compter ; son stockage distant reste désactivé, même si le parent est configuré.
    for (const cle of ["DELTA_BASE_URL", "KV_REST_API_URL", "KV_REST_API_TOKEN"]) {
      const avant = process.env[cle];
      t.after(() => { if (avant === undefined) delete process.env[cle]; else process.env[cle] = avant; });
    }
    process.env.KV_REST_API_URL = "";
    process.env.KV_REST_API_TOKEN = "";
    const requetes = [];
    const donnees = http.createServer((req, res) => {
      requetes.push(req.url);
      res.setHeader("Content-Type", "application/json");
      if (req.url.endsWith("/openai/index.json")) {
        res.statusCode = incident === "HTTP 503" ? 503 : 200;
        return res.end("{json-invalide");
      }
      res.end(JSON.stringify({ jours: [] }));
    });
    const mcp = http.createServer(handler);
    for (const serveur of [donnees, mcp]) {
      await new Promise(r => serveur.listen(0, "127.0.0.1", r));
      t.after(() => new Promise(r => serveur.close(r)));
    }
    const base = `http://127.0.0.1:${donnees.address().port}`;
    const url = `http://127.0.0.1:${mcp.address().port}`;
    const fetchReel = globalThis.fetch, horsBac = [];
    t.mock.method(globalThis, "fetch", (adresse, options) => {
      if (![base, url].includes(new URL(adresse).origin)) {
        horsBac.push(String(adresse));
        throw new Error("accès hors du bac local interdit");
      }
      return fetchReel(adresse, options);
    });
    for (const langue of ["fr", "en"]) {
      // Une adresse distincte isole aussi le cache du lecteur entre les langues et les incidents.
      process.env.DELTA_BASE_URL = `${base}/${langue}`;
      const r = await fetch(`${url}/?source=ancienne_route&langue=${langue}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(appel({}, "resume_du_jour")),
      });
      assert.equal(r.status, 200);
      const texte = langue === "fr" ? "Données ORQYRA AI indisponibles" : "ORQYRA AI data unavailable";
      const raison = incident === "HTTP 503" ? "HTTP 503" : langue === "fr" ? "JSON illisible" : "unreadable JSON";
      const separateur = langue === "fr" ? " : " : ": ";
      assert.deepEqual(await r.json(), { jsonrpc: "2.0", id: 1, result: {
        content: [{ type: "text", text: `${texte}${separateur}openai/index.json${separateur}${raison}` }],
        isError: true,
      } });
      assert.equal(journal.length, langue === "fr" ? 1 : 2);
      const ligne = journal.at(-1);
      assert.equal(ligne.statut, "erreur_outil");
      for (const champ of champs(ligne)) compteur.set(champ, (compteur.get(champ) ?? 0) + 1);
    }
    assert.deepEqual(requetes.sort(), ["en", "fr"].flatMap(l => ["actu", "claude", "openai"].map(p => `/${l}/${p}/index.json`)).sort());
    assert.deepEqual(horsBac, []);
    assert.deepEqual(journal.map(l => l.cause_erreur), [cause, cause]);
    assert.deepEqual(Object.fromEntries(compteur), {
      "req:tools/call": 2, "outil:resume_du_jour": 2, "erreur:resume_du_jour": 2,
      [`cause:resume_du_jour/${cause}`]: 2,
    });
  });
}

test("diagnostic : les paramètres invalides ont un code sans leurs valeurs", async (t) => {
  const secret = "contenu-prive-qui-ne-doit-pas-etre-journalise";
  const journal = [];
  t.mock.method(console, "log", s => journal.push(JSON.parse(s)));
  for (const [args, cause] of [
    [{ requete: "" }, "param.requete"],
    [{ requete: secret, produit: secret }, "param.produit"],
    [{ requete: secret, categorie: secret }, "param.categorie"],
    [{ requete: secret, forme: secret }, "param.forme"],
    [{ requete: secret, statut: "utilise" }, "param.statut_commun"],
  ]) {
    const lignes = [];
    const r = await traiterJournalise(appel(args), lignes, { langue: "fr", source: "commun" });
    assert.equal(r.result.isError, true);
    assert.equal(lignes[0].cause_erreur, cause);
    assert.ok(champs(lignes[0]).includes(`cause:chercher_reference/${cause}`));
  }
  assert.ok(!JSON.stringify(journal).includes(secret));
});

test("diagnostic : erreur de lecture contrôlée, erreur interne et succès restent distincts", async (t) => {
  const journal = [];
  t.mock.method(console, "log", s => journal.push(JSON.parse(s)));
  const { ErreurTexte } = await import("../lib/textes.js");
  const { ErreurModeles } = await import("../lib/modeles.js");
  for (const [erreur, attendu] of [
    [new ErreurTexte("couche.empreinte", { chemin: "prive" }), "couche.empreinte"],
    [new ErreurTexte("lecture.message", { chemin: "prive", raison: new ErreurTexte("lecture.http", { statut: 503 }) }), "lecture.http"],
    [new ErreurModeles("modeles.absent", { modele: "prive" }), "modeles.absent"],
    [new Error("prive"), "interne"],
  ]) {
    const ctx = { langue: "fr", source: "local", local: { blocDonnees() { throw erreur; } } };
    await traiterJournalise(appel({ requete: "valide" }), [], ctx);
    assert.equal(journal.at(-1).cause_erreur, attendu);
  }
  await traiterJournalise({ jsonrpc: "2.0", id: 2, method: "ping" }, []);
  assert.equal(journal.at(-1).cause_erreur, null);
  assert.ok(!JSON.stringify(journal).includes("prive"));
  assert.ok(!champs({ methode: "tools/call", outil: "chercher_reference", statut: "erreur_outil", cause_erreur: "prive" })
    .some(c => c.startsWith("cause:")));
});

test("tools/call : les noms hérités du prototype sont des outils inconnus", async () => {
  for (const nom of ["__proto__", "constructor", "toString", { toString: 1 }, null, ["chercher_reference"]]) {
    const r = await traiter(appel({}, nom));
    assert.equal(r.error?.code, -32602, JSON.stringify(nom));
  }
});

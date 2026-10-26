import { test } from "node:test";
import assert from "node:assert/strict";
import { traiter, traiterJournalise } from "../api/mcp.js";
import { champs } from "../lib/compteur.js";

const appel = (argumentsOutil, name = "chercher_reference") => ({
  jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: argumentsOutil },
});

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
  for (const [erreur, attendu] of [
    [new ErreurTexte("couche.empreinte", { chemin: "prive" }), "couche.empreinte"],
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
  for (const nom of ["__proto__", "constructor", "toString"]) {
    const r = await traiter(appel({}, nom));
    assert.equal(r.error?.code, -32602, nom);
  }
});

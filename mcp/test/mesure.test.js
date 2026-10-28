import { test } from "node:test";
import assert from "node:assert/strict";
import { mesurerCorpus } from "../mesurer.js";
import { evaluerReponse, mesurerReductions } from "../mesurer-surface.js";

test("mesure : un résultat non vide ne suffit pas, les erreurs comptent comme des échecs", async () => {
  const corpus = ["trouve", "hors-cible", "erreur"].map(requete => ({ requete, attendus: ["cible"] }));
  const mesure = await mesurerCorpus(corpus, async args => {
    if (args.requete === "erreur") return { result: { isError: true } };
    const ids = args.requete === "trouve" ? ["bruit", "cible"] : ["bruit"];
    return { result: { isError: false, structuredContent: { total: ids.length, resultats: ids.map(id => ({ id })) } } };
  });
  assert.equal(mesure.mesures.liste.cibles_top8, 1);
  assert.equal(mesure.mesures.liste.cibles_top1, 0);
  assert.equal(mesure.mesures.liste.erreurs, 1);
  assert.equal(mesure.mesures.liste.taux_top8_pct, 100 / 3);
  assert.equal(mesure.questions[0].formes.liste.rang, 2);
  assert.equal(mesure.questions[1].formes.liste.rang, null);
  assert.equal(mesure.questions[2].formes.liste.rang, null);
  assert.equal(mesure.jetons, null);
});

const questionP15 = requete => ({ requete, attendus: ["cible"], faits: [{ id: "cible", syntaxe: "/commande", source: "https://exemple.invalid/doc" }] });
const reponseP15 = (id = "cible") => ({ result: { isError: false, structuredContent: { resultats: [{
  id, usage: "/commande", source: "https://exemple.invalid/doc", validite: "inconnue", perimee: null, verifie_le: null }] } } });

test("P15 R178 : cible sans syntaxe ou source, erreur et lecture incomplète ne sont pas utiles", () => {
  assert.equal(evaluerReponse(reponseP15(), questionP15("q")).utile, true);
  for (const modification of [r => delete r.result.structuredContent.resultats[0].usage,
    r => delete r.result.structuredContent.resultats[0].source,
    r => delete r.result.structuredContent.resultats[0].validite,
    r => { r.result.isError = true; },
    r => { r.result.structuredContent.categories_non_lues = ["commandes"]; }]) {
    const r = reponseP15(); modification(r);
    assert.equal(evaluerReponse(r, questionP15("q")).utile, false);
  }
});

test("P15 R178 : un gain sur une autre question ne masque pas une perte à taux égal", async () => {
  const mesure = await mesurerReductions([questionP15("A"), questionP15("B")], async args =>
    reponseP15((args.forme === "liste" ? args.requete === "A" : args.requete === "B") ? "cible" : "bruit"));
  const m = mesure.mesures;
  assert.equal(m.liste8.utiles, m.consultation3.utiles);
  assert.deepEqual(m.consultation3.pertes, ["A"]);
  assert.deepEqual(m.consultation3.gains, ["B"]);
  assert.equal(m.consultation3.conserve_signal_liste8, false);
  assert.equal(mesure.minimum_octets_sans_perte, "liste8");
  assert.equal(m.consultation3.jetons, null);
});

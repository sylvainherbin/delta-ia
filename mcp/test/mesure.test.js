import { test } from "node:test";
import assert from "node:assert/strict";
import { mesurerCorpus } from "../mesurer.js";

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

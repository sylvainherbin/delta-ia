#!/usr/bin/env bash
# À lancer au premier plan sous verrou-tests-dev ; aucune requête au service public.
# Usage : bash mcp/preuve-p15d.sh /chemin/absolu/vers/.tmp-preuves-neuves
set -euo pipefail
cd "$(dirname "$0")/.."
racine="$PWD"
noeud="$HOME/.nvm/current/bin/node"
base=5a66288617f25d6f08b6d7af64424196fa19dcd4
copie="${1:?dossier de preuve neuf requis}"
[[ "$copie" = /* && ! -e "$copie" ]] || { echo "Copie absolue neuve requise" >&2; exit 2; }
mkdir -p "$copie"/{avant,description}
instantane_avant="$(sha256sum mcp/mesures/2026-10-28-surface.json)"
git archive "$base" mcp | tar -x -C "$copie/avant"
# Les quatre témoins P15d restent compatibles avec cette base ; les mutations
# P15e du fichier courant exigent une constante absente de P15c.
git show 8a513c88a6895050b496379826b36d4705a3fac3:mcp/test/textes.test.js \
  > "$copie/avant/mcp/test/textes.test.js"
sha256sum mcp/api/mcp.js mcp/lib/{consultation,textes}.js mcp/test/{mcp,textes}.test.js \
  mcp/preuve-p15{c,d}.sh "$copie/avant/mcp/test/textes.test.js" > "$copie/code.sha256"

verdict() {
  "$noeud" --input-type=module - "$@" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const [fichier, attendus, echecs, ...noms] = process.argv.slice(2);
const log = fs.readFileSync(fichier, "utf8");
assert.doesNotMatch(log, /^Bail out!/m, "preuve refusée : abandon TAP");
// « suite » : le total est lu du rapport (la suite grandit à chaque preuve ajoutée), jamais figé ici.
const lu = log.match(/^# tests (\d+)$/m);
const tests = attendus === "suite" ? (lu && Number(lu[1]) > 0 ? lu[1] : assert.fail("aucun total de tests lisible")) : attendus;
assert.match(log, new RegExp(`^# tests ${tests}$`, "m"));
assert.match(log, new RegExp(`^# fail ${echecs}$`, "m"));
assert.match(log, new RegExp(`^# pass ${Number(tests) - Number(echecs)}$`, "m"));
for (const total of ["cancelled", "skipped", "todo"]) assert.match(log, new RegExp(`^# ${total} 0$`, "m"));
if (Number(echecs)) {
  // Les quatre témoins historiques sont aussi le contrat des appels sans noms.
  if (!noms.length) for (const langue of ["fr", "en"]) noms.push(
    `P15d : descriptions servies avec la constante à 4 en ${langue}`,
    `P15d : aide du Bureau avec la constante à 4 en ${langue}`);
  assert.equal(noms.length, Number(tests), "noms exacts des témoins rouges requis");
  assert.equal(new Set(noms).size, noms.length, "noms des témoins rouges uniques requis");
  const resultats = [...log.matchAll(/^(ok|not ok) \d+ - (.+)$/gm)];
  assert.equal(resultats.length, Number(tests), "nombre de résultats rouges incohérent");
  for (const nom of noms) {
    const trouves = resultats.filter(r => r[2] === nom);
    assert.equal(trouves.length, 1, nom);
    const resultat = trouves[0], suivant = resultats[resultats.indexOf(resultat) + 1];
    assert.equal(resultat[1], "not ok", nom);
    const diagnostic = log.slice(resultat.index, suivant?.index ?? log.length);
    // Lire le diagnostic du témoin ; les commentaires peuvent décrire une erreur capturée.
    assert.match(diagnostic, /^  failureType: 'testCodeFailure'$/m,
      `${nom} : rouge refusé, échec de préparation ou de chargement`);
    assert.match(diagnostic, /^  code: 'ERR_ASSERTION'$/m,
      `${nom} : rouge refusé, aucune assertion en échec`);
  }
}
console.log(`${fichier}: ${tests} tests, ${echecs} échecs`);
JS
}

code=0
"$noeud" --test --test-reporter=tap "$copie/avant/mcp/test/textes.test.js" > "$copie/rouge-5a66288.log" 2>&1 || code=$?
[[ "$code" = 1 ]] || { cat "$copie/rouge-5a66288.log"; exit 1; }
verdict "$copie/rouge-5a66288.log" 4 4

"$noeud" --test --test-reporter=tap mcp/test/*.test.js > "$copie/verts.log" 2>&1 || { cat "$copie/verts.log"; exit 1; }
verdict "$copie/verts.log" suite 0

# Tous les dictionnaires et les réponses de découverte réelles, avec le défaut à 3 : comparaison octet par octet.
cat > "$copie/surface.mjs" <<'JS'
import { pathToFileURL } from "node:url";
globalThis.fetch = () => { throw new Error("P15d : aucun réseau autorisé pour la découverte"); };
const racine = process.argv[2];
const { traiter } = await import(pathToFileURL(`${racine}/mcp/api/mcp.js`));
const { TEXTES, ErreurTexte } = await import(pathToFileURL(`${racine}/mcp/lib/textes.js`));
const reponses = [];
for (const langue of ["en", "fr"]) {
  for (const source of ["ancienne_route", "commun", "local"]) for (const surface of [undefined, "compatible", "service", "reference"])
    for (const method of ["initialize", "tools/list"])
      reponses.push(await traiter({ jsonrpc: "2.0", id: 1, method }, {}, { langue, source, surface }));
  reponses.push(new ErreurTexte("local.limite_consultation").texte(langue));
}
// Inclure aussi la requête sans contexte explicite (surface publique par défaut).
reponses.push(await traiter({ jsonrpc: "2.0", id: 1, method: "tools/list" }));
process.stdout.write(JSON.stringify({ TEXTES, reponses }) + "\n");
JS
"$noeud" "$copie/surface.mjs" "$copie/avant" > "$copie/surface-avant.json"
"$noeud" "$copie/surface.mjs" "$racine" > "$copie/surface-apres.json"
cmp "$copie/surface-avant.json" "$copie/surface-apres.json"
sha256sum "$copie/"surface-{avant,apres}.json

# La garde couvre aussi une dérive de description de niveau outil, sans changement de nom ni de paramètre.
cp -R mcp "$copie/description/mcp"
ln -s "$racine/docs" "$copie/description/docs"
"$noeud" --input-type=module - "$copie/description/mcp/api/mcp.js" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const fichier = process.argv[2], texte = fs.readFileSync(fichier, "utf8");
const avant = 'const description = texteSurface(ctx, `outil.${nom}.description`, { origine })';
assert.equal(texte.split(avant).length, 2);
fs.writeFileSync(fichier, texte.replace(avant, avant + ' + (surface !== "compatible" ? " P15d dérive." : "")'));
JS
code=0
"$noeud" --test --test-reporter=tap --test-name-pattern='^P15c R172' \
  "$copie/description/mcp/test/mcp.test.js" > "$copie/mutation-description.log" 2>&1 || code=$?
[[ "$code" = 1 ]] || { cat "$copie/mutation-description.log"; exit 1; }
verdict "$copie/mutation-description.log" 2 2 \
  'P15c R172 : descriptions complètes des outils et paramètres en fr' 'P15c R172 : descriptions complètes des outils et paramètres en en'
[[ "$instantane_avant" = "$(sha256sum mcp/mesures/2026-10-28-surface.json)" ]]
printf '%s\n' "$instantane_avant" "P15d : rouge, vert, identité des textes et mutation de description vérifiés."

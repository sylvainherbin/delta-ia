#!/usr/bin/env bash
# Premier plan sous verrou-tests-dev. Toute écriture de preuve reste dans une copie neuve.
# Usage : bash mcp/preuve-p15c.sh /chemin/absolu/vers/copie-neuve
set -euo pipefail
cd "$(dirname "$0")/.."
noeud="$HOME/.nvm/current/bin/node"
base=389bf95a068cd43e369d14b3a47a7e136e85eb30
copie="${1:?dossier de copie neuf requis}"
[[ "$copie" = /* && ! -e "$copie" ]] || { echo "Copie absolue neuve requise" >&2; exit 2; }
mkdir -p "$copie"/{tete,avant}
instantane_avant="$(sha256sum mcp/mesures/2026-10-28-surface.json)"
git rev-parse HEAD > "$copie/tete.txt"
git archive HEAD mcp docs/data docs/commun docs/assets scripts/deltalib/couches/bootstrap.json | tar -x -C "$copie/tete"
git archive "$base" mcp docs/data docs/commun | tar -x -C "$copie/avant"
cp "$copie/tete/mcp/test/"{mcp,local}.test.js "$copie/avant/mcp/test/"

verdict() {
  "$noeud" --input-type=module - "$1" "$2" "$3" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const [fichier, tests, echecs] = process.argv.slice(2);
const log = fs.readFileSync(fichier, "utf8");
assert.match(log, new RegExp(`^# tests ${tests}$`, "m"));
assert.match(log, new RegExp(`^# fail ${echecs}$`, "m"));
console.log(`${fichier}: ${tests} tests, ${echecs} échecs`);
JS
}

# Deux défauts reproduits sur P15b avec les seules assertions nouvelles.
code=0
"$noeud" --test --test-reporter=tap --test-name-pattern='^P15c R(176|178)' \
  "$copie/avant/mcp/test/mcp.test.js" "$copie/avant/mcp/test/local.test.js" > "$copie/rouge-389bf95.log" 2>&1 || code=$?
[[ "$code" = 1 ]] || { cat "$copie/rouge-389bf95.log"; exit 1; }
verdict "$copie/rouge-389bf95.log" 2 2

for variante in parametres constante; do
  mkdir "$copie/$variante"
  cp -R "$copie/tete/mcp" "$copie/$variante/mcp"
  ln -s "$copie/tete/docs" "$copie/$variante/docs"
done
"$noeud" --input-type=module - "$copie" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const copie = process.argv[2];
function remplacer(fichier, avant, apres) {
  const texte = fs.readFileSync(fichier, "utf8");
  assert.equal(texte.split(avant).length, 2, avant);
  fs.writeFileSync(fichier, texte.replace(avant, apres));
}
// Dérive sans aucun nom d'outil : les comparaisons de noms seules la laisseraient passer.
const description = 'description: texteSurface(ctx, `outil.${nom}.${p}`)';
remplacer(`${copie}/parametres/mcp/api/mcp.js`, description,
  description + ' + (p === "requete" && surface !== "compatible" ? " P15c dérive." : "")');
remplacer(`${copie}/constante/mcp/lib/consultation.js`, 'export const LIMITE_CONSULTATION = 3;', 'export const LIMITE_CONSULTATION = 4;');
JS
code=0
"$noeud" --test --test-reporter=tap --test-name-pattern='^P15c R172' \
  "$copie/parametres/mcp/test/mcp.test.js" > "$copie/mutation-parametres.log" 2>&1 || code=$?
[[ "$code" = 1 ]] || { cat "$copie/mutation-parametres.log"; exit 1; }
verdict "$copie/mutation-parametres.log" 2 2

# Changer la constante seule doit modifier le défaut réel (API, Bureau et CLI) et rester vert.
"$noeud" --test --test-reporter=tap --test-name-pattern='^P15c R178' \
  "$copie/constante/mcp/test/local.test.js" > "$copie/constante-4.log" 2>&1
verdict "$copie/constante-4.log" 1 0
"$noeud" --input-type=module - "$copie/constante/mcp/bureau.js" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const fichier = process.argv[2], texte = fs.readFileSync(fichier, "utf8");
assert.equal(texte.split('limite = LIMITE_CONSULTATION').length, 2);
fs.writeFileSync(fichier, texte.replace('limite = LIMITE_CONSULTATION', 'limite = 3'));
JS
code=0
"$noeud" --test --test-reporter=tap --test-name-pattern='^P15c R178' \
  "$copie/constante/mcp/test/local.test.js" > "$copie/mutation-bureau-3.log" 2>&1 || code=$?
[[ "$code" = 1 ]] || { cat "$copie/mutation-bureau-3.log"; exit 1; }
verdict "$copie/mutation-bureau-3.log" 1 1

"$noeud" --test --test-reporter=tap "$copie/tete/mcp/test/"*.test.js > "$copie/verts.log" 2>&1
verdict "$copie/verts.log" 107 0
"$noeud" "$copie/tete/mcp/mesurer-surface.js" > "$copie/surface.json"
"$noeud" --input-type=module - "$copie" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
const copie = process.argv[2], mesure = JSON.parse(fs.readFileSync(`${copie}/surface.json`, "utf8"));
for (const [fichier, empreinte] of Object.entries(mesure.code_sha256))
  assert.equal(createHash("sha256").update(fs.readFileSync(`${copie}/tete/${fichier}`)).digest("hex"), empreinte, fichier);
console.log("P15c : instantané descriptif recalculé dans la copie, empreintes du code vérifiées ; aucun seuil de signal imposé");
JS
[[ "$instantane_avant" = "$(sha256sum mcp/mesures/2026-10-28-surface.json)" ]] || { echo "Instantané suivi modifié pendant la preuve" >&2; exit 1; }

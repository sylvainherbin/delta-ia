#!/usr/bin/env bash
# À lancer au premier plan par verrou-tests-dev. Aucun service public ni appel de modèle.
set -euo pipefail
cd "$(dirname "$0")/.."
noeud="$HOME/.nvm/current/bin/node"
base=5675a43e02d53d2a507c4a12c5c842f0d1c4ef52
copie="$(mktemp -d)"
trap 'rm -rf -- "$copie"' EXIT
mkdir -p "$copie/avant" "$copie/mutation" rapports/grilles-v2-p15b
git archive "$base" mcp docs/data docs/commun | tar -x -C "$copie/avant"
cp mcp/test/{mcp,local}.test.js "$copie/avant/mcp/test/"
code=0
"$noeud" --test --test-reporter=tap --test-name-pattern='^P15b ' \
  "$copie/avant/mcp/test/mcp.test.js" "$copie/avant/mcp/test/local.test.js" > "$copie/rouge.log" 2>&1 || code=$?
cp "$copie/rouge.log" rapports/grilles-v2-p15b/rouge-5675a43.log
if [ "$code" -ne 1 ]; then cat "$copie/rouge.log"; echo "P15b : témoin rouge inattendu ($code)" >&2; exit 1; fi
"$noeud" --input-type=module - "$copie/rouge.log" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const log = fs.readFileSync(process.argv[2], "utf8");
assert.match(log, /^# tests 4$/m);
assert.match(log, /^# fail 4$/m);
for (const nom of ["descriptions et paramètres préfixés en fr", "descriptions et paramètres préfixés en en",
  "erreurs et suite citent les noms de la surface", "Bureau consulter, défaut 3"])
  assert.ok(log.includes(nom), nom);
console.log("P15b : quatre témoins rouges sur 5675a43e (descriptions fr/en, messages, limite Bureau)");
JS
# Reproduire précisément la réserve de relecture : retirer l'adaptation des seules descriptions d'outils.
cp -R mcp "$copie/mutation/mcp"
ln -s "$PWD/docs" "$copie/mutation/docs"
"$noeud" --input-type=module - "$copie/mutation/mcp/api/mcp.js" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const fichier = process.argv[2], texte = fs.readFileSync(fichier, "utf8");
const avant = 'const description = texteSurface(ctx, `outil.${nom}.description`, { origine })';
assert.equal(texte.split(avant).length, 2);
fs.writeFileSync(fichier, texte.replace(avant, 'const description = t(langue, `outil.${nom}.description`, { origine })'));
JS
code=0
"$noeud" --test --test-reporter=tap --test-name-pattern='^P15b R172 : descriptions' \
  "$copie/mutation/mcp/test/mcp.test.js" > "$copie/mutation.log" 2>&1 || code=$?
cp "$copie/mutation.log" rapports/grilles-v2-p15b/mutation-descriptions.log
if [ "$code" -ne 1 ]; then cat "$copie/mutation.log"; echo "P15b : mutation non détectée ($code)" >&2; exit 1; fi
"$noeud" --input-type=module - "$copie/mutation.log" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const log = fs.readFileSync(process.argv[2], "utf8");
assert.match(log, /^# tests 2$/m);
assert.match(log, /^# fail 2$/m);
console.log("P15b : mutation des descriptions détectée en français et en anglais (2/2 rouges)");
JS
avant="$(sha256sum mcp/mesures/2026-10-28-surface.json)"
bash mcp/preuve-p15.sh
apres="$(sha256sum mcp/mesures/2026-10-28-surface.json)"
if [ "$avant" != "$apres" ]; then echo "P15b : l'instantané suivi a changé" >&2; exit 1; fi
printf '%s\n' "P15b : instantané suivi inchangé : $apres"

#!/usr/bin/env bash
# À lancer par verrou-tests-dev (voir mesures/2026-10-28-p15.md). Aucun checkout, service public ou appel modèle.
set -euo pipefail
cd "$(dirname "$0")/.."
noeud="$HOME/.nvm/current/bin/node"
base=78030f81e0aa4d731d78a53b36ae5660ea6c3735
copie="$(mktemp -d)"
trap 'rm -rf -- "$copie"' EXIT
mkdir -p rapports/grilles-v2-p15
git archive "$base" mcp docs/data | tar -x -C "$copie"
# Seules les assertions nouvelles sont portées sur la base ; aucun fichier d'implémentation ne l'est.
cp mcp/test/mcp.test.js "$copie/mcp/test/mcp.test.js"
code=0
"$noeud" --test --test-reporter=tap --test-name-pattern='^P15 ' "$copie/mcp/test/mcp.test.js" > "$copie/rouge.log" 2>&1 || code=$?
cp "$copie/rouge.log" rapports/grilles-v2-p15/rouge-main.log
if [ "$code" -ne 1 ]; then cat "$copie/rouge.log"; echo "P15 : témoin rouge inattendu (code $code)" >&2; exit 1; fi
"$noeud" --input-type=module - "$copie/rouge.log" <<'JS'
import fs from "node:fs";
import assert from "node:assert/strict";
const log = fs.readFileSync(process.argv[2], "utf8");
assert.match(log, /^# tests 4$/m);
assert.match(log, /^# fail 4$/m);
assert.match(log, /six noms de service/);
assert.match(log, /trois outils de référence/);
assert.match(log, /les alias alimentent les compteurs/);
assert.match(log, /la consultation conserve les premières cibles/);
console.log("P15 : les quatre tests de pratique échouent sur main 78030f81 (journal : rapports/grilles-v2-p15/rouge-main.log)");
JS
"$noeud" --test mcp/test/mcp.test.js mcp/test/mesure.test.js mcp/test/diagnostic.test.js mcp/test/couches.test.js mcp/test/local.test.js
"$noeud" mcp/mesurer-surface.js > "$copie/surface.json"
mv -- "$copie/surface.json" rapports/grilles-v2-p15/surface.json
echo "P15 : mesure descriptive, sans seuil de régression (rapports/grilles-v2-p15/surface.json)"

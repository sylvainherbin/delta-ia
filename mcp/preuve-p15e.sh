#!/usr/bin/env bash
# À lancer au premier plan sous verrou-tests-dev ; aucun accès réseau.
# Usage : bash mcp/preuve-p15e.sh /chemin/absolu/vers/une-copie-neuve
set -euo pipefail
cd "$(dirname "$0")/.."
racine="$PWD"
commun="$(git rev-parse --path-format=absolute --git-common-dir)"
python="${commun%/.git}/.venv/bin/python"
noeud="$HOME/.nvm/current/bin/node"
copie="${1:?dossier de preuve neuf requis}"
[[ "$copie" = /* && ! -e "$copie" ]] || { echo "Copie absolue neuve requise" >&2; exit 2; }
[[ -x "$python" && -x "$noeud" ]] || { echo "Python du venv ou Node nvm absent" >&2; exit 2; }
mkdir -p "$copie/avant"
git archive 8a513c88a6895050b496379826b36d4705a3fac3 \
  tests/test_vouvoiement_visible.py mcp/lib mcp/package.json | tar -x -C "$copie/avant"
export PYTHONPATH="$racine/tests:$racine/scripts${PYTHONPATH:+:$PYTHONPATH}"
"$python" - "$racine" "$copie" <<'PY'
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

racine, copie = map(Path, sys.argv[1:])
avant = copie / "avant"
cle = "local.limite_consultation"
fichier = avant / "mcp/lib/textes.js"
source = fichier.read_text(encoding="utf-8")
en, fr = source.split("  fr: {", 1)
fr, nombre = re.subn(r'(^\s*"local\.limite_consultation":\s*`.*)(`,\s*$)',
                     r"\1 Tu peux continuer.\2", fr, flags=re.MULTILINE)
assert nombre == 1
fichier.write_text(en + "  fr: {" + fr, encoding="utf-8")
apres = copie / "apres"
shutil.copytree(avant, apres)
shutil.copy2(racine / "tests/test_vouvoiement_visible.py", apres / "tests/test_vouvoiement_visible.py")

for nom, dossier, attendu in (("ancien", avant, 121), ("corrige", apres, 124)):
    garde = runpy.run_path(str(dossier / "tests/test_vouvoiement_visible.py"))
    dico = garde["dictionnaire_fr_du_connecteur"]()
    assert len(dico) == attendu, (nom, len(dico))
    print(f"{nom} : {len(dico)} clés lues ; clé gabarit couverte : {cle in dico}", flush=True)

def passage(nom, commande, code, fragment):
    r = subprocess.run(commande, cwd=racine, capture_output=True, text=True, timeout=120)
    log = r.stdout + r.stderr
    (copie / f"{nom}.log").write_text(log, encoding="utf-8")
    assert r.returncode == code and fragment in log, (nom, r.returncode, log)
    print(f"{nom} : code {r.returncode} attendu ; {fragment}", flush=True)

test = "tests/test_vouvoiement_visible.py::test_connecteur_mcp_fr_vouvoie"
print(f"Python : {sys.executable}", flush=True)
passage("ancienne-garde-mutant", [sys.executable, "-m", "pytest", "-q", str(avant / test)], 0, "1 passed")
passage("garde-corrigee-mutant", [sys.executable, "-m", "pytest", "-q", str(apres / test)], 1, cle)
passage("verts-python", [sys.executable, "-m", "pytest", "-q", "tests/test_vouvoiement_visible.py"], 0, "9 passed")
PY
cat > "$copie/sans-reseau.mjs" <<'JS'
globalThis.fetch = () => { throw new Error("P15e : réseau interdit ; utilisez une doublure explicite"); };
JS
"$noeud" --import "$copie/sans-reseau.mjs" --test --test-reporter=tap mcp/test/textes.test.js \
  > "$copie/verts-node.log" 2>&1 || { cat "$copie/verts-node.log"; exit 1; }
cat "$copie/verts-node.log"
sha256sum tests/test_vouvoiement_visible.py mcp/lib/{consultation,textes}.js mcp/api/mcp.js \
  mcp/test/textes.test.js mcp/preuve-p15e.sh > "$copie/code.sha256"
printf '%s\n' "P15e : ancienne garde aveugle, garde corrigée rouge sur le même mutant, tests verts."

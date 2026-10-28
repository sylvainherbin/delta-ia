"""Mission 00u : contrôle réel du verdict TAP ajouté par c275785.

Node produit les journaux à partir de fixtures, puis Bash exécute sans
modification la fonction verdict de mcp/preuve-p15c.sh. Aucun serveur,
appel de modèle, copie d'implémentation ou journal TAP fabriqué.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


RACINE = Path(__file__).resolve().parents[1]
RECETTE = RACINE / "mcp/preuve-p15c.sh"


class DiagnosticAttenduRejete(AssertionError):
    """00u-F1 : un import refusé, capturé et vérifié invalide un TAP vert."""


@pytest.fixture
def contexte(tmp_path):
    source = RECETTE.read_text(encoding="utf-8")
    fonction = re.search(r"^verdict\(\) \{\n[\s\S]*?^JS\n\}", source, re.MULTILINE)
    assert fonction, "fonction réelle à auditer"
    noms = [re.search(rf"^{cle}='([^']+)'$", source, re.MULTILINE).group(1)
            for cle in ("r176", "r178")]
    node = shutil.which("node")
    assert node, "Node requis pour produire un vrai TAP"
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    env = dict(os.environ, HOME=str(home), TMPDIR=str(tmp_path),
               XDG_CONFIG_HOME=str(home / ".config"),
               XDG_CACHE_HOME=str(home / ".cache"),
               XDG_DATA_HOME=str(home / ".local/share"),
               XDG_STATE_HOME=str(home / ".local/state"))
    env.pop("NODE_TEST_CONTEXT", None)
    return tmp_path, fonction.group(0), noms, node, env


def lancer(contexte, commande):
    dossier, _, _, _, env = contexte
    return subprocess.run(commande, cwd=dossier, env=env, text=True,
                          capture_output=True, timeout=120)


def verdict(contexte, execution, echecs):
    dossier, fonction, noms, node, _ = contexte
    journal = dossier / "tap.log"
    journal.write_text(execution.stdout + execution.stderr, encoding="utf-8")
    return lancer(contexte, ["bash", "-c", 'noeud="$1"\n' + fonction
                            + '\nverdict "$2" 2 "$3" "${@:4}"',
                            "chasse3c", node, str(journal), str(echecs), *noms])


def import_capture(contexte, journaliser):
    dossier, _, noms, node, _ = contexte
    fichier = dossier / "importe-capture.test.mjs"
    # La seule différence entre le témoin et son contrôle sain est le
    # diagnostic console.error d'une vraie exception d'import déjà capturée.
    fichier.write_text('''import { test } from "node:test";
import assert from "node:assert/strict";
test(NOM_1, async () => {
  let erreur;
  try { await import("./dependance-absente.mjs"); }
  catch (e) { erreur = e; }
  assert.equal(erreur?.code, "ERR_MODULE_NOT_FOUND");
  JOURNAL
});
test(NOM_2, () => { assert.equal(2 + 2, 4); });
'''.replace("NOM_1", json.dumps(noms[0]))
       .replace("NOM_2", json.dumps(noms[1]))
       .replace("JOURNAL", "console.error(erreur);" if journaliser else ""), encoding="utf-8")
    r = lancer(contexte, [node, "--test", "--test-reporter=tap", str(fichier)])
    assert r.returncode == 0, r.stdout + r.stderr
    for compteur in ("tests 2", "pass 2", "fail 0", "cancelled 0", "skipped 0", "todo 0"):
        assert re.search(rf"^# {compteur}$", r.stdout, re.MULTILINE), r.stdout
    for i, nom in enumerate(noms, 1):
        assert f"ok {i} - {nom}\n" in r.stdout
    return r


def test_chasse3c_verdict_accepte_un_import_refuse_et_capture(contexte):
    r = import_capture(contexte, journaliser=False)
    validation = verdict(contexte, r, 0)
    assert validation.returncode == 0, validation.stderr


# Contrat voisin, mcp/test/preuve-p15c.test.js : « un compte rendu de
# panne rejetée ne constitue pas lui-même une panne de chargement ».
# c275785 ne respecte ce contrat que pour le message simplifié du test
# voisin ; le format natif de console.error(erreur) produit un faux rejet.
def test_chasse3c_verdict_accepte_le_diagnostic_natif_dun_import_capture(contexte):
    r = import_capture(contexte, journaliser=True)
    assert re.search(r"^# Error \[ERR_MODULE_NOT_FOUND\]:", r.stdout, re.MULTILINE), r.stdout
    validation = verdict(contexte, r, 0)
    if validation.returncode != 0:
        raise DiagnosticAttenduRejete(
            "00u-F1 : Node rend 0, 2 tests passent ; verdict rejette le diagnostic "
            "de l'exception capturée :\n" + validation.stderr)


def test_chasse3c_verdict_refuse_de_vrais_imports_non_captures(contexte):
    dossier, _, _, node, _ = contexte
    fichiers = [dossier / f"import-non-capture-{i}.test.mjs" for i in range(2)]
    for fichier in fichiers:
        fichier.write_text('import "./dependance-absente.mjs";\n', encoding="utf-8")
    r = lancer(contexte, [node, "--test", "--test-reporter=tap", *map(str, fichiers)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ERR_MODULE_NOT_FOUND" in r.stdout
    assert re.search(r"^# tests 2$", r.stdout, re.MULTILINE)
    assert re.search(r"^# fail 2$", r.stdout, re.MULTILINE)
    assert verdict(contexte, r, 2).returncode != 0

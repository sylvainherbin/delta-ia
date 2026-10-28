"""04h : le YAML d'un résultat TAP ne doit pas être confondu avec du texte.

Cible : fonctions verdict extraites sans modification de preuve-p15c.sh et
preuve-p15d.sh. Node produit les journaux depuis des fixtures ; aucun TAP
fabriqué ou retouché, aucune recette complète, aucun réseau ni modèle.
Contrat : mcp/test/preuve-p15c.test.js exige une assertion réellement exécutée
pour chaque rouge nommé ; RELECTURE.md promet les témoins de mutation.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


RACINE = Path(__file__).resolve().parents[1]
NOMS = [
    "P15c R176 : erreurs des essais orientées vers le catalogue de référence",
    "P15c R178 : Bureau suit la constante de consultation",
]
PARENT_CORRECTIF = "77afdb7"


@pytest.fixture
def tap(tmp_path):
    noeud = shutil.which("node")
    assert noeud, "Node requis pour produire le TAP natif"
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    garde = tmp_path / "sans-reseau.mjs"
    garde.write_text('''import net from "node:net";
import tls from "node:tls";
import dgram from "node:dgram";
import dns from "node:dns";
import {syncBuiltinESMExports} from "node:module";
const interdit = () => { throw new Error("04h : réseau interdit"); };
globalThis.fetch = interdit;
net.connect = net.createConnection = interdit;
net.Socket.prototype.connect = net.Server.prototype.listen = interdit;
tls.connect = dgram.createSocket = dns.lookup = interdit;
syncBuiltinESMExports();
''', encoding="utf-8")
    env = {
        "PATH": os.defpath, "HOME": str(home), "TMPDIR": str(tmp_path),
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "NODE_OPTIONS": f"--import={garde.as_uri()}",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }

    def lancer(commande):
        return subprocess.run(commande, cwd=tmp_path, env=env,
                              text=True, capture_output=True, timeout=60)

    def fonction(source):
        trouves = re.findall(r"^verdict\(\) \{\n[\s\S]*?^JS\n\}", source, re.M)
        assert len(trouves) == 1, "fonction verdict réelle unique requise"
        return trouves[0]

    fonctions = {lettre: fonction((RACINE / f"mcp/preuve-p15{lettre}.sh").read_text(encoding="utf-8"))
                 for lettre in "cd"}
    historique = lancer(["git", "-C", str(RACINE), "show",
                         f"{PARENT_CORRECTIF}:mcp/preuve-p15c.sh"])
    assert historique.returncode == 0, historique.stderr
    fonctions["parent"] = fonction(historique.stdout)
    return tmp_path, noeud, lancer, fonctions


def produire(tap, variante):
    dossier, noeud, lancer, _ = tap
    trace = dossier / "corps.jsonl"
    # Texte ordinaire d'une erreur enveloppant un rapport d'enfant. Ces deux
    # lignes restent une CHAÎNE YAML, et ne sont pas des clés du diagnostic.
    message = "rapport du processus enfant :\nfailureType: 'testCodeFailure'\ncode: 'ERR_ASSERTION'"
    corps = f"fs.appendFileSync({json.dumps(str(trace))}, NAME + '\\n');"
    erreur = f"throw new Error({json.dumps(message if variante in ('message', 'hook-message') else 'préparation indisponible')});"
    fichiers = []
    for i, nom in enumerate(NOMS):
        source = ('import {test, before} from "node:test";\n'
                  'import fs from "node:fs";\n'
                  f'const NAME = {json.dumps(nom)};\n')
        if variante.startswith("hook"):
            source += f"before(() => {{ {erreur} }});\ntest(NAME, () => {{ {corps} }});\n"
        elif variante == "assertion":
            source += ('import assert from "node:assert/strict";\n'
                       f'test(NAME, () => {{ {corps} assert.fail("assertion métier"); }});\n')
        else:
            source += f"test(NAME, () => {{ {corps} {erreur} }});\n"
        fichier = dossier / f"{i}.test.mjs"
        fichier.write_text(source, encoding="utf-8")
        fichiers.append(str(fichier))
    retour = lancer([noeud, "--test", "--test-reporter=tap", "--test-concurrency=1", *fichiers])
    journal = dossier / "natif.tap"
    journal.write_text(retour.stdout + retour.stderr, encoding="utf-8")
    assert retour.returncode == 1, retour.stdout + retour.stderr
    for cle, valeur in {"tests": 2, "pass": 0, "fail": 2, "cancelled": 0, "skipped": 0, "todo": 0}.items():
        assert re.findall(rf"^# {cle} (\d+)$", retour.stdout, re.M) == [str(valeur)], retour.stdout
    assert re.findall(r"^not ok \d+ - (.+)$", retour.stdout, re.M) == NOMS
    assert re.search(r"^1\.\.2$", retour.stdout, re.M)
    if variante.startswith("hook"):
        assert not trace.exists(), "aucun corps ne doit être exécuté si la préparation échoue"
        assert re.findall(r"^  failureType: '([^']+)'$", retour.stdout, re.M) == ["hookFailed"] * 2
    else:
        assert trace.read_text(encoding="utf-8").splitlines() == NOMS
        assert re.findall(r"^  failureType: '([^']+)'$", retour.stdout, re.M) == ["testCodeFailure"] * 2
    if variante == "assertion":
        assert len(re.findall(r"^  code: 'ERR_ASSERTION'$", retour.stdout, re.M)) == 2
    else:
        assert not re.search(r"^  code: 'ERR_ASSERTION'$", retour.stdout, re.M), retour.stdout
    if variante in ("message", "hook-message"):
        assert len(re.findall(r"^    code: 'ERR_ASSERTION'$", retour.stdout, re.M)) == 2
        assert len(re.findall(r"^    failureType: 'testCodeFailure'$", retour.stdout, re.M)) == 2
        assert retour.stdout.count("  error: |-") == 2, retour.stdout
    return retour


def valider(tap, lettre, retour):
    dossier, noeud, lancer, fonctions = tap
    journal = dossier / "natif.tap"
    assert journal.read_text(encoding="utf-8") == retour.stdout + retour.stderr
    shell = ('set -euo pipefail\nnoeud="$1"\n' + fonctions[lettre]
             + '\nverdict "$2" 2 2 "${@:3}"\n')
    resultat = lancer(["bash", "-c", shell, "04h", noeud, str(journal), *NOMS])
    (dossier / f"verdict-{lettre}.log").write_text(resultat.stdout + resultat.stderr, encoding="utf-8")
    return resultat


@pytest.mark.parametrize("lettre", ["c", "d", "parent"])
def test_chasse8_assertions_reelles_acceptees(tap, lettre):
    retour = produire(tap, "assertion")
    resultat = valider(tap, lettre, retour)
    assert resultat.returncode == 0, resultat.stderr


@pytest.mark.parametrize("variante", ["erreur", "hook"])
@pytest.mark.parametrize("lettre", ["c", "d", "parent"])
def test_chasse8_erreurs_ordinaires_refusees(tap, lettre, variante):
    retour = produire(tap, variante)
    resultat = valider(tap, lettre, retour)
    assert resultat.returncode != 0, resultat.stdout


# Le parent, P15d et P15c refusent les clés contenues dans le scalaire.
@pytest.mark.parametrize("variante", ["message", "hook-message"])
def test_chasse8_p15c_refuse_des_cles_dans_un_message(tap, variante):
    retour = produire(tap, variante)
    for lettre in ("parent", "d"):
        resultat = valider(tap, lettre, retour)
        assert resultat.returncode != 0, resultat.stdout
    resultat = valider(tap, "c", retour)
    assert resultat.returncode != 0, resultat.stdout

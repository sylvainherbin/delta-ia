"""082 : P15d doit distinguer un test nommé par un chemin d'un résultat de fichier.

Contrat : mcp/RELECTURE.md, rejeu de la suite MCP ; tests/test_chasse7_ia.py,
acceptation d'une suite dont les assertions s'exécutent. Les quatre noms P15d
exigés par la recette sont présents. Les TAP viennent réellement de Node ; les
fonctions verdict courante et historique sont extraites sans modification.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


RACINE = Path(__file__).resolve().parents[1]
PARENT = "77afdb7a76f50b5d91b6f35bf7aa5a16585f2b73"
NOMS = [
    f"P15d : {objet} avec la constante à 4 en {langue}"
    for langue in ("fr", "en")
    for objet in ("descriptions servies", "aide du Bureau")
]


class VraiTestPrisPourFichier(AssertionError):
    """082-F1 : P15d rejette le nom d'un corps de test effectivement exécuté."""


def extraire(source):
    fonctions = re.findall(r"^verdict\(\) \{\n[\s\S]*?^JS\n\}", source, re.M)
    assert len(fonctions) == 1, "fonction verdict réelle unique requise"
    return fonctions[0]


@pytest.fixture
def contexte(tmp_path):
    node = shutil.which("node")
    assert node, "Node requis pour produire le TAP natif"
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    garde = tmp_path / "sans-reseau.mjs"
    garde.write_text('''import net from "node:net";
import tls from "node:tls";
import dgram from "node:dgram";
import dns from "node:dns";
import {syncBuiltinESMExports} from "node:module";
const interdit = () => { throw new Error("082 : réseau interdit"); };
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

    fonctions = {
        lettre: extraire((RACINE / f"mcp/preuve-p15{lettre}.sh").read_text(encoding="utf-8"))
        for lettre in "cd"
    }
    ancien = lancer(["git", "-C", str(RACINE), "show", f"{PARENT}:mcp/preuve-p15d.sh"])
    assert ancien.returncode == 0, ancien.stderr
    fonctions["parent"] = extraire(ancien.stdout)
    return tmp_path, node, lancer, fonctions


def produire(contexte, variante):
    dossier, node, lancer, _ = contexte
    trace = dossier / "assertions-executees.jsonl"
    cible = dossier / "fichier-verifie.mjs"
    cible.write_text("export const valeur = 42;\n", encoding="utf-8")
    nom = {
        "posix": str(cible),
        "windows": r"C:\copie\mcp\api\mcp.js",
        "relatif": "mcp/api/mcp.js",
        "ordinaire": "contenu du fichier source",
    }.get(variante)
    source = ('import {test} from "node:test";\n'
              'import assert from "node:assert/strict";\n'
              'import fs from "node:fs";\n'
              f'const trace = {json.dumps(str(trace))};\n')
    for i, nom_attendu in enumerate(NOMS):
        source += (f'test({json.dumps(nom_attendu)}, () => {{ '
                   'assert.equal(2 + 2, 4); '
                   f'fs.appendFileSync(trace, {json.dumps(str(i) + chr(10))}); }});\n')
    if nom:
        # Le nom est une étiquette ; même sous Windows aucun chemin hôte n'est ouvert.
        # Le corps lit la vraie fixture locale puis exécute son assertion et sa trace.
        source += (f'test({json.dumps(nom)}, () => {{ '
                   f'assert.match(fs.readFileSync({json.dumps(str(cible))}, "utf8"), /valeur = 42/); '
                   'fs.appendFileSync(trace, "4\\n"); });\n')
    fixture = dossier / "corps.test.mjs"
    fixture.write_text(source, encoding="utf-8")
    fichiers = [str(fixture)]
    if variante == "sans-corps":
        fichiers.append(str(cible))  # vrai module chargé, sans aucun appel à test()
    retour = lancer([node, "--test", "--test-reporter=tap", "--test-concurrency=1", *fichiers])
    assert retour.returncode == 0, retour.stdout + retour.stderr
    assert retour.stderr == "", retour.stderr
    nombre = 5 if nom or variante == "sans-corps" else 4
    for cle, valeur in {"tests": nombre, "pass": nombre, "fail": 0,
                       "cancelled": 0, "skipped": 0, "todo": 0}.items():
        assert re.findall(rf"^# {cle} (\d+)$", retour.stdout, re.M) == [str(valeur)], retour.stdout
    assert re.findall(r"^1\.\.(\d+)$", retour.stdout, re.M) == [str(nombre)]
    assert trace.read_text(encoding="utf-8").splitlines() == [str(i) for i in range(5 if nom else 4)]
    if nom:
        # Node échappe les antislashs du nom Windows dans son propre TAP.
        assert f"ok 5 - {nom.replace(chr(92), chr(92) * 2)}\n" in retour.stdout, retour.stdout
    journal = dossier / "natif.tap"
    journal.write_text(retour.stdout, encoding="utf-8")
    return journal, nombre


def valider(contexte, lettre, journal, nombre):
    dossier, node, lancer, fonctions = contexte
    shell = ('set -euo pipefail\nnoeud="$1"\n' + fonctions[lettre]
             + '\nverdict "$2" "$3" 0 "${@:4}"\n')
    retour = lancer(["bash", "-c", shell, "082", node, str(journal),
                     str(nombre) if lettre == "c" else "suite", *NOMS])
    (dossier / f"verdict-{lettre}.log").write_text(retour.stdout + retour.stderr, encoding="utf-8")
    return retour


@pytest.mark.parametrize("variante", ["ordinaire", "relatif"])
def test_chasse9_p15d_accepte_les_corps_sans_chemin_absolu(contexte, variante):
    journal, nombre = produire(contexte, variante)
    resultat = valider(contexte, "d", journal, nombre)
    assert resultat.returncode == 0, resultat.stderr


def test_chasse9_p15d_refuse_un_module_sans_corps_en_plus_des_temoins(contexte):
    journal, nombre = produire(contexte, "sans-corps")
    resultat = valider(contexte, "d", journal, nombre)
    assert resultat.returncode != 0, resultat.stdout
    assert "résultat de fichier ou test non vert" in resultat.stderr


@pytest.mark.parametrize("variante", ["posix", "windows"])
@pytest.mark.xfail(strict=True, raises=VraiTestPrisPourFichier,
                   reason="082-F1 : un nom de chemin ne prouve pas l'absence de corps")
def test_chasse9_p15d_accepte_un_vrai_test_nomme_par_un_chemin(contexte, variante):
    journal, nombre = produire(contexte, variante)
    for lettre in ("parent", "c"):
        resultat = valider(contexte, lettre, journal, nombre)
        assert resultat.returncode == 0, resultat.stderr
    resultat = valider(contexte, "d", journal, nombre)
    if resultat.returncode != 0:
        assert "résultat de fichier ou test non vert" in resultat.stderr, resultat.stderr
        raise VraiTestPrisPourFichier(
            f"082-F1 ({variante}) : 5 corps et assertions exécutés, 5 pass, quatre témoins présents ; "
            "P15d rejette le nom du cinquième test :\n" + resultat.stderr)

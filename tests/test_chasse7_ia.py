"""03u : limites résiduelles des verdicts TAP P15c/P15d, sans correction.

Contrats : mcp/test/preuve-p15c.test.js (témoins verts nommés, résultats
cohérents) et mcp/RELECTURE.md (rejeu de la suite MCP courante).
Les fonctions Bash sont extraites à l'identique. Node produit les TAP à partir
de fixtures ; aucun journal n'est fabriqué ou retouché, aucune recette complète
n'est exécutée. Les xfail stricts ne couvrent que les désaccords de verdict.
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


class SousTestsValidesRejetes(AssertionError):
    """03u-F1 : seuls les résultats non indentés sont comptés par P15c."""


class SuiteSansCorpsAcceptee(AssertionError):
    """03u-F2 : le succès du fichier remplace l'exécution de ses tests."""


@pytest.fixture
def contexte_tap(tmp_path):
    node = shutil.which("node")
    assert node, "Node requis pour produire du TAP natif"
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    garde = tmp_path / "sans-reseau.mjs"
    garde.write_text('''import net from "node:net";
import tls from "node:tls";
import dgram from "node:dgram";
const interdire = () => { throw new Error("03u : réseau interdit"); };
globalThis.fetch = interdire;
net.Socket.prototype.connect = interdire;
net.Server.prototype.listen = interdire;
tls.connect = interdire;
dgram.createSocket = interdire;
''', encoding="utf-8")
    env = {
        "PATH": os.defpath, "HOME": str(home), "TMPDIR": str(tmp_path),
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "NODE_OPTIONS": f"--import={garde.as_uri()}",
    }
    fonctions = {}
    for lettre in "cd":
        source = (RACINE / f"mcp/preuve-p15{lettre}.sh").read_text(encoding="utf-8")
        fonctions_trouvees = re.findall(r"^verdict\(\) \{\n[\s\S]*?^JS\n\}", source, re.M)
        assert len(fonctions_trouvees) == 1, "fonction réelle unique requise"
        fonctions[lettre] = fonctions_trouvees[0]
    return tmp_path, node, env, fonctions


def lancer(contexte, commande):
    dossier, _, env, _ = contexte
    return subprocess.run(commande, cwd=dossier, env=env, capture_output=True,
                          text=True, timeout=60)


def produire(contexte, source):
    dossier, node, _, _ = contexte
    fichier = dossier / "fixture.test.mjs"
    fichier.write_text(source, encoding="utf-8")
    retour = lancer(contexte, [node, "--test", "--test-reporter=tap", str(fichier)])
    journal = dossier / "natif.tap"
    journal.write_text(retour.stdout + retour.stderr, encoding="utf-8")
    return retour


def compteurs(retour, *, tests, echecs=0, sautes=0, todo=0):
    assert retour.returncode == int(echecs > 0), retour.stdout + retour.stderr
    valeurs = {"tests": tests, "fail": echecs, "pass": tests - echecs - sautes - todo,
               "cancelled": 0, "skipped": sautes, "todo": todo}
    for compteur, valeur in valeurs.items():
        assert re.findall(rf"^# {compteur} (\d+)$", retour.stdout, re.M) == [str(valeur)], retour.stdout
    assert re.search(r"^1\.\.\d+$", retour.stdout, re.M), retour.stdout


def verdict(contexte, lettre, retour, tests, echecs, noms=()):
    dossier, node, _, fonctions = contexte
    journal = dossier / "natif.tap"
    assert journal.read_text(encoding="utf-8") == retour.stdout + retour.stderr
    shell = ('set -euo pipefail\nnoeud="$1"\n' + fonctions[lettre]
             + '\nverdict "$2" "$3" "$4" "${@:5}"\n')
    validation = lancer(contexte, ["bash", "-c", shell, "03u", node, str(journal),
                                  str(tests), str(echecs), *noms])
    (dossier / f"verdict-p15{lettre}.log").write_text(
        validation.stdout + validation.stderr, encoding="utf-8")
    return validation


def deux_assertions(contexte, structure, *, rouges=False):
    dossier, _, _, _ = contexte
    trace = dossier / "corps-executes.jsonl"
    source = ('import {test, describe} from "node:test";\n'
              'import assert from "node:assert/strict";\n'
              'import fs from "node:fs";\n'
              f'const trace = {json.dumps(str(trace))};\n')
    def corps(i):
        return (f'fs.appendFileSync(trace, {json.dumps(str(i) + chr(10))});\n'
                + ('assert.fail("témoin rouge métier");' if rouges else 'assert.equal(2 + 2, 4);'))
    if structure == "sous-test":
        source += (f'test({json.dumps(NOMS[0])}, async t => {{\n{corps(0)}\n'
                   f'await t.test({json.dumps(NOMS[1])}, () => {{ {corps(1)} }});\n}});\n')
    else:
        tests = "\n".join(f'test({json.dumps(nom)}, () => {{ {corps(i)} }});'
                          for i, nom in enumerate(NOMS))
        source += 'describe("suite", () => {\n' + tests + '\n});\n' if structure == "suite" else tests
    retour = produire(contexte, source)
    assert trace.read_text(encoding="utf-8").splitlines() == ["0", "1"], retour.stdout
    compteurs(retour, tests=2, echecs=2 if rouges else 0)
    assert "hookFailed" not in retour.stdout
    assert "ERR_MODULE_NOT_FOUND" not in retour.stdout
    return retour


@pytest.mark.parametrize("lettre", ["c", "d"])
@pytest.mark.parametrize("rouges", [False, True])
def test_chasse7_deux_assertions_plates_acceptees(contexte_tap, lettre, rouges):
    retour = deux_assertions(contexte_tap, "plat", rouges=rouges)
    validation = verdict(contexte_tap, lettre, retour, 2, 2 if rouges else 0, NOMS)
    assert validation.returncode == 0, validation.stderr


@pytest.mark.parametrize("structure", ["plat", "suite", "sous-test"])
def test_chasse7_p15d_accepte_une_suite_executant_ses_assertions(contexte_tap, structure):
    retour = deux_assertions(contexte_tap, structure)
    validation = verdict(contexte_tap, "d", retour, "suite", 0)
    assert validation.returncode == 0, validation.stderr


# Résiduel hérité de c275785 : le total Node inclut les tests imbriqués,
# tandis que /^ok/ ne voit que le résultat englobant. 16b26fc le conserve.
@pytest.mark.xfail(strict=True, raises=SousTestsValidesRejetes)
@pytest.mark.parametrize("structure", ["suite", "sous-test"])
def test_chasse7_p15c_accepte_deux_assertions_vertes_imbriquees(contexte_tap, structure):
    retour = deux_assertions(contexte_tap, structure)
    for nom in NOMS:
        assert re.search(rf"^\s*ok \d+ - {re.escape(nom)}$", retour.stdout, re.M), retour.stdout
    assert len(re.findall(r"^ok \d+ - ", retour.stdout, re.M)) == 1
    validation = verdict(contexte_tap, "c", retour, 2, 0, NOMS)
    if validation.returncode != 0:
        raise SousTestsValidesRejetes(
            f"03u-F1 ({structure}) : Node rend 0, deux corps exécutés, deux passes ; "
            "P15c compte seulement le résultat englobant :\n" + validation.stderr)


# Résiduel de la phase verte dynamique dd6a8e8 : 9483341 a renforcé les
# rouges, mais la phase « suite 0 » accepte encore un pseudo-test de fichier.
@pytest.mark.xfail(strict=True, raises=SuiteSansCorpsAcceptee)
@pytest.mark.parametrize("variante", ["aucun-test", "sortie-avant-corps"])
def test_chasse7_p15d_refuse_une_suite_sans_corps_execute(contexte_tap, variante):
    dossier, _, _, _ = contexte_tap
    charge, corps = dossier / "module-charge", dossier / "corps-execute"
    source = ('import fs from "node:fs";\n'
              f'fs.writeFileSync({json.dumps(str(charge))}, "chargé");\n')
    if variante == "aucun-test":
        source += "export const fixture = 42;\n"
    else:
        source += ('import {test} from "node:test";\n'
                   'import assert from "node:assert/strict";\n'
                   f'test("corps jamais exécuté", () => {{ fs.writeFileSync({json.dumps(str(corps))}, "appelé"); '
                   'assert.fail("ce test doit être rouge s’il est exécuté"); });\n'
                   'process.exit(0);\n')
    retour = produire(contexte_tap, source)
    compteurs(retour, tests=1)
    assert charge.read_text(encoding="utf-8") == "chargé"
    assert not corps.exists(), "le corps interdit n'a pas été exécuté"
    assert f"ok 1 - {dossier / 'fixture.test.mjs'}\n" in retour.stdout, retour.stdout
    assert "ok 1 - corps jamais exécuté\n" not in retour.stdout
    validation = verdict(contexte_tap, "d", retour, "suite", 0)
    if validation.returncode == 0:
        raise SuiteSansCorpsAcceptee(
            f"03u-F2 ({variante}) : aucun corps de test ni assertion exécutés ; "
            "Node certifie seulement le fichier, P15d accepte « suite 0 » :\n" + validation.stdout)


@pytest.mark.parametrize("lettre", ["c", "d"])
@pytest.mark.parametrize("directive", ["skip", "todo"])
def test_chasse7_sauts_et_todo_refuses(contexte_tap, lettre, directive):
    source = 'import {test} from "node:test";\nimport assert from "node:assert/strict";\n'
    source += "\n".join(f'test({json.dumps(nom)}, {{ {directive}: true }}, () => assert.fail("non probant"));'
                        for nom in NOMS)
    retour = produire(contexte_tap, source)
    compteurs(retour, tests=2, sautes=2 if directive == "skip" else 0,
              todo=2 if directive == "todo" else 0)
    validation = verdict(contexte_tap, lettre, retour, "suite" if lettre == "d" else 2, 0, NOMS)
    assert validation.returncode != 0, validation.stdout

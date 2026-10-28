"""02a-F1 : P15d doit distinguer ses assertions rouges d'une préparation en panne.

La cible est la fonction verdict de mcp/preuve-p15d.sh, extraite sans modification.
Le TAP vient des quatre vrais témoins historiques épinglés par cette recette,
exécutés sur sa vraie base. Seules les fixtures archivées perdent une dépendance.
Aucune recette complète, connexion, écoute ou modification de production.
"""

import io
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


RACINE = Path(__file__).resolve().parent.parent
BASE = "5a66288617f25d6f08b6d7af64424196fa19dcd4"
TEMOINS = "8a513c88a6895050b496379826b36d4705a3fac3"


class RougeSansAssertionAccepte(AssertionError):
    """Le validateur accepte une panne des hooks comme une preuve métier rouge."""


@pytest.fixture
def execution_isolee(tmp_path):
    noeud = shutil.which("node")
    assert noeud, "Node requis pour produire le véritable TAP"
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()
    garde = tmp_path / "sans-reseau.mjs"
    garde.write_text(
        'import net from "node:net";\n'
        'import tls from "node:tls";\n'
        'import dgram from "node:dgram";\n'
        'import dns from "node:dns";\n'
        'import { syncBuiltinESMExports } from "node:module";\n'
        'const interdit = () => { throw new Error("02a : réseau interdit"); };\n'
        'globalThis.fetch = interdit;\n'
        'net.connect = net.createConnection = interdit;\n'
        'net.Socket.prototype.connect = net.Server.prototype.listen = interdit;\n'
        'tls.connect = dgram.createSocket = dns.lookup = interdit;\n'
        'syncBuiltinESMExports();\n', encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", os.defpath), "HOME": str(home),
        "TMPDIR": str(temp), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0", "NODE_OPTIONS": f"--import={garde}",
    }

    def lancer(commande, *, binaire=False):
        return subprocess.run(
            commande, cwd=RACINE, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=not binaire, timeout=120,
        )

    return noeud, lancer


def phase_rouge(tmp_path, execution_isolee, *, dependance_absente=None):
    noeud, lancer = execution_isolee
    archive = lancer(["git", "archive", BASE, "mcp"], binaire=True)
    assert archive.returncode == 0, archive.stderr
    copie = tmp_path / "avant"
    copie.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as fichiers:
        fichiers.extractall(copie, filter="data")
    historique = lancer(["git", "show", f"{TEMOINS}:mcp/test/textes.test.js"], binaire=True)
    assert historique.returncode == 0, historique.stderr
    temoin = copie / "mcp/test/textes.test.js"
    temoin.write_bytes(historique.stdout)
    if dependance_absente:
        # Panne de fixture uniquement : les tests et le validateur restent inchangés.
        (copie / "mcp" / dependance_absente).unlink()
    node = lancer([noeud, "--test", "--test-reporter=tap", str(temoin)])
    assert node.returncode == 1, node.stdout + node.stderr
    tap = node.stdout + node.stderr
    for compteur, valeur in (("tests", 4), ("pass", 0), ("fail", 4),
                              ("cancelled", 0), ("skipped", 0), ("todo", 0)):
        assert re.search(rf"^# {compteur} {valeur}$", tap, re.MULTILINE), tap
    noms = re.findall(r"^not ok \d+ - (P15d : .+)$", tap, re.MULTILINE)
    assert len(set(noms)) == 4, tap
    journal = tmp_path / "rouge-node.tap"
    journal.write_text(tap, encoding="utf-8")

    recette = (RACINE / "mcp/preuve-p15d.sh").read_text(encoding="utf-8")
    fonctions = re.findall(r"^verdict\(\) \{\n[\s\S]*?^JS\n\}", recette, re.MULTILINE)
    assert len(fonctions) == 1, "fonction réelle de contrôle P15d requise"
    shell = 'set -euo pipefail\nnoeud="$1"\n' + fonctions[0] + '\nverdict "$2" 4 4\n'
    verdict = lancer(["bash", "-c", shell, "chasse5-ia", noeud, str(journal)])
    (tmp_path / "verdict.log").write_text(verdict.stdout + verdict.stderr, encoding="utf-8")
    return verdict, tap


def test_chasse5_p15d_accepte_les_quatre_assertions_historiques(tmp_path, execution_isolee):
    verdict, tap = phase_rouge(tmp_path, execution_isolee)
    assert tap.count("failureType: 'testCodeFailure'") == 4, tap
    assert tap.count("code: 'ERR_ASSERTION'") == 4, tap
    assert "hookFailed" not in tap
    assert verdict.returncode == 0, verdict.stdout + verdict.stderr


@pytest.mark.parametrize("dependance", ["bureau.js", "lib/textes.js"])
def test_chasse5_p15d_refuse_un_rouge_sans_assertion(tmp_path, execution_isolee, dependance):
    verdict, tap = phase_rouge(tmp_path, execution_isolee, dependance_absente=dependance)
    assert tap.count("failureType: 'hookFailed'") == 4, tap
    assert "failureType: 'testCodeFailure'" not in tap, tap
    assert "code: 'ERR_ASSERTION'" not in tap, tap
    assert ("ENOENT" if dependance == "bureau.js" else "ERR_MODULE_NOT_FOUND") in tap, tap
    if verdict.returncode == 0:
        raise RougeSansAssertionAccepte(
            f"02a-F1 : {dependance} absent dans la fixture ; Node rend 1, "
            "4 tests / 4 hookFailed / aucune assertion ; verdict P15d rend 0\n"
            + verdict.stdout
        )

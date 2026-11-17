"""Séquence des unités rejouée sur un faux dépôt, sans systemd ni import du code sale."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

RACINE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("nom", ["commun", "selection"])
@pytest.mark.parametrize("etat", ["propre", "modifie", "index", "non_suivi"])
def test_arret_avant_import_du_module_sale(tmp_path, nom, etat):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "piege.py").write_text("# fixture ordinaire\n")
    (scripts / f"{nom}_auto.py").write_text("import piege\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    git("init", "-q")
    git("add", "scripts")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "initial")
    if etat != "propre":
        (scripts / "piege.py").write_text("from pathlib import Path\nPath('IMPORTE').write_text('fixture')\n")
        if etat == "index":
            git("add", "scripts/piege.py")
        elif etat == "non_suivi":
            git("rm", "--cached", "scripts/piege.py")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "retirer du suivi")
    unite = (RACINE / f"deploy/systemd/delta-ia-{nom}.service").read_text()
    pre = [l.partition("=")[2] for l in unite.splitlines() if l.startswith("ExecStartPre=")]
    # S'il manque, le simulateur lance directement ExecStart : le témoin importe le piège.
    code = 0
    for ligne in pre:
        resultat = subprocess.run(shlex.split(ligne), cwd=tmp_path, env=env, capture_output=True, text=True)
        code = resultat.returncode
        if code:
            assert "ARBRE_CODE_SALE" in resultat.stderr
            break
    if code == 0:
        subprocess.run([sys.executable, "-B", str(scripts / f"{nom}_auto.py")], cwd=tmp_path, env=env, check=True)
    assert code == (0 if etat == "propre" else 126)
    assert not (tmp_path / "IMPORTE").exists()

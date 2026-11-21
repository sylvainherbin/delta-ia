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


def _env_unite(unite: str, tmp_path: Path) -> dict:
    """Environnement que systemd donne à ExecStart : lignes Environment= de l'unité, %h et %t remplacés par des dossiers de test."""
    env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path / "home")}
    for ligne in unite.splitlines():
        if ligne.startswith("Environment="):
            for affectation in shlex.split(ligne.partition("=")[2]):
                cle, _, valeur = affectation.partition("=")
                env[cle] = valeur.replace("%h", str(tmp_path / "home")).replace("%t", str(tmp_path / "run"))
    return env


def _depot_scripts(tmp_path: Path, nom: str) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc\nrapports/\n")  # comme le dépôt : __pycache__/ échappe à git status
    (scripts / "piege.py").write_text("# fixture ordinaire\n")
    (scripts / f"{nom}_auto.py").write_text("import piege\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (["init", "-q"], ["add", ".gitignore", "scripts"],
                 ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "initial"]):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    return scripts


def _pre(unite: str, tmp_path: Path, env: dict) -> list:
    return [subprocess.run(shlex.split(l.partition("=")[2]), cwd=tmp_path, env=env, capture_output=True, text=True)
            for l in unite.splitlines() if l.startswith("ExecStartPre=")]


@pytest.mark.parametrize("nom", ["commun", "selection"])
def test_pyc_piege_dans_l_arbre_n_est_pas_charge(tmp_path, nom):
    """B2 : un .pyc valide pour la source propre (même mtime, même taille) mais compilé d'un code piégé, posé dans
    scripts/__pycache__/ (ignoré par git) : PYTHONPYCACHEPREFIX de l'unité le fait ignorer."""
    import importlib.util
    import marshal
    scripts = _depot_scripts(tmp_path, nom)
    st = (scripts / "piege.py").stat()
    code = compile("from pathlib import Path\nPath('IMPORTE').write_text('pyc')\n", str(scripts / "piege.py"), "exec")
    pyc = scripts / "__pycache__" / f"piege.{sys.implementation.cache_tag}.pyc"
    pyc.parent.mkdir()
    pyc.write_bytes(importlib.util.MAGIC_NUMBER + (0).to_bytes(4, "little") + (int(st.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
                    + (st.st_size & 0xFFFFFFFF).to_bytes(4, "little") + marshal.dumps(code))
    unite = (RACINE / f"deploy/systemd/delta-ia-{nom}.service").read_text()
    env = _env_unite(unite, tmp_path)
    assert all(r.returncode == 0 for r in _pre(unite, tmp_path, env)), "arbre propre pour git : le piège passe le contrôle"
    temoin = subprocess.run([sys.executable, "-B", str(scripts / f"{nom}_auto.py")], cwd=tmp_path,
                            env={k: v for k, v in env.items() if k != "PYTHONPYCACHEPREFIX"}, check=True)
    assert temoin.returncode == 0 and (tmp_path / "IMPORTE").exists(), "témoin : sans le préfixe, le .pyc piégé est chargé"
    (tmp_path / "IMPORTE").unlink()
    subprocess.run([sys.executable, "-B", str(scripts / f"{nom}_auto.py")], cwd=tmp_path, env=env, check=True)
    assert env["PYTHONPYCACHEPREFIX"] == str(tmp_path / "run" / "delta-ia-pycache")
    assert not (tmp_path / "IMPORTE").exists()


@pytest.mark.parametrize("nom", ["commun", "selection"])
def test_temoin_d_incident_arrete_avant_le_python_du_venv(tmp_path, nom):
    """B2 : témoin d'incident git présent (un .pth ou un hook peut avoir été posé) : ExecStartPre rend 126 avant ExecStart."""
    _depot_scripts(tmp_path, nom)
    unite = (RACINE / f"deploy/systemd/delta-ia-{nom}.service").read_text()
    env = _env_unite(unite, tmp_path)
    assert all(r.returncode == 0 for r in _pre(unite, tmp_path, env))
    (tmp_path / "rapports" / "auto").mkdir(parents=True)
    (tmp_path / "rapports" / "auto" / "incident-git.json").write_text("{}\n")
    codes = [(r.returncode, r.stderr) for r in _pre(unite, tmp_path, env)]
    assert any(c == 126 and "INCIDENT_GIT" in e for c, e in codes)


def _faux_git(tmp_path: Path, env: dict) -> Path:
    """git du PATH de l'unité (%h/.local/bin en tête) qui laisse une trace avant d'appeler le vrai : un hook ou un réglage
    posé s'exécuterait à ce moment-là."""
    trace = tmp_path / "git-lance"
    bin_ = tmp_path / "home" / ".local" / "bin"
    bin_.mkdir(parents=True, exist_ok=True)
    (bin_ / "git").write_text(f"#!/bin/sh\necho \"$@\" >> '{trace}'\nexec /usr/bin/git \"$@\"\n")
    (bin_ / "git").chmod(0o755)
    env.setdefault("PATH", f"{bin_}:/usr/bin:/bin")  # unité sans Environment=PATH : celui de systemd --user, sans ~/.local/bin
    if not env["PATH"].startswith(str(bin_)):
        env["PATH"] = f"{bin_}:{env['PATH']}"
    return trace


def _sequence(unite: str, tmp_path: Path, env: dict) -> list:
    """ExecStartPre dans l'ordre, comme systemd : le premier code non nul arrête l'unité."""
    faits = []
    for l in unite.splitlines():
        if l.startswith("ExecStartPre="):
            faits.append(subprocess.run(shlex.split(l.partition("=")[2]), cwd=tmp_path, env=env, capture_output=True, text=True))
            if faits[-1].returncode:
                break
    return faits


UNITES = ["deploy/systemd/delta-ia-commun.service", "deploy/systemd/delta-ia-selection.service"]


@pytest.mark.parametrize("chemin", UNITES)
def test_temoin_d_incident_avant_tout_git(tmp_path, chemin):
    """SUITE 3, B1 : le témoin est le premier ExecStartPre ; tant qu'il existe, git n'est pas lancé (un hook ou un réglage
    git posé, cause du témoin, s'exécuterait au premier git)."""
    _depot_scripts(tmp_path, "commun")
    unite = (RACINE / chemin).read_text()
    env = _env_unite(unite, tmp_path)
    trace = _faux_git(tmp_path, env)
    (tmp_path / "rapports" / "auto").mkdir(parents=True)
    (tmp_path / "rapports" / "auto" / "incident-git.json").write_text("{}\n")
    faits = _sequence(unite, tmp_path, env)
    assert len(faits) == 1 and faits[0].returncode == 126 and "INCIDENT_GIT" in faits[0].stderr, "le témoin est le premier contrôle"
    assert not trace.exists(), "aucun git avant le témoin"
    (tmp_path / "rapports" / "auto" / "incident-git.json").unlink()
    assert all(r.returncode == 0 for r in _sequence(unite, tmp_path, env)) and trace.exists(), "témoin levé : le contrôle git suit"

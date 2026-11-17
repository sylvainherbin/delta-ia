"""Frontière des commits : dépôts synthétiques, origin local, aucun réseau."""
import subprocess
import sys
from pathlib import Path

import pytest
import orchestrateur as orc


def git(racine, *args):
    return subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def depot(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for cle in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(cle, "Fixture")
    for cle in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(cle, "fixture@example.invalid")
    racine = tmp_path / "depot"
    racine.mkdir()
    git(racine, "init", "-q", "-b", "main")
    git(tmp_path, "init", "-q", "--bare", str(tmp_path / "origin.git"))
    (racine / ".gitignore").write_text("rapports/\n")
    git(racine, "add", ".gitignore")
    git(racine, "commit", "-qm", "initial")
    git(racine, "remote", "add", "origin", str(tmp_path / "origin.git"))
    git(racine, "push", "-q", "origin", "HEAD:main")
    return racine


@pytest.mark.parametrize("chemin,pousser,code", [
    ("scripts/piege.py", True, 126),
    ("scripts/piege.py", False, 126),
    (" docs/data/openai/fixture.json", True, 126),
    ("docs/data/openai/jour.json", True, 0),
    (None, False, 0),
])
def test_chemins_des_commits_apres_etape(depot, monkeypatch, chemin, pousser, code):
    cfg = orc.charger_config()
    cfg["chaine"].pop("capteur_x", None)
    e = orc.Etape("codex-delta", "codex", [sys.executable], 10,
                  checkout=["docs/data/openai", "state/openai.json"])
    def agent(*args):
        if chemin:
            cible = depot / chemin
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_text("fixture\n")
            git(depot, "add", chemin)
            git(depot, "commit", "-qm", "fixture étape")
            if pousser:
                git(depot, "push", "-q", "origin", "HEAD:main")
        return orc.Resultat(0, "", "", False, 0)
    monkeypatch.setattr(orc, "lancer", agent)
    monkeypatch.setattr(orc, "version_codex", lambda *a, **kw: None)
    c = orc.Chaine(depot, cfg, [e], distant=False)
    issue = c.executer_etape(e)
    assert issue.code == code
    if code == 126:
        assert issue.arret_chaine
        tete = git(depot, "rev-parse", "HEAD")
        assert chemin in issue.detail and tete in issue.detail and e.nom in issue.detail
        rapport = next((depot / "rapports/auto").glob("*.log")).read_text()
        assert "PERIMETRE_COMMITS" in rapport and chemin in rapport
        assert (depot / chemin).exists()  # aucun revert/nettoyage de l'incident


def test_commit_retabli_ne_cache_pas_un_chemin_interdit(depot):
    debut = git(depot, "rev-parse", "origin/main")
    (depot / "interdit.txt").write_text("fixture")
    git(depot, "add", "interdit.txt")
    git(depot, "commit", "-qm", "ajout interdit")
    (depot / "interdit.txt").unlink()
    git(depot, "add", "interdit.txt")
    git(depot, "commit", "-qm", "suppression interdite")
    git(depot, "push", "-q", "origin", "HEAD:main")
    e = orc.Etape("codex-delta", "codex", [], 10, checkout=["docs/data/openai"])
    assert "interdit.txt" in orc.controle_commits(depot, e, debut)

"""Messages du pont vers la boîte du chef dev, sans remise à un rôle d'OPÉRER."""

import os
import re
import subprocess

import pytest

from conftest import RACINE


@pytest.fixture
def pont(tmp_path):
    maison = tmp_path / "maison"
    binaires = tmp_path / "bin"
    binaires.mkdir()
    appel = tmp_path / "operer-appele"
    faux = binaires / "operer"
    faux.write_text('#!/bin/sh\n: > "$APPEL_OPERER"\nexit 97\n', encoding="utf-8")
    faux.chmod(0o755)
    env = {**os.environ, "HOME": str(maison), "PATH": f"{binaires}{os.pathsep}{os.defpath}",
           "APPEL_OPERER": str(appel), "BRANCHE": "reglages-pont/2026-10-27", "WT": str(tmp_path / "worktree dédié"),
           "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@exemple.test",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@exemple.test"}
    for variable in ("DELTA_PONT_BOITE", "DELTA_PONT_SANS_MESSAGE"):
        env.pop(variable, None)
    for args in (["init", "-q", "-b", "main"],
                 ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    hash_attendu = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, env=env, text=True).strip()
    # Charge la vraie fonction seule : aucun collecteur, worktree ou état réel n'est touché.
    script = (RACINE / "scripts/reglages-pont.sh").read_text(encoding="utf-8")
    fonction = "prevenir() {" + script.split("prevenir() {", 1)[1].split("\nechec()", 1)[0]

    def lancer(**variables):
        resultat = subprocess.run(["bash", "-uc", fonction + '\nprevenir "$1"', "pont", "Constats à relire.\nDeuxième ligne."],
                                  cwd=tmp_path, env={**env, **variables}, capture_output=True, text=True, timeout=10)
        assert not appel.exists(), "operer ne doit jamais être appelé, même si son échec est masqué"
        return resultat

    return lancer, maison, hash_attendu, env


@pytest.mark.parametrize("personnalisee", [False, True])
def test_message_date_dans_la_boite_du_chef_dev(pont, tmp_path, personnalisee):
    lancer, maison, hash_attendu, env = pont
    defaut = maison / ".local/state/chef-dev/boite"
    boite = tmp_path / "autre boîte" if personnalisee else defaut
    resultat = lancer(**({"DELTA_PONT_BOITE": str(boite)} if personnalisee else {}))
    assert resultat.returncode == 0, resultat.stderr
    fichiers = list(boite.iterdir())
    assert len(fichiers) == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{6}-reglages-pont\.md", fichiers[0].name)
    assert fichiers[0].read_text(encoding="utf-8") == (
        f"[PONT RÉGLAGES] Constats à relire.\nDeuxième ligne.\n\nBranche : {env['BRANCHE']}\n"
        f"Hash : {hash_attendu}\nWorktree : {env['WT']}\n")
    if personnalisee:
        assert not defaut.exists()


def test_sans_message_affiche_sans_creer_la_boite(pont, tmp_path):
    lancer, maison, _, _ = pont
    boite = tmp_path / "boîte désactivée"
    resultat = lancer(DELTA_PONT_SANS_MESSAGE="1", DELTA_PONT_BOITE=str(boite))
    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stdout == "[PONT RÉGLAGES] Constats à relire.\nDeuxième ligne.\n"
    assert not boite.exists() and not (maison / ".local/state/chef-dev/boite").exists()


def test_deux_messages_conservent_deux_fichiers(pont, tmp_path):
    lancer, _, _, _ = pont
    boite = tmp_path / "boîte"
    for _ in range(2):
        resultat = lancer(DELTA_PONT_BOITE=str(boite))
        assert resultat.returncode == 0, resultat.stderr
    fichiers = list(boite.iterdir())
    assert len(fichiers) == 2
    assert fichiers[0].read_bytes() == fichiers[1].read_bytes()


def test_script_et_unites_sans_routage_operer():
    chemins = [RACINE / "scripts/reglages-pont.sh", *(RACINE / "deploy/systemd").glob("*reglages-pont.*.exemple")]
    for chemin in chemins:
        texte = chemin.read_text(encoding="utf-8")
        assert not re.search(r"operer|OPÉRER|--(?:de|role)\s+delta\b", texte), chemin

"""D87 : scripts/verifier.py réutilise un résultat par arbre ; commandes factices, registre et verrous dans tmp_path."""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys

import pytest

import verifier

ENV_GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@exemple.test", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@exemple.test", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def git(racine, *args, env=None):
    import os
    subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True, env={**os.environ, **ENV_GIT})


@pytest.fixture
def depot(tmp_path):
    racine = tmp_path / "depot"
    racine.mkdir()
    git(racine, "init", "-q", "-b", "main")
    (racine / ".gitignore").write_text("rapports/\n__pycache__/\n")
    (racine / "requirements.txt").write_text("requests\n")
    (racine / "a.txt").write_text("a\n")
    git(racine, "add", ".")
    git(racine, "commit", "-q", "-m", "un")
    return racine


@pytest.fixture
def sans_verrou():
    return lambda: None


def commande_compteur(racine, code=0):
    """Commande factice : ajoute une ligne à `appels` puis sort avec `code`."""
    script = f"open({str(racine.parent / 'appels')!r}, 'a').write('x\\n'); raise SystemExit({code})"
    return [[sys.executable, "-c", script]]


def appels(racine):
    f = racine.parent / "appels"
    return len(f.read_text().splitlines()) if f.exists() else 0


def test_cle_stable_apres_rebase_sans_changement(depot):
    avant = verifier.cle_arbre(depot)
    git(depot, "commit", "-q", "--amend", "-m", "message réécrit")
    git(depot, "commit", "-q", "--allow-empty", "-m", "commit vide")
    assert verifier.cle_arbre(depot) == avant


def test_cle_change_avec_un_fichier_suivi_modifie(depot):
    propre = verifier.cle_arbre(depot)
    (depot / "a.txt").write_text("modifié\n")
    sale = verifier.cle_arbre(depot)
    assert sale != propre
    git(depot, "add", "a.txt")  # indexé : même contenu, même clé
    assert verifier.cle_arbre(depot) == sale
    git(depot, "commit", "-q", "-m", "deux")  # commité : l'arbre porte le contenu
    assert verifier.cle_arbre(depot).split(":")[0] != propre.split(":")[0]


def test_cle_change_avec_un_fichier_non_suivi_mais_pas_un_ignore(depot):
    propre = verifier.cle_arbre(depot)
    (depot / "rapports").mkdir()
    (depot / "rapports" / "r.md").write_text("ignoré\n")
    (depot / ".tmp-verify").mkdir()
    (depot / ".tmp-verify" / "sortie.json").write_text("{}")
    assert verifier.cle_arbre(depot) == propre
    (depot / "nouveau.py").write_text("x = 1\n")
    avec = verifier.cle_arbre(depot)
    assert avec != propre
    (depot / "nouveau.py").write_text("x = 2\n")
    assert verifier.cle_arbre(depot) != avec


def test_succes_reutilise_sans_relancer_les_commandes(depot, tmp_path, sans_verrou):
    registre = tmp_path / "registre.json"
    cmds = commande_compteur(depot)
    premier = verifier.verifier(depot, registre, cmds, verrou=sans_verrou)
    second = verifier.verifier(depot, registre, cmds, verrou=sans_verrou)
    assert premier["ok"] and not premier["reutilise"]
    assert second["ok"] and second["reutilise"]
    assert appels(depot) == 1
    assert second["total_secondes"] < 1


def test_resultat_reutilise_apres_rebase(depot, tmp_path, sans_verrou):
    registre = tmp_path / "registre.json"
    cmds = commande_compteur(depot)
    verifier.verifier(depot, registre, cmds, verrou=sans_verrou)
    git(depot, "commit", "-q", "--amend", "-m", "autre message")
    assert verifier.verifier(depot, registre, cmds, verrou=sans_verrou)["reutilise"]
    assert appels(depot) == 1


def test_echec_jamais_reutilise(depot, tmp_path, sans_verrou):
    registre = tmp_path / "registre.json"
    cmds = commande_compteur(depot, code=1)
    assert not verifier.verifier(depot, registre, cmds, verrou=sans_verrou)["ok"]
    assert not registre.exists() or verifier.cle_arbre(depot) not in json.loads(registre.read_text())
    rapport = verifier.verifier(depot, registre, cmds, verrou=sans_verrou)
    assert not rapport["ok"] and not rapport["reutilise"]
    assert appels(depot) == 2


def test_une_commande_en_echec_arrete_la_suite(depot):
    rapport = verifier.lancer([*commande_compteur(depot, code=3), *commande_compteur(depot)], depot)
    assert not rapport["ok"] and len(rapport["commandes"]) == 1 and rapport["commandes"][0]["code"] == 3


def test_environnement_change_relance(depot, tmp_path, sans_verrou, monkeypatch):
    registre = tmp_path / "registre.json"
    cmds = commande_compteur(depot)
    verifier.verifier(depot, registre, cmds, verrou=sans_verrou)
    reel = verifier.signature
    monkeypatch.setattr(verifier, "signature", lambda racine=depot: {**reel(racine), "paquets": "autre"})
    rapport = verifier.verifier(depot, registre, cmds, verrou=sans_verrou)
    assert not rapport["reutilise"] and appels(depot) == 2


def test_signature_depend_de_requirements(depot):
    avant = verifier.signature(depot)
    (depot / "requirements.txt").write_text("requests\nPyYAML\n")
    assert verifier.signature(depot)["requirements"] != avant["requirements"]


def test_contenu_modifie_pendant_les_tests_non_enregistre(depot, tmp_path, sans_verrou):
    registre = tmp_path / "registre.json"
    script = f"open({str(depot / 'a.txt')!r}, 'a').write('bouge\\n')"
    rapport = verifier.verifier(depot, registre, [[sys.executable, "-c", script]], verrou=sans_verrou)
    assert rapport["ok"] and not registre.exists()


def test_sans_cache_force_une_nouvelle_execution(depot, tmp_path, sans_verrou):
    registre = tmp_path / "registre.json"
    cmds = commande_compteur(depot)
    verifier.verifier(depot, registre, cmds, verrou=sans_verrou)
    assert not verifier.verifier(depot, registre, cmds, sans_cache=True, verrou=sans_verrou)["reutilise"]
    assert appels(depot) == 2


@pytest.mark.parametrize("contenu", ["", "pas du json", "[]", '{"cle": 3}'])
def test_registre_illisible_ne_prouve_rien(depot, tmp_path, sans_verrou, contenu):
    registre = tmp_path / "registre.json"
    registre.write_text(contenu)
    assert not verifier.verifier(depot, registre, commande_compteur(depot), verrou=sans_verrou)["reutilise"]
    assert verifier.lire_registre(registre)  # remplacé par un registre valide


def test_deux_succes_de_worktrees_distincts_se_conservent(depot, tmp_path):
    registre = tmp_path / "registre.json"
    verifier.sauver(registre, "arbre1:x", {"e": 1}, {"ok": True})
    verifier.sauver(registre, "arbre2:y", {"e": 1}, {"ok": True})
    verifier.sauver(registre, "arbre3:z", {"e": 1}, {"ok": False})
    assert set(json.loads(registre.read_text())) == {"arbre1:x", "arbre2:y"}


def test_commandes_pytest_puis_les_trois_perimetres():
    cmds = verifier.commandes("py")
    assert cmds[0] == ["py", "-m", "pytest", "-q"]
    assert [c[-1] for c in cmds[1:]] == ["claude", "openai", "actu"]
    assert all(c[1:3] == ["scripts/valider.py", "--perimetre"] for c in cmds[1:])


@pytest.fixture
def verrous(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier.os, "nice", lambda n: 0)
    monkeypatch.setenv("VERIFY_VERROU_TENU", "")  # enregistre l'état pour la restauration : verrou_machine écrit os.environ
    monkeypatch.delenv("VERIFY_VERROU_TENU")
    return tmp_path / "verrous"


def test_verrou_machine_prend_la_seconde_place_si_la_premiere_est_tenue(verrous):
    verrous.mkdir()
    premiere = (verrous / verifier.VERROUS[0]).open("a")
    fcntl.flock(premiere, fcntl.LOCK_EX)
    try:
        tenu = verifier.verrou_machine(verrous)
        assert tenu is not None and tenu.name.endswith(verifier.VERROUS[1])
    finally:
        premiere.close()


def test_verrou_machine_herite_ne_reprend_pas_le_verrou(verrous, monkeypatch):
    monkeypatch.setenv("VERIFY_VERROU_TENU", "1")
    assert verifier.verrou_machine(verrous) is None
    assert not verrous.exists()

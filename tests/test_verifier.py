"""D87 : scripts/verifier.py réutilise un résultat par arbre ; commandes factices, registre et verrous dans tmp_path."""

from __future__ import annotations

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
    git(depot, "commit", "-q", "-m", "deux")  # commité : même contenu, même clé
    assert verifier.cle_arbre(depot) == sale
    (depot / "a.txt").unlink()  # une suppression change aussi la clé
    assert verifier.cle_arbre(depot) not in (propre, sale)


def test_cle_propre_est_l_arbre_de_head(depot):
    arbre = subprocess.run(["git", "-C", str(depot), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True).stdout.strip()
    assert verifier.cle_arbre(depot) == arbre


def test_cle_ne_touche_pas_a_l_index_reel(depot):
    (depot / "nouveau.py").write_text("x = 1\n")
    verifier.cle_arbre(depot)
    statut = subprocess.run(["git", "-C", str(depot), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert statut.strip() == "?? nouveau.py"


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
def lanceur(tmp_path, monkeypatch):
    """Faux `verrou-tests` : note ses arguments (un appel par ligne) puis sort avec le code demandé (défaut 0)."""
    monkeypatch.delenv("VERIFY_VERROU_TENU", raising=False)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    script = bin_ / "verrou-tests"
    script.write_text(f'#!/bin/sh\necho "$*" >> {tmp_path / "prises"}\nexit "${{FAUX_CODE:-0}}"\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    return tmp_path / "prises"


def test_verrou_commun_relance_sous_verrou_tests(lanceur, tmp_path):
    with pytest.raises(SystemExit) as sortie:
        verifier.verrou_commun(["--cible", "--base", "main"], tmp_path)
    assert sortie.value.code == 0
    prise, = lanceur.read_text().splitlines()
    assert prise == (f"--depot {tmp_path} --nom delta-ia -- {sys.executable} {verifier.__file__} --cible --base main")


def test_verrou_commun_herite_ne_reprend_pas_le_verrou(lanceur, monkeypatch):
    monkeypatch.setenv("VERIFY_VERROU_TENU", "1")
    assert verifier.verrou_commun(["--local"]) is None
    assert not lanceur.exists()


@pytest.mark.parametrize("code", [1, 75])
def test_verrou_commun_rend_le_code_tel_quel(lanceur, monkeypatch, capsys, code):
    monkeypatch.setenv("FAUX_CODE", str(code))
    with pytest.raises(SystemExit) as sortie:
        verifier.verrou_commun([])
    assert sortie.value.code == code
    assert ("file du verrou commun pleine" in capsys.readouterr().out) is (code == 75)


def test_verrou_commun_sans_lanceur_ne_contourne_pas(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("VERIFY_VERROU_TENU", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(verifier, "LANCEUR_DEFAUT", tmp_path / "absent" / "verrou-tests")
    with pytest.raises(SystemExit) as sortie:
        verifier.verrou_commun([])
    assert sortie.value.code == 127
    assert "aucun verrou local de rechange" in capsys.readouterr().out


def test_verrou_commun_essaie_local_bin_quand_le_path_ne_le_trouve_pas(lanceur, monkeypatch, tmp_path):
    """PATH sans ~/.local/bin (systemd, cron) : le lanceur de ~/.local/bin sert avant le code 127."""
    maison = tmp_path / "maison"
    (maison / ".local" / "bin").mkdir(parents=True)
    (tmp_path / "bin" / "verrou-tests").rename(maison / ".local" / "bin" / "verrou-tests")
    monkeypatch.setattr(verifier, "LANCEUR_DEFAUT", maison / ".local" / "bin" / "verrou-tests")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    with pytest.raises(SystemExit) as sortie:
        verifier.verrou_commun(["--local"], tmp_path)
    assert sortie.value.code == 0
    assert lanceur.read_text().startswith(f"--depot {tmp_path} --nom delta-ia -- ")


@pytest.fixture
def prises(monkeypatch, depot):
    """Remplace la relance par un compteur : combien de fois chaque exécution demande le verrou."""
    monkeypatch.setattr(verifier, "RACINE", depot)
    monkeypatch.setattr(verifier, "lancer", lambda *a, **k: {"ok": True, "commandes": [{"cmd": "x", "code": 0, "secondes": 0.1}]})
    appels_ = []
    monkeypatch.setattr(verifier, "verrou_commun", lambda argv, racine=None: appels_.append(list(argv)))
    return appels_


def preparer_cible(depot):
    git(depot, "update-ref", "refs/remotes/origin/main", "HEAD")
    (depot / "scripts").mkdir()
    (depot / "tests").mkdir()
    (depot / "scripts" / "outil.py").write_text("x = 1\n")
    (depot / "tests" / "test_outil.py").write_text("import outil\n")


@pytest.mark.parametrize("argv", [["--local"], ["--cible"], ["tests/test_x.py"], ["--sans-cache", "--registre", "{reg}"]])
def test_une_seule_prise_par_execution(prises, depot, tmp_path, argv):
    preparer_cible(depot)
    argv = [a.replace("{reg}", str(tmp_path / "reg.json")) for a in argv]
    verifier.main(argv)
    assert prises == [argv]


def test_resultat_reutilise_n_attend_aucun_verrou(prises, depot, tmp_path):
    reg = ["--registre", str(tmp_path / "reg.json")]
    verifier.main(reg)
    assert len(prises) == 1
    verifier.main(reg)  # même arbre, même environnement : réutilisé
    assert len(prises) == 1


def test_cible_liste_ou_sans_test_ne_prend_pas_le_verrou(prises, depot):
    preparer_cible(depot)
    verifier.main(["--cible", "--liste"])
    assert prises == []


# --- D94 : vérification ciblée, preuve CI du hash exact, tests marqués `local` ---------------------------------------

def test_fichiers_touches_depuis_l_ancetre_commun(depot):
    git(depot, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(depot, "checkout", "-q", "-b", "operer/x")
    (depot / "b.txt").write_text("b\n")
    git(depot, "add", "b.txt")
    git(depot, "commit", "-q", "-m", "deux")
    (depot / "a.txt").write_text("modifié\n")  # non commité
    (depot / "c.py").write_text("x = 1\n")  # non suivi
    (depot / ".tmp-verify").mkdir()
    (depot / ".tmp-verify" / "s.json").write_text("{}")  # sortie locale : ignorée
    assert verifier.fichiers_touches(depot, "origin/main") == ["a.txt", "b.txt", "c.py"]
    # main avance de son côté : ce qu'il a reçu n'est pas un changement de la branche
    git(depot, "checkout", "-q", "main")
    (depot / "d.txt").write_text("d\n")
    git(depot, "add", "d.txt")
    git(depot, "commit", "-q", "-m", "trois")
    git(depot, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(depot, "checkout", "-q", "operer/x")
    assert "d.txt" not in verifier.fichiers_touches(depot, "origin/main")


def test_commandes_cible_jamais_la_suite_complete():
    cmds = verifier.commandes_cible({"tests": ["tests/test_a.py", "tests/test_b.py"], "valider": False}, "py")
    assert cmds == [["py", "-m", "pytest", "-q", "tests/test_a.py", "tests/test_b.py"]]
    avec = verifier.commandes_cible({"tests": ["tests/test_a.py"], "valider": True}, "py")
    assert [c[-1] for c in avec[1:]] == ["claude", "openai", "actu"]
    # aucun test désigné : pas de « pytest -q » nu, qui lancerait toute la suite
    assert verifier.commandes_cible({"tests": [], "valider": False}, "py") == []
    sans_tests = verifier.commandes_cible({"tests": [], "valider": True}, "py")
    assert all("pytest" not in c for c in sans_tests)


SHA = "a" * 40


@pytest.mark.parametrize("runs, ok, extrait", [
    ([{"headSha": SHA, "conclusion": "success", "status": "completed"}], True, "CI verte"),
    ([{"headSha": "b" * 40, "conclusion": "success", "status": "completed"}], False, "aucun run CI"),  # autre commit
    ([], False, "aucun run CI"),
    ([{"headSha": SHA, "conclusion": "", "status": "in_progress"}], False, "en cours"),
    ([{"headSha": SHA, "conclusion": "failure", "status": "completed"}], False, "non verte"),
    ([{"headSha": SHA, "conclusion": "failure", "status": "completed"},
      {"headSha": SHA, "conclusion": "success", "status": "completed"}], True, "CI verte"),  # relance verte
    ([{"headSha": SHA, "conclusion": "success", "status": "completed"}, {"headSha": "c" * 40, "conclusion": "failure", "status": "completed"}], True, "CI verte"),
])
def test_preuve_ci_exige_le_hash_exact(runs, ok, extrait):
    assert verifier.preuve_ci("operer/x", SHA, runs)[1].count(extrait) == 1
    assert verifier.preuve_ci("operer/x", SHA, runs)[0] is ok


def test_preuve_ci_non_verte_nomme_le_repli():
    message = verifier.preuve_ci("operer/x", SHA, [])[1]
    assert "repli : suite complète locale" in message


def test_main_ci_code_de_sortie(depot, monkeypatch, capsys):
    sha = subprocess.run(["git", "-C", str(depot), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(verifier, "RACINE", depot)
    monkeypatch.setattr(verifier, "lire_runs_ci", lambda branche, racine=depot: [{"headSha": sha, "conclusion": "success", "status": "completed"}])
    assert verifier.main(["--ci", "main"]) == 0
    monkeypatch.setattr(verifier, "lire_runs_ci", lambda branche, racine=depot: [])
    assert verifier.main(["--ci", "main"]) == 1
    assert "NON EXPLOITABLE" in capsys.readouterr().out

    def illisible(branche, racine=depot):
        raise OSError("gh absent")
    monkeypatch.setattr(verifier, "lire_runs_ci", illisible)
    assert verifier.main(["--ci", "main"]) == 1  # repli, jamais un succès par défaut


def test_ci_resout_une_branche_qui_n_existe_que_sur_origin(depot, tmp_path, monkeypatch, capsys):
    """Branche poussée par une autre session : `refs/remotes/origin/<nom>` seul, pas de branche locale."""
    def git_(*a):
        return subprocess.run(["git", "-C", str(depot), *a], check=True, capture_output=True, text=True).stdout.strip()
    sha = git_("rev-parse", "HEAD")
    git_("update-ref", "refs/remotes/origin/operer/x-r2", sha)
    assert verifier.hash_branche("operer/x-r2", depot) == sha
    monkeypatch.setattr(verifier, "RACINE", depot)
    monkeypatch.setattr(verifier, "lire_runs_ci", lambda branche, racine=depot: [{"headSha": sha, "conclusion": "success", "status": "completed"}])
    assert verifier.main(["--ci", "operer/x-r2"]) == 0
    assert "CI verte" in capsys.readouterr().out
    git_("update-ref", "refs/heads/operer/x-r2", git_("rev-parse", "HEAD~0"))  # la locale prime quand elle existe
    assert verifier.hash_branche("operer/x-r2", depot) == sha


def test_ci_branche_introuvable_est_un_repli_pas_un_succes(depot, monkeypatch, capsys):
    monkeypatch.setattr(verifier, "RACINE", depot)
    monkeypatch.setattr(verifier, "lire_runs_ci", lambda branche, racine=depot: [])
    with pytest.raises(ValueError, match="introuvable"):
        verifier.hash_branche("operer/fantome", depot)
    assert verifier.main(["--ci", "operer/fantome"]) == 1
    assert "introuvable" in capsys.readouterr().out


def test_lancer_tolere_le_code_5_seulement_si_demande(depot):
    cmd = [[sys.executable, "-c", "raise SystemExit(5)"]]
    assert not verifier.lancer(cmd, depot)["ok"]
    assert verifier.lancer(cmd, depot, codes_ok=(0, 5))["ok"]
    assert not verifier.lancer([[sys.executable, "-c", "raise SystemExit(1)"]], depot, codes_ok=(0, 5))["ok"]


def test_commandes_local_vise_le_marqueur_local():
    assert verifier.commandes_local("py") == [["py", "-m", "pytest", "-q", "-m", "local"]]


def test_main_cible_liste_n_execute_rien(depot, monkeypatch, capsys):
    git(depot, "update-ref", "refs/remotes/origin/main", "HEAD")
    (depot / "scripts").mkdir()
    (depot / "tests").mkdir()
    (depot / "scripts" / "outil.py").write_text("x = 1\n")
    (depot / "tests" / "test_outil.py").write_text("import outil\n")
    monkeypatch.setattr(verifier, "RACINE", depot)
    monkeypatch.setattr(verifier, "lancer", lambda *a, **k: pytest.fail("--liste ne lance rien"))
    assert verifier.main(["--cible", "--liste"]) == 0
    sortie = capsys.readouterr().out
    assert "1 test(s)" in sortie and "scripts/outil.py" in sortie

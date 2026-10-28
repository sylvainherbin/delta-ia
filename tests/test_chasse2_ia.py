"""Missions 92 et 97 : témoins des défauts présents sur 5a66288 et de leur correction.

Tout est exécuté sur des copies sous tmp_path. Lancer avec --basetemp dans
le worktree ; aucun service, collecteur, réseau ou vrai modèle n'est appelé.
"""

import json
import os
import stat
import subprocess
import time
from datetime import date, datetime, timezone

import pytest

import orchestrateur as orc
from conftest import RACINE


JOUR = date(2026, 10, 28)
INSTANT = datetime(2026, 10, 28, 16, 50, tzinfo=timezone.utc)
RESULTAT = (
    "# Supervision du passage\n\n"
    "Les étapes ont été examinées et les résultats attendus sont présents. "
    "Le dépôt est propre, les journaux sont lisibles et aucune intervention "
    "supplémentaire ne reste à effectuer."
)
SORTIE = json.dumps({"subtype": "success", "is_error": False, "result": RESULTAT})


@pytest.fixture
def horloge(monkeypatch):
    class DateFixe(datetime):
        @classmethod
        def now(cls, tz=None):
            return INSTANT.astimezone(tz)

    # Seule l'horloge est remplacée ; l'écriture et son contrôle restent réels.
    monkeypatch.setattr(orc, "datetime", DateFixe)
    return f"{JOUR}_{INSTANT.astimezone():%H%M}-supervision.md"


def test_chasse2_supervision_ecrit_un_rapport_ordinaire(tmp_path, horloge):
    debut = time.time()
    assert orc.enregistrer_rapport_supervision(tmp_path, JOUR, debut, SORTIE)
    assert (tmp_path / "rapports" / horloge).read_text() == RESULTAT + "\n"
    assert orc.rapport_supervision_ecrit(tmp_path, JOUR, debut)


@pytest.mark.parametrize("lien", ["fichier", "dossier"])
def test_chasse2_supervision_necrase_pas_une_cible_hors_racine(tmp_path, horloge, lien):
    racine = tmp_path / "copie"
    ailleurs = tmp_path / "autre-copie"
    racine.mkdir()
    ailleurs.mkdir()
    cible = ailleurs / horloge
    contenu = "FICHIER VOISIN À CONSERVER\n"
    cible.write_text(contenu)
    os.utime(cible, (1, 1))
    if lien == "dossier":
        (racine / "rapports").symlink_to(ailleurs, target_is_directory=True)
    else:
        (racine / "rapports").mkdir()
        (racine / "rapports" / horloge).symlink_to(cible)

    debut = time.time()
    assert not orc.rapport_supervision_ecrit(racine, JOUR, debut)
    orc.enregistrer_rapport_supervision(racine, JOUR, debut, SORTIE)
    # L'ancienne cible ne doit jamais être tronquée, même si un nouveau rapport
    # est créé de façon sûre à sa place. Les deux copies sont dans le worktree.
    assert cible.read_text() == contenu, "le repli a écrasé un fichier hors de sa racine"


@pytest.mark.parametrize("composant", ["racine", "ancetre", "rapports", "fichier"])
def test_supervision_refuse_aussi_les_liens_vers_un_rapport_frais(tmp_path, horloge, composant):
    debut = time.time() - 1
    ailleurs = tmp_path / "ailleurs"
    (ailleurs / "rapports").mkdir(parents=True)
    cible = ailleurs / "rapports" / horloge
    cible.write_text(RESULTAT)
    cible.chmod(0o640)
    avant = cible.stat()
    racine = tmp_path / "racine"
    if composant == "racine":
        racine.symlink_to(ailleurs, target_is_directory=True)
    elif composant == "ancetre":
        racine.symlink_to(tmp_path, target_is_directory=True)
        racine = racine / "ailleurs"
    else:
        racine.mkdir()
        if composant == "rapports":
            (racine / "rapports").symlink_to(ailleurs / "rapports", target_is_directory=True)
        else:
            (racine / "rapports").mkdir()
            (racine / "rapports" / horloge).symlink_to(cible)

    assert not orc.rapport_supervision_ecrit(racine, JOUR, debut)
    ecrit = orc.enregistrer_rapport_supervision(racine, JOUR, debut, SORTIE)
    assert ecrit is (composant == "fichier")
    assert cible.read_text() == RESULTAT
    apres = cible.stat()
    assert (apres.st_ino, apres.st_mode, apres.st_size, apres.st_mtime_ns, apres.st_ctime_ns) == (
        avant.st_ino, avant.st_mode, avant.st_size, avant.st_mtime_ns, avant.st_ctime_ns)


def test_supervision_remplace_un_lien_physique_sans_modifier_sa_cible(tmp_path, horloge):
    cible = tmp_path / "voisin.md"
    cible.write_text("voisin à conserver\n")
    cible.chmod(0o640)
    racine = tmp_path / "racine"
    (racine / "rapports").mkdir(parents=True)
    rapport = racine / "rapports" / horloge
    os.link(cible, rapport)

    assert orc.enregistrer_rapport_supervision(racine, JOUR, time.time() - 1, SORTIE)
    assert cible.read_text() == "voisin à conserver\n"
    assert stat.S_IMODE(cible.stat().st_mode) == 0o640
    assert rapport.stat().st_ino != cible.stat().st_ino
    assert rapport.read_text() == RESULTAT + "\n"


def test_supervision_parent_remplace_par_un_lien_pendant_la_creation(tmp_path, horloge, monkeypatch):
    racine = tmp_path / "racine"
    rapports = racine / "rapports"
    rapports.mkdir(parents=True)
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    cible = ailleurs / horloge
    cible.write_text("voisin à conserver\n")
    ouvrir = os.open

    def substitution(nom, flags, *args, **kwargs):
        if str(nom).startswith(".supervision-"):
            rapports.rename(racine / "rapports-originaux")
            rapports.symlink_to(ailleurs, target_is_directory=True)
        return ouvrir(nom, flags, *args, **kwargs)

    monkeypatch.setattr(orc.os, "open", substitution)
    orc.enregistrer_rapport_supervision(racine, JOUR, time.time() - 1, SORTIE)
    assert cible.read_text() == "voisin à conserver\n"
    assert list(ailleurs.iterdir()) == [cible]
    assert not orc.rapport_supervision_ecrit(racine, JOUR, time.time() - 1)


def test_supervision_creation_exclusive_refuse_un_lien_temporaire(tmp_path, horloge, monkeypatch):
    rapports = tmp_path / "rapports"
    rapports.mkdir()
    cible = tmp_path / "voisin.md"
    cible.write_text("voisin à conserver\n")
    (rapports / ".supervision-connu.tmp").symlink_to(cible)
    monkeypatch.setattr(orc.secrets, "token_hex", lambda _: "connu")

    assert not orc.enregistrer_rapport_supervision(tmp_path, JOUR, time.time() - 1, SORTIE)
    assert cible.read_text() == "voisin à conserver\n"
    assert not (rapports / horloge).exists()


def test_supervision_echec_de_publication_conserve_ancien_rapport_et_nettoie_temporaire(tmp_path, horloge, monkeypatch):
    rapports = tmp_path / "rapports"
    rapports.mkdir()
    rapport = rapports / horloge
    rapport.write_text("ancien rapport\n")

    def echouer(*args, **kwargs):
        raise OSError("publication impossible")

    monkeypatch.setattr(orc.os, "replace", echouer)
    assert not orc.enregistrer_rapport_supervision(tmp_path, JOUR, time.time() - 1, SORTIE)
    assert rapport.read_text() == "ancien rapport\n"
    assert list(rapports.iterdir()) == [rapport]


@pytest.fixture
def fin_pont(tmp_path):
    script = (RACINE / "scripts/reglages-pont.sh").read_text(encoding="utf-8")
    fonction = "prevenir() {" + script.split("prevenir() {", 1)[1].split("\nechec()", 1)[0]
    fin = script[script.index('hash="$(git rev-parse --short HEAD)"'):]
    # La vraie fonction ET son véritable appel final sont exécutés ensemble.
    # Le collecteur et la création de worktree ne tournent pas : ils utilisent
    # des chemins machine et sont sans rapport avec le contrat de notification.
    depot = tmp_path / "depot"
    depot.mkdir()
    maison = tmp_path / "maison"
    maison.mkdir()
    env = {
        "PATH": os.defpath, "HOME": str(maison), "TMPDIR": str(tmp_path),
        "LC_ALL": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@exemple.test",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@exemple.test",
        "WT": str(depot), "BRANCHE": "reglages-pont/2026-10-28",
        "resume": "Un constat prêt pour relecture", "code": "0",
    }
    for args in (
        ["init", "-q", "-b", "copie-test"],
        ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
         "commit", "--allow-empty", "-qm", "copie de test"],
    ):
        subprocess.run(["git", *args], cwd=depot, env=env, check=True, capture_output=True, timeout=10)

    def lancer(boite, **variables):
        return subprocess.run(
            ["bash", "-uc", fonction + "\n" + fin], cwd=depot,
            env={**env, "DELTA_PONT_BOITE": str(boite), **variables},
            capture_output=True, text=True, timeout=10,
        )

    return lancer


def test_chasse2_pont_fin_depose_un_message_avant_de_reussir(fin_pont, tmp_path):
    boite = tmp_path / "boite"
    resultat = fin_pont(boite)
    assert resultat.returncode == 0, resultat.stderr
    messages = list(boite.glob("*-reglages-pont.md"))
    assert len(messages) == 1
    assert "Constats internes automatiques à relire" in messages[0].read_text()


def test_chasse2_pont_echec_de_notification_ne_rend_pas_succes(fin_pont, tmp_path):
    boite = tmp_path / "boite-inaccessible"
    boite.write_text("ce fichier empêche la création du dossier\n")
    resultat = fin_pont(boite)
    assert "mkdir:" in resultat.stderr, resultat.stderr
    assert not list(tmp_path.glob("**/*-reglages-pont.md"))
    assert resultat.returncode == 1, (
        f"notification impossible mais code {resultat.returncode}; "
        f"stdout={resultat.stdout!r}; stderr={resultat.stderr!r}"
    )


def test_pont_echec_de_synchronisation_ne_rend_pas_succes(fin_pont, tmp_path):
    faux_python = tmp_path / "python-en-echec"
    faux_python.write_text("#!/bin/sh\nexit 43\n")
    faux_python.chmod(0o755)
    boite = tmp_path / "boite"
    resultat = fin_pont(boite, PYTHON=str(faux_python))
    assert resultat.returncode == 1
    assert "notification en échec" in resultat.stderr
    assert "conservés" in resultat.stderr
    assert "notification mise en file" not in resultat.stdout
    assert not list(boite.iterdir())


@pytest.mark.parametrize("code", ["0", "3"])
def test_pont_conserve_le_code_collecteur_apres_notification_confirmee(fin_pont, tmp_path, code):
    boite = tmp_path / "boite"
    resultat = fin_pont(boite, code=code)
    assert resultat.returncode == int(code), resultat.stderr
    messages = list(boite.glob("*-reglages-pont.md"))
    assert len(messages) == 1
    assert str(messages[0]) in resultat.stdout


@pytest.mark.parametrize("code,nouveaux", [("3", "0"), ("0", "1")])
@pytest.mark.parametrize("notification_ok", [False, True])
def test_pont_sans_constat_notifie_avant_de_nettoyer(tmp_path, code, nouveaux, notification_ok):
    script = (RACINE / "scripts/reglages-pont.sh").read_text(encoding="utf-8")
    fonction = "prevenir() {" + script.split("prevenir() {", 1)[1].split("\nechec()", 1)[0]
    segment = script[script.index('if [ -z "$(git status --porcelain -- kb-modeles)" ]'):]
    # Le segment réel sort avant le catalogue et les tests. Les seules commandes Git
    # simulées représentent l'état inchangé et enregistrent les demandes de nettoyage.
    simulation = '''
git() {
    case "$1" in
        status) return 0 ;;
        rev-parse) echo 0123456789abcdef ;;
        -C) echo 0123456789abcdef ;;
        worktree|branch) echo "$*" >> "$NETTOYAGE" ;;
        *) return 99 ;;
    esac
}
'''
    boite = tmp_path / "boite"
    if not notification_ok:
        boite.write_text("dossier indisponible\n")
    nettoyage = tmp_path / "nettoyage"
    env = {"PATH": os.defpath, "HOME": str(tmp_path), "LC_ALL": "C.UTF-8",
           "DELTA_PONT_BOITE": str(boite), "WT": str(tmp_path / "worktree"),
           "RACINE": str(tmp_path), "BRANCHE": "reglages-pont/test", "resume": "constats inchangés",
           "code": code, "nouveaux": nouveaux, "NETTOYAGE": str(nettoyage)}
    resultat = subprocess.run(["bash", "-uc", simulation + fonction + "\n" + segment],
                              cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
    if notification_ok:
        assert resultat.returncode == int(code), resultat.stderr
        assert len(list(boite.glob("*-reglages-pont.md"))) == 1
        assert "worktree remove" in nettoyage.read_text()
    else:
        assert resultat.returncode == 1
        assert "notification en échec" in resultat.stderr
        assert "conservés" in resultat.stderr
        assert not nettoyage.exists()

"""Mission 92 : témoins des défauts présents sur 5a66288, sans correctif.

Tout est exécuté sur des copies sous tmp_path. Lancer avec --basetemp dans
le worktree ; aucun service, collecteur, réseau ou vrai modèle n'est appelé.
--runxfail permet de revoir les assertions rouges des défauts documentés.
"""

import json
import os
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


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M92-1 : le repli de supervision suit les liens du fichier et du dossier "
    "rapports, puis valide l'écriture hors de sa racine (f4960ae4)."
))
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

    def lancer(boite):
        return subprocess.run(
            ["bash", "-uc", fonction + "\n" + fin], cwd=depot,
            env={**env, "DELTA_PONT_BOITE": str(boite)},
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


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M92-2 : l'appel final ignore le code d'échec de prevenir, puis rend le "
    "code 0 du collecteur sans message déposé (35021aea)."
))
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

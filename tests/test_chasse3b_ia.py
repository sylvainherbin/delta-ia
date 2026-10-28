"""Mission 00q : régression des droits sur les ancêtres, introduite par 672dde53.

Contrats : scripts/orchestrateur.py (docstrings des deux fonctions) et
SPEC.md D70 : enregistrer un résultat valide et reconnaître le rapport frais.
Les ancêtres ne sont pas énumérés : leur droit de traversée suffit pour ces
opérations. Seul le dossier rapports doit être lisible par le contrôleur.
Vrais fichiers et vrais droits POSIX ; aucun remplacement du code ou des appels
système. Exécuter sous un utilisateur sans CAP_DAC_READ_SEARCH/OVERRIDE.
"""

import json
import os
import stat
import time
from contextlib import contextmanager
from datetime import date

import pytest

import orchestrateur as orc


JOUR = date(2026, 10, 28)
RAPPORT = "# Supervision\n\n" + (
    "Les étapes ont été relues et les résultats attendus sont présents. "
    "Les contrôles locaux sont terminés et le rapport est disponible."
)
SORTIE = json.dumps({"subtype": "success", "is_error": False, "result": RAPPORT})


class LectureAncetreImposee(AssertionError):
    """00q-F1 : O_RDONLY exige un droit inutile sur un ancêtre traversable."""


def modes_ancetre():
    return [
        pytest.param(0o711, id="ancetre-lisible"),
        pytest.param(
            0o111,
            id="ancetre-traversable",
            marks=pytest.mark.xfail(
                strict=True,
                raises=LectureAncetreImposee,
                reason="00q-F1 (672dde53) : ouverture O_RDONLY des ancêtres au lieu du seul droit de traversée",
            ),
        ),
    ]


@contextmanager
def ancetre_aux_droits(ancetre, mode):
    avant = stat.S_IMODE(ancetre.stat().st_mode)
    ancetre.chmod(mode)
    try:
        if mode == 0o111 and os.access(ancetre, os.R_OK):
            pytest.skip("cet utilisateur contourne les droits de lecture POSIX")
        assert os.access(ancetre, os.X_OK)
        assert stat.S_IMODE(ancetre.stat().st_mode) == mode
        yield
    finally:
        ancetre.chmod(avant)


@pytest.fixture
def arborescence(tmp_path):
    ancetre = tmp_path / "ancetre"
    racine = ancetre / "depot"
    rapports = racine / "rapports"
    rapports.mkdir(parents=True)
    # Aucun lien, y compris dans les parents de tmp_path ; tous les composants
    # à ouvrir après l'ancêtre restent lisibles, inscriptibles et traversables.
    assert not any(p.is_symlink() for p in (rapports, *rapports.parents))
    racine.chmod(0o700)
    rapports.chmod(0o700)
    return ancetre, racine, rapports


@pytest.mark.parametrize("mode", modes_ancetre())
def test_chasse3b_repli_ecrit_sous_un_ancetre_traversable(arborescence, mode):
    ancetre, racine, rapports = arborescence
    with ancetre_aux_droits(ancetre, mode):
        # Contrôle préalable indépendant : créer, lire et retirer un fichier
        # dans ce même dossier reste autorisé avec ces droits exacts.
        controle = rapports / "controle.md"
        controle.write_text(RAPPORT, encoding="utf-8")
        assert controle.read_text(encoding="utf-8") == RAPPORT
        controle.unlink()
        debut = time.time() - 1
        ecrit = orc.enregistrer_rapport_supervision(racine, JOUR, debut, SORTIE)
        if not ecrit:
            raise LectureAncetreImposee(
                f"00q-F1 : le repli refuse un résultat valide sous l'ancêtre {mode:o}, "
                "bien que la création réelle dans rapports soit autorisée"
            )
        fichiers = list(rapports.iterdir())
        assert len(fichiers) == 1
        assert fichiers[0].read_text(encoding="utf-8") == RAPPORT + "\n"
        assert fichiers[0].stat().st_mtime >= debut


@pytest.mark.parametrize("mode", modes_ancetre())
def test_chasse3b_reconnait_un_rapport_sous_un_ancetre_traversable(arborescence, mode):
    ancetre, racine, rapports = arborescence
    rapport = rapports / f"{JOUR}_1200-supervision.md"
    rapport.write_text(RAPPORT, encoding="utf-8")
    debut = rapport.stat().st_mtime - 1
    with ancetre_aux_droits(ancetre, mode):
        assert rapport.read_text(encoding="utf-8") == RAPPORT
        assert rapport.is_file() and rapport.stat().st_mtime >= debut
        assert list(rapports.iterdir()) == [rapport]
        reconnu = orc.rapport_supervision_ecrit(racine, JOUR, debut)
        if not reconnu:
            raise LectureAncetreImposee(
                f"00q-F1 : un rapport régulier, frais et lisible est déclaré absent "
                f"sous l'ancêtre {mode:o}"
            )

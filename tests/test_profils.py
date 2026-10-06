"""D82 : profils fictifs (camille, neutre) — la veille ne dépend pas du CONTEXTE.md de Sylvain. Sans LLM.

Les marques xfail « attend G1/G2/G3 » ont été retirées à l'intégration de G1 à G4 : ces tests doivent passer.
"""

from __future__ import annotations

import json
import re

import pytest

import contexte as contexte_cli
import valider
from conftest import FIXTURES_PROFILS, RACINE
from deltalib.contexte import analyser

CAMILLE = FIXTURES_PROFILS / "camille"
NEUTRE = FIXTURES_PROFILS / "neutre"
PROJETS_DE_SYLVAIN = ("carnet", "trading-sim", "chatgpt-trading-sim", "ceramist", "restoration-id")


def _projets_ctx(dossier) -> set[str]:
    """Projets = sections de niveau 3 de ctx-id `projet.<nom>` (cadre commun G1-G4)."""
    s, _ = analyser((dossier / "CONTEXTE.md").read_text(encoding="utf-8"))
    return {k.removeprefix("projet.") for k, v in s.items() if v["niveau"] == 3 and k.startswith("projet.")}


def test_fixtures_presentes():
    for f in ("CONTEXTE.md", "profil.yaml", "besoins.md"):
        assert (CAMILLE / f).is_file(), f
    assert (NEUTRE / "CONTEXTE.md").is_file()
    assert not (NEUTRE / "profil.yaml").exists(), "le profil neutre teste les valeurs par défaut"


def test_camille_contexte_analyse():
    s, deprecies = analyser((CAMILLE / "CONTEXTE.md").read_text(encoding="utf-8"))
    assert {"profil", "projet.vue-ensemble", "projet.atelier-resa", "projet.site-vitrine"} <= set(s)
    assert s["projet.vue-ensemble"]["niveau"] == 2 and s["projet.atelier-resa"]["niveau"] == 3
    assert deprecies == set()
    assert _projets_ctx(CAMILLE) == {"atelier-resa", "site-vitrine"}


def test_neutre_contexte_analyse():
    s, _ = analyser((NEUTRE / "CONTEXTE.md").read_text(encoding="utf-8"))
    assert set(s) == {"profil"}
    assert _projets_ctx(NEUTRE) == set()


@pytest.mark.parametrize("dossier, attendu", [(CAMILLE, {"profil", "projet.atelier-resa", "projet.site-vitrine"}), (NEUTRE, {"profil"})])
def test_contexte_py_liste_les_sections(dossier, attendu, capsys):
    assert contexte_cli.main(["--racine", str(dossier), "--json"]) == 0
    sections = json.loads(capsys.readouterr().out)["sections"]
    assert attendu <= set(sections)
    assert not any(c.startswith("projet.") and c.removeprefix("projet.") in PROJETS_DE_SYLVAIN for c in sections)


def test_besoins_camille():
    texte = (CAMILLE / "besoins.md").read_text(encoding="utf-8")
    assert re.findall(r"\*\*(B\d)\*\*", texte) == [f"B{i}" for i in range(1, 8)]


@pytest.mark.parametrize("dossier, attendu", [(CAMILLE, {"atelier-resa", "site-vitrine"}), (NEUTRE, set())])
def test_valider_reconnait_les_projets(dossier, attendu):
    assert valider.projets_du_contexte(dossier / "CONTEXTE.md") == attendu


def _valeur(profil, cle):
    return profil[cle] if isinstance(profil, dict) else getattr(profil, cle)


def test_profil_camille():
    from deltalib import profil
    p = profil.charger(CAMILLE / "profil.yaml")
    assert len(_valeur(p, "priorites")) == 3 and "atelier-resa" in _valeur(p, "priorites")[0]
    assert _valeur(p, "progression") is None
    assert _valeur(p, "releves_machine") is False


def test_profil_neutre_valeurs_par_defaut():
    from deltalib import profil
    p = profil.charger(NEUTRE / "profil.yaml")  # fichier absent : valeurs par défaut sûres
    assert _valeur(p, "priorites") == []
    assert _valeur(p, "progression") is None
    assert _valeur(p, "releves_machine") is False
    base = _valeur(p, "base")
    assert (base["exclure_systemes"] if isinstance(base, dict) else base.exclure_systemes) == ["windows", "macos"]


def _fichiers_skills():
    fichiers = [*RACINE.glob(".claude/skills/*/SKILL.md"), *RACINE.glob(".agents/skills/*/SKILL.md"),
                *RACINE.glob("prompts/codex-delta*.md")]
    assert fichiers
    return sorted(fichiers)


@pytest.mark.parametrize("fichier", _fichiers_skills(), ids=lambda f: str(f.relative_to(RACINE)))
def test_skills_sans_donnees_de_sylvain(fichier):
    texte = fichier.read_text(encoding="utf-8").lower()
    trouves = [m for m in (*PROJETS_DE_SYLVAIN, "tmux") if re.search(rf"(?<![\w-]){re.escape(m)}(?![\w-])", texte)]
    assert not trouves, f"{fichier.relative_to(RACINE)} contient en dur : {trouves}"

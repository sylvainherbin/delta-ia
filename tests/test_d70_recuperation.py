"""D129 : les six consignes restent cohérentes sur les reprises et la publication des lots."""

import pytest

from conftest import RACINE

TEXTES = (
    ".claude/skills/delta/SKILL.md", ".claude/skills/delta-kb/SKILL.md",
    ".agents/skills/delta/SKILL.md", ".agents/skills/delta-kb/SKILL.md",
    "prompts/codex-delta.md", "prompts/codex-delta-kb.md",
)


def section(texte, titre):
    return texte.split(titre + "\n", 1)[1].split("\n##", 1)[0]


def test_regle_de_reprise_identique_dans_les_six_copies():
    regles = [section((RACINE / f).read_text(), "### Erreurs récupérables et arrêts (D70, D129)") for f in TEXTES]
    assert len(set(regles)) == 1
    for attendu in ("au plus 2 nouvelles tentatives par commande", "section CONTEXTE absente", "ctx-id inconnu",
                    "fichier introuvable en lecture", "option mal formée", "texte cible déplacé", "`ecartes`",
                    "hors du périmètre", "en échec après correction", "garde, quota, conflit git",
                    "permission en écriture reste bloquant", "rapport D63", "nombre de tentatives", "133"):
        assert attendu in regles[0]


@pytest.mark.parametrize("fichier", TEXTES)
def test_pas_d_ancienne_regle_arret_general_ni_interdiction_de_rapport(fichier):
    texte = (RACINE / fichier).read_text()
    for obsolete in ("Toute erreur arrête", "toute erreur arrête", "Tu n'écris aucun rapport",
                     "Journal toujours, aucun rapport", "un commit `claude` déjà fait reste local"):
        assert obsolete not in texte


def test_procedure_fiche_refusee_et_publication_avant_lot_suivant():
    copies = [(RACINE / f).read_text() for f in TEXTES if "delta-kb" in f]
    assert len({section(t, "### Reprendre un lot refusé par appliquer (D129)") for t in copies}) == 1
    for texte in copies:
        for attendu in ("seulement son id du fichier de commentaires", "ne supprime jamais la fiche de la base",
                        "exemple_origine: null", '"exemple_origine": "source" | "compose"',
                        "corrigé toute origine `null` recopiée", "avant toute commande du lot suivant",
                        "écris son journal", "son rapport D63 si nécessaire", "Après une garde bloquante",
                        "Les logs `rapports/auto/` ne remplacent pas ce rapport"):
            assert attendu in texte
        assert "un seul push" not in texte.lower()


@pytest.mark.parametrize("skill", ["delta", "delta-kb"])
def test_corps_codex_identique_au_prompt(skill):
    texte = (RACINE / f".agents/skills/{skill}/SKILL.md").read_text()
    assert texte.split("---\n", 2)[2].lstrip("\n") == (RACINE / f"prompts/codex-{skill}.md").read_text()

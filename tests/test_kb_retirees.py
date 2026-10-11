"""D118 : une commande que la page des commandes liste encore avec une description « Removed … » est `retiree`.

Fixture réelle : `cc_commands_removed.md`, https://code.claude.com/docs/en/commands.md récupérée le 11/10/2026
(lignes `/pr-comments`, `/ultraplan`, `/vim`)."""

from pathlib import Path

import pytest

from conftest import RACINE
from deltalib.kb import catalogue as cat
from deltalib.kb.documentation import charger_documentation
from deltalib.kb.extracteurs import EXTRACTEURS
from deltalib.kb.modeles import EntreeExtraite

KB = Path(__file__).parent / "fixtures" / "kb"
RETIREES = {"claude-code-commandes-pr-comments", "claude-code-commandes-ultraplan", "claude-code-commandes-vim"}


@pytest.fixture
def extraites():
    doc = next(d for d in charger_documentation(RACINE / "sources.yaml") if d.id == "cc-commandes")
    return EXTRACTEURS[doc.extracteur](doc, {"page": (KB / "cc_commands_removed.md").read_text(encoding="utf-8")})


def test_extraction_marque_les_lignes_removed(extraites):
    assert {e.id for e in extraites if e.retiree} == RETIREES
    noms = {e.id: e for e in extraites}
    # « removed » au milieu d'une description ne retire rien
    assert "removed" in noms["claude-code-commandes-reload-skills"].description_source
    assert not noms["claude-code-commandes-reload-skills"].retiree and not noms["claude-code-commandes-rename"].retiree


def x(retiree, description="src"):
    return EntreeExtraite(produit="claude-code", categorie="commandes", nom="/vim", usage="/vim", description_source=description,
                          url="https://code.claude.com/docs/en/commands", libelle="commands", origine="cc-commandes",
                          retiree=retiree)


def test_fusion_retire_une_entree_dite_removed():
    k = "claude-code-commandes-vim"
    ent, m = cat.fusionner({}, [x(False)], {"cc-commandes"}, jour="2026-10-10")
    assert ent[k]["retiree"] is False
    ent, m = cat.fusionner(ent, [x(True, "Removed in v2.1.92.")], {"cc-commandes"}, jour="2026-10-11")
    assert ent[k]["retiree"] is True and m["retirees"] == [k] and m["reapparues"] == []
    assert ent[k]["historique"][-1] == {"date": "2026-10-11", "changement": "retirée dans la documentation"}
    assert ent[k]["description_source"] == "Removed in v2.1.92."
    # nouvel extrait identique : rien ne change, pas de second historique
    n = len(ent[k]["historique"])
    ent, m = cat.fusionner(ent, [x(True, "Removed in v2.1.92.")], {"cc-commandes"}, jour="2026-10-12")
    assert not any(m.values()) and len(ent[k]["historique"]) == n
    # absente ensuite : reste retirée, sans nouvel historique
    ent, m = cat.fusionner(ent, [], {"cc-commandes"}, jour="2026-10-13")
    assert m["retirees"] == [] and ent[k]["retiree"] is True
    # de nouveau décrite sans « Removed » : réapparue
    ent, m = cat.fusionner(ent, [x(False, "Toggle Vim mode.")], {"cc-commandes"}, jour="2026-10-14")
    assert m["reapparues"] == [k] and ent[k]["retiree"] is False


def test_fusion_nouvelle_entree_deja_removed():
    ent, m = cat.fusionner({}, [x(True, "Removed.")], {"cc-commandes"}, jour="2026-10-11")
    assert ent["claude-code-commandes-vim"]["retiree"] is True and m["ajoutees"] == ["claude-code-commandes-vim"]


def test_base_reelle_les_trois_commandes_sortent(extraites):
    existantes = cat.charger(RACINE, "claude")
    for k in RETIREES:  # état d'avant D118, quel que soit le dernier passage
        existantes[k]["retiree"] = False
    ent, m = cat.fusionner(existantes, extraites, {"cc-commandes"}, jour="2026-10-11")
    assert RETIREES <= set(m["retirees"]) and all(ent[k]["retiree"] is True for k in RETIREES)
    assert not RETIREES & {i for ids in cat.construire_noms(list(ent.values())).values() for i in ids}

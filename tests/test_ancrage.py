"""D101 : ancrage des `pour_toi` dans CONTEXTE.md (REGLES §4) — termes tirés du fichier, avertissement sans effet sur le code de sortie.

Profil fictif camille (D82) : aucune valeur propre à Sylvain dans le code éprouvé.
"""

import copy

import pytest

import valider as v
from conftest import FIXTURES_PROFILS, element_depuis_brut, ecrire_quotidien
from deltalib.contexte import ContexteInvalide, normaliser_ancrage, resoudre, termes_ancrage, termes_nommes

CAMILLE_TXT = (FIXTURES_PROFILS / "camille" / "CONTEXTE.md").read_text(encoding="utf-8")
CAMILLE = termes_ancrage(CAMILLE_TXT)
JOUR = "2026-10-04"  # après le 24/09 (D64) : le contrôle d'ancrage s'applique


def test_termes_projets_et_sections_de_camille():
    assert CAMILLE["projets"] == {"atelier resa", "site vitrine", "vue ensemble"}
    assert {"atelier resa", "postgresql", "github actions"} <= CAMILLE["sections"]["projet.atelier-resa"]
    assert {"astro", "site vitrine"} <= CAMILLE["sections"]["projet.site-vitrine"]
    assert {"claude code", "configuration claude code"} <= CAMILLE["sections"]["config.claude-code"]
    assert {"macbook", "macos"} <= CAMILLE["sections"]["env.machine"]


def test_termes_sans_etiquettes_de_gabarit_ni_sujets_de_la_veille():
    tous = set().union(*CAMILLE["sections"].values())
    assert not tous & {"stack", "revue", "objectif", "etat", "codex", "claude", "chatgpt"}


def test_termes_codes_en_dur_absents_un_autre_contexte_donne_d_autres_termes():
    t = termes_ancrage("# T\n<!-- ctx-id: profil -->\n\n## Atelier\n<!-- ctx-id: outils.bois -->\n\n"
                       "| Outil | Valeur |\n|---|---|\n| Rabot Lamello | `rabot --lame 3` ; voir `docs/data/plans.json` |\n\n"
                       "Mon atelier compte une Ponceuse Festool et **fraiseuse CNC**.\n")
    assert {"rabot", "rabot lamello", "plans json", "ponceuse festool", "fraiseuse cnc", "bois"} <= t["sections"]["outils.bois"]
    assert t["projets"] == set()
    assert not ({"data", "docs", "valeur", "outil"} & t["sections"]["outils.bois"])


def test_termes_structure_invalide_propagee():
    with pytest.raises(ContexteInvalide):
        termes_ancrage("# T\n\nsans ctx-id\n")


def test_normalisation_sans_casse_ni_accents():
    assert normaliser_ancrage("Hébergement  Atelier-Resa_2") == "hebergement atelier resa 2"


@pytest.mark.parametrize("pour_toi, cites, attendu", [
    ("Ton projet Atelier-Resa livre vendredi.", [], ["atelier resa"]),
    ("TON SITE-VITRINE est en ASTRO.", ["projet.site-vitrine"], ["astro", "site vitrine"]),
    ("Ta stack PostgreSQL passe par github actions.", ["projet.atelier-resa"], ["github", "github actions", "postgresql"]),
    ("Tu travailles sur MacBook.", ["env.machine"], ["macbook"]),
    ("Rien de nommé ici.", ["projet.atelier-resa"], []),
    ("Netlify seulement, mais la section citée est autre.", ["config.codex"], []),
    ("Un atelier-resatruc et un postgresqlx ne comptent pas.", ["projet.atelier-resa"], []),
    ("Section citée inconnue.", ["projet.inconnu"], []),
], ids=["projet-sans-section", "casse-et-accents", "plusieurs-termes", "outil-de-section", "aucun", "autre-section",
        "mots-entiers", "ctx-id-inconnu"])
def test_termes_nommes(pour_toi, cites, attendu):
    assert termes_nommes(pour_toi, CAMILLE, cites) == attendu


def _avert(**champs):
    e = element_depuis_brut({"id": "fx-1", "produit": "claude-code", "titre": "Commande /foo", "version": None,
                             "date_publication": None, "url": "https://example.org/x", "officielle": True}, impact="faible")
    e.update(champs)
    r = v.Rapport()
    v.avertir_element(e, 0, r, "x.json", CAMILLE)
    return [a for a in r.avertissements if "ancrage" in a]


def test_avertit_quand_aucun_terme_n_est_nomme():
    avert = _avert(pour_toi="Ça peut servir un jour.", contexte_sections={"projet.atelier-resa": {}})
    assert avert == [f"x.json elements[0] (fx-1): {v.MESSAGE_ANCRAGE}"]
    assert "sans projet, outil ni habitude nommés de CONTEXTE.md" in avert[0]


def test_pas_d_avertissement_quand_un_terme_est_nomme():
    assert _avert(pour_toi="Utile pour atelier-resa.", contexte_sections={"projet.atelier-resa": {}}) == []
    assert _avert(pour_toi="Tu as Claude Code sur ce poste.", contexte_sections={"config.claude-code": {}}) == []


@pytest.mark.parametrize("champs", [{"contexte_sections": {}}, {"contexte_sections": None}, {"__absent": True}],
                         ids=["vide", "null", "absent"])
def test_contexte_sections_vide_ou_absent_avertit_meme_si_un_projet_est_nomme(champs):
    e = {"pour_toi": "Utile pour atelier-resa.", **champs}
    if e.pop("__absent", False):
        r = v.Rapport()
        el = element_depuis_brut({"id": "fx-1", "produit": "claude-code", "titre": "t", "version": None,
                                  "date_publication": None, "url": "https://example.org/x", "officielle": True})
        el.pop("contexte_sections"); el["pour_toi"] = e["pour_toi"]
        v.avertir_element(el, 0, r, "x.json", CAMILLE)
        assert [a for a in r.avertissements if "ancrage" in a]
    else:
        assert len(_avert(**e)) == 1


@pytest.mark.parametrize("champs", [{"pour_toi": None}, {"pour_toi": ""}, {"pour_toi": "   "}, {"impact": "nul", "pour_toi": None}],
                         ids=["null", "vide", "blanc", "impact-nul"])
def test_pas_d_avertissement_sans_pour_toi_ou_impact_nul(champs):
    assert _avert(contexte_sections={}, **champs) == []


def test_sans_ancrage_aucun_controle():
    e = element_depuis_brut({"id": "fx-1", "produit": "claude-code", "titre": "t", "version": None, "date_publication": None,
                             "url": "https://example.org/x", "officielle": True})
    e["pour_toi"] = "Ça peut servir."
    r = v.Rapport()
    v.avertir_element(e, 0, r, "x.json")
    assert [a for a in r.avertissements if "ancrage" in a] == []


def test_citees_du_pour_toi_tolere_les_formes_invalides():
    assert v.citees_du_pour_toi({"contexte_sections": {"a": {}, "b": {}}}) == ["a", "b"]
    assert v.citees_du_pour_toi({"contexte_sections": ["a"]}) == [] and v.citees_du_pour_toi({}) == []


def _racine_camille(tmp_path, jour, pour_toi, cites):
    (tmp_path / "CONTEXTE.md").write_text(CAMILLE_TXT, encoding="utf-8")
    e = element_depuis_brut({"id": "fx-1", "produit": "claude-code", "titre": "Commande /foo", "version": None,
                             "date_publication": None, "url": "https://example.org/x", "officielle": True}, impact="moyen")
    e["pour_toi"] = pour_toi
    e["contexte_sections"] = resoudre(tmp_path, {k: "section citée par le test" for k in cites})
    return ecrire_quotidien(tmp_path, "claude", {}, jour, extra_elements=[e])


def test_de_bout_en_bout_avertit_sans_changer_le_code(tmp_path, capsys):
    _racine_camille(tmp_path, JOUR, "Ça peut servir un jour.", ["projet.atelier-resa"])
    assert v.main(["--racine", str(tmp_path), "--perimetre", "claude"]) == 0
    sortie = capsys.readouterr().out
    assert any(l.startswith(f"! AVERTISSEMENT {JOUR}.json elements[0] (fx-1): ancrage") for l in sortie.splitlines())
    assert "claude valide" in sortie


def test_de_bout_en_bout_projet_nomme_pas_d_avertissement(tmp_path, capsys):
    _racine_camille(tmp_path, JOUR, "Utile pour atelier-resa.", ["projet.atelier-resa"])
    assert v.main(["--racine", str(tmp_path), "--perimetre", "claude"]) == 0
    assert "ancrage" not in capsys.readouterr().out


def test_fichier_anterieur_a_d64_hors_champ(tmp_path, capsys):
    _racine_camille(tmp_path, "2026-09-20", "Ça peut servir un jour.", ["projet.atelier-resa"])
    v.main(["--racine", str(tmp_path), "--perimetre", "claude"])
    assert "ancrage" not in capsys.readouterr().out


def test_contexte_invalide_ou_absent_pas_de_controle(tmp_path):
    assert v.termes_ancrage_du_contexte(tmp_path / "CONTEXTE.md") is None
    (tmp_path / "CONTEXTE.md").write_text("# T\n\nsans ctx-id\n", encoding="utf-8")
    assert v.termes_ancrage_du_contexte(tmp_path / "CONTEXTE.md") is None

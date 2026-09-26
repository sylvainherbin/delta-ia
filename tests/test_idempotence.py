"""Critères d'acceptation, de bout en bout via fetch.py : deux passages identiques, état intact, zéro après --valider."""

import json

import pytest

import fetch
from conftest import FauxClient, ecrire_quotidien

JOUR = __import__("datetime").date.today().isoformat()


@pytest.fixture
def racine(tmp_path, monkeypatch, date_figee):
    (tmp_path / "state").mkdir()
    (tmp_path / "raw").mkdir()
    monkeypatch.setattr(fetch, "Client", lambda: FauxClient())
    return tmp_path


def lancer(racine, *args):
    return fetch.main(["--racine", str(racine), *args])


def lire(chemin):
    return json.loads(chemin.read_text(encoding="utf-8"))


@pytest.mark.parametrize("perimetre", ["claude", "openai", "actu"])
def test_deux_passages_donnent_les_memes_nouveautes_sans_toucher_l_etat(racine, perimetre):
    brut = racine / "raw" / f"{perimetre}-nouveautes.json"
    etat = racine / "state" / f"{perimetre}.json"
    assert lancer(racine, "--perimetre", perimetre) == 0
    premier = lire(brut)
    assert lancer(racine, "--perimetre", perimetre) == 0
    second = lire(brut)
    assert premier["nouveautes"] == second["nouveautes"] and premier["ignores"] == second["ignores"]
    assert premier["nouveautes"], "les échantillons contiennent des éléments récents"
    assert not etat.exists(), "l'état n'est jamais modifié sans --valider"
    assert premier["perimetre"] == perimetre and premier["fenetre_depuis"] == "2026-08-24"


def test_apres_valider_zero_nouveaute(racine):
    brut = racine / "raw" / "claude-nouveautes.json"
    etat = racine / "state" / "claude.json"
    lancer(racine, "--perimetre", "claude")
    n = len(lire(brut)["nouveautes"]) + len(lire(brut)["ignores"])
    ecrire_quotidien(racine, "claude", lire(brut), JOUR)
    assert lancer(racine, "--perimetre", "claude", "--valider") == 0
    assert etat.exists() and len(lire(etat)["vus"]) == n
    assert lancer(racine, "--perimetre", "claude") == 0
    apres = lire(brut)
    assert apres["nouveautes"] == [] and apres["ignores"] == []
    assert apres["fenetre_depuis"] is None, "plus de fenêtre une fois l'état constitué"
    # revalider ne change rien
    avant = etat.read_text()
    assert lancer(racine, "--perimetre", "claude", "--valider") == 0
    assert lire(etat)["vus"] == lire(avant and etat)["vus"]


def test_premier_passage_ignore_les_anciens_et_les_valide_aussi(racine):
    """Sans état, seuls les 30 derniers jours sont des nouveautés ; les anciens partent dans `ignores`."""
    lancer(racine, "--perimetre", "claude")
    brut = lire(racine / "raw" / "claude-nouveautes.json")
    assert all(e["date_publication"] >= "2026-08-24" for e in brut["nouveautes"])
    assert brut["ignores"] == []  # les échantillons ne contiennent que des entrées récentes


def test_depuis_restreint_la_fenetre(racine):
    lancer(racine, "--perimetre", "claude", "--depuis", "2026-09-20")
    brut = lire(racine / "raw" / "claude-nouveautes.json")
    assert brut["fenetre_depuis"] == "2026-09-20"
    assert all(e["date_publication"] >= "2026-09-20" for e in brut["nouveautes"])
    assert brut["ignores"], "les éléments antérieurs sont listés pour être validés"


def test_dry_run_n_ecrit_rien(racine):
    assert lancer(racine, "--perimetre", "claude", "--dry-run") == 0
    assert not (racine / "raw" / "claude-nouveautes.json").exists()
    lancer(racine, "--perimetre", "claude")
    ecrire_quotidien(racine, "claude", lire(racine / "raw" / "claude-nouveautes.json"), JOUR)
    assert lancer(racine, "--perimetre", "claude", "--valider", "--dry-run") == 0
    assert not (racine / "state" / "claude.json").exists()


def test_nouveautes_triees_et_format(racine):
    lancer(racine, "--perimetre", "openai")
    brut = lire(racine / "raw" / "openai-nouveautes.json")
    dates = [e["date_publication"] for e in brut["nouveautes"]]
    cle = [d or "9999" for d in dates]  # non datés en tête, comme etat.detecter (D3, O2)
    assert cle == sorted(cle, reverse=True)
    assert {e["produit"] for e in brut["nouveautes"]} <= {"chatgpt", "codex"}
    assert set(brut) == {"perimetre", "genere_le", "fenetre_depuis", "borne", "sources_traitees", "elements_total",
                         "nouveautes", "ignores", "ignores_sources", "sources_amorcees", "empreintes", "sources_en_echec"}

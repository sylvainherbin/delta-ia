"""Identifiants stables, détection des nouveautés, fenêtre du premier passage, validation de l'état."""

from datetime import date

from deltalib.etat import detecter, premier_passage, valider
from deltalib.modeles import Element, construire_id, normaliser_titre


def el(titre, date_pub, version=None, produit="claude-code"):
    return Element(produit, titre, version, date_pub, "https://exemple.test/x", "contenu", "src", True)


def test_identifiant_stable_et_normalise():
    a = construire_id("claude-code", "2.1.280", "2026-09-22", "Claude Code 2.1.280")
    b = construire_id("claude-code", "2.1.280", None, "  claude  code 2.1.280 ")
    assert a == b and a.startswith("claude-code-2.1.280-") and len(a.split("-")[-1]) == 10
    assert construire_id("claude", None, "2026-09-22", "Été") == construire_id("claude", None, "2026-09-22", "ete")
    assert construire_id("claude", None, None, "x").startswith("claude-nd-")
    assert normaliser_titre("Éléphant, GPT-6 !") == "elephant gpt 6"


def test_detection_sans_etat_avec_fenetre():
    etat = {"version": 1, "maj_le": None, "vus": {}}
    assert premier_passage(etat)
    elements = [el("récent", "2026-09-20"), el("vieux", "2026-07-01"), el("sans date", None), el("borne", "2026-08-24")]
    nouveautes, ignores = detecter(elements, etat, date(2026, 8, 24))
    assert [e.titre for e in nouveautes] == ["récent", "borne"]  # tri par date décroissante, borne incluse
    assert len(ignores) == 2 and el("vieux", "2026-07-01").id in ignores and el("sans date", None).id in ignores


def test_detection_avec_etat_sans_fenetre():
    deja = el("déjà vu", "2026-09-01")
    etat = {"version": 1, "maj_le": "x", "vus": {deja.id: {}}}
    assert not premier_passage(etat)
    nouveautes, ignores = detecter([deja, el("nouveau", "2026-09-02"), el("nouveau sans date", None)], etat, None)
    assert {e.titre for e in nouveautes} == {"nouveau", "nouveau sans date"} and ignores == []


def test_detection_deduplique_les_identifiants():
    e = el("double", "2026-09-02")
    nouveautes, _ = detecter([e, el("double", "2026-09-02")], {"vus": {}}, None)
    assert len(nouveautes) == 1


def test_valider_ajoute_nouveautes_et_ignores_puis_est_idempotent():
    etat = {"version": 1, "maj_le": None, "vus": {}}
    brut = {"nouveautes": [el("a", "2026-09-02").en_dict()], "ignores": ["claude-nd-abc"]}
    etat, ajoutes = valider(etat, brut)
    assert ajoutes == 2 and len(etat["vus"]) == 2 and etat["maj_le"]
    assert etat["vus"]["claude-nd-abc"]["ignore"] is True
    etat, ajoutes = valider(etat, brut)
    assert ajoutes == 0 and len(etat["vus"]) == 2
    # tout ce qui est validé disparaît des nouveautés
    nouveautes, ignores = detecter([el("a", "2026-09-02")], etat, None)
    assert nouveautes == [] and ignores == []

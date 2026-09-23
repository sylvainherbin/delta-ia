"""Identifiants stables, détection des nouveautés, fenêtre du premier passage, validation de l'état."""

from datetime import date

import pytest

from deltalib.etat import detecter, premier_passage, valider
from deltalib.modeles import Element, FormatInattendu, cle_version, empreinte_contenu


def el(titre, date_pub, version=None, produit="claude-code", ident=None, contenu="contenu"):
    return Element(id=ident or f"{produit}-{titre}", produit=produit, titre=titre, version=version, date_publication=date_pub,
                   url="https://exemple.test/x", contenu=contenu, source_id="src", officielle=True)


def test_element_exige_un_identifiant_natif():
    with pytest.raises(FormatInattendu):
        el("x", None, ident=" ")


def test_cle_version_et_empreinte():
    assert cle_version("2.1.280") > cle_version("2.1.99") > cle_version("0.2.21")
    assert cle_version("0.157.0-alpha.11") < cle_version("0.157.0") < cle_version("0.158.0-alpha.2")
    assert empreinte_contenu("a  ") == empreinte_contenu("a") != empreinte_contenu("b")


def test_detection_sans_etat_avec_fenetre():
    etat = {"version": 1, "maj_le": None, "vus": {}}
    assert premier_passage(etat)
    elements = [el("récent", "2026-09-20"), el("vieux", "2026-07-01"), el("sans date", None), el("borne", "2026-08-24")]
    nouveautes, ignores = detecter(elements, etat, date(2026, 8, 24))
    # D3 : un élément non daté n'est jamais ignoré à cause de la fenêtre ; il est trié en tête
    assert [e.titre for e in nouveautes] == ["sans date", "récent", "borne"]
    assert ignores == [el("vieux", "2026-07-01").id]


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


def test_revision_detectee_seulement_si_l_empreinte_change():
    e = el("notes", "2026-09-22", ident="claude-apps-notes-2026-09-22", contenu="v1")
    e.empreinte = empreinte_contenu("v1")
    etat = {"version": 1, "maj_le": "x", "vus": {e.id: {"empreinte": e.empreinte}}}
    assert detecter([e], etat, None) == ([], [])
    e2 = el("notes", "2026-09-22", ident=e.id, contenu="v2")
    e2.empreinte = empreinte_contenu("v2")
    nouveautes, _ = detecter([e2], etat, None)
    assert [x.id for x in nouveautes] == [e.id] and nouveautes[0].revision is True
    # sans suivi des révisions (pas d'empreinte), un identifiant connu ne revient jamais
    e3 = el("notes", "2026-09-22", ident=e.id, contenu="v3")
    assert detecter([e3], etat, None) == ([], [])


def test_valider_enregistre_et_met_a_jour_l_empreinte():
    etat = {"version": 1, "maj_le": None, "vus": {}}
    e = el("notes", "2026-09-22", ident="claude-apps-notes-2026-09-22", contenu="v1"); e.empreinte = "aaa"
    etat, n = valider(etat, {"nouveautes": [e.en_dict()], "ignores": ["claude-apps-notes-2026-01-01"],
                             "empreintes": {"claude-apps-notes-2026-01-01": "iii"}})
    assert n == 2 and etat["vus"][e.id]["empreinte"] == "aaa" and etat["vus"]["claude-apps-notes-2026-01-01"]["empreinte"] == "iii"
    e.empreinte = "bbb"; e.revision = True
    etat, n = valider(etat, {"nouveautes": [e.en_dict()], "ignores": []})
    assert n == 1 and etat["vus"][e.id]["empreinte"] == "bbb" and etat["vus"][e.id]["revise_le"]

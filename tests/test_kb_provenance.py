"""D127 : provenance et caducité des fiches qui recommandent (lot `provenance`, historique des corrections, valider.py)."""

import json

import pytest

import catalogue as cli
import orchestrateur
import valider
from deltalib.kb import catalogue as cat
from deltalib.kb.modeles import EntreeExtraite

CONTEXTE = "# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n"
JOUR = "2026-10-14"
URL = "https://code.claude.com/docs/en/commands"


def affirmation(**kw):
    return {"affirmation": "La commande reprend une session.", "source": URL, "releve_le": "2026-10-13",
            "caduc_si": "La page des commandes change de syntaxe.", **kw}


def entree(nom="resume", verdict="utiliser", categorie="commandes", provenance=None, sections=None, source="Resume a session."):
    e = cat.nouvelle_entree(EntreeExtraite(
        produit="claude-code", categorie=categorie, nom=nom, usage=f"claude --{nom}", description_source=source,
        url=URL, libelle="Doc", origine="test", usage_nature="syntaxe"), "2026-09-23")
    c = {"description": "Reprend une session de travail dans le projet.", "statut_usage": "inconnu",
         "recommandation": {"verdict": verdict, "pourquoi": "Reprise des sessions du projet de veille."},
         "contexte_sections": sections or {}}
    if provenance:
        c["provenance"] = provenance
    assert cat.appliquer_commentaires({e["id"]: e}, {e["id"]: c}, jour=JOUR, contexte="a" * 40,
                                      resoudre=lambda cs: {k: {"sha1": "b" * 40, "pourquoi": v} for k, v in cs.items()}) == []
    return e


def base(*entrees):
    return {e["id"]: e for e in entrees}


# ----------------------------------------------------------------------------------------------- forme de la provenance

def test_provenance_valide_les_trois_sources():
    prov = [affirmation(), affirmation(source="contexte:profil"), affirmation(source="essai:claude-code-commandes-resume",
                                                                         revoir_le="2026-12-01")]
    assert cat.verifier_provenance(prov, {"profil"}, JOUR, {"claude-code-commandes-resume"}) is None


@pytest.mark.parametrize("prov,sections,morceau", [
    ([], {"profil"}, "liste de 1 à"),
    ("texte", set(), "liste de 1 à"),
    ([affirmation(caduc_si="")], set(), "`caduc_si`"),
    ([{k: v for k, v in affirmation().items() if k != "releve_le"}], set(), "attendu"),
    ([affirmation(inconnu=1)], set(), "attendu"),
    ([affirmation(source="ma mémoire")], set(), "`source` = URL"),
    ([affirmation(source="contexte:autre")], {"profil"}, "section non citée"),
    ([affirmation(source="essai:inconnu")], set(), "essai absent"),
    ([affirmation(releve_le="2026-13-01")], set(), "AAAA-MM-JJ"),
    ([affirmation(releve_le="2026-10-15")], set(), "postérieur"),
    ([affirmation(revoir_le="2026-10-01")], set(), "`revoir_le`"),
    ([affirmation(affirmation="x" * 301)], set(), "`affirmation`"),
    ([affirmation()] * 9, set(), "liste de 1 à"),
])
def test_provenance_refus(prov, sections, morceau):
    msg = cat.verifier_provenance(prov, sections, JOUR, set())
    assert msg and morceau in msg


def test_revoir_echu():
    assert cat.revoir_echu([affirmation(revoir_le="2026-10-14")], JOUR)
    assert not cat.revoir_echu([affirmation(revoir_le="2026-10-15"), affirmation()], JOUR)


# ----------------------------------------------------------------------------------------------- appliquer : commentaire complet

def appliquer(e, c, **kw):
    return cat.appliquer_commentaires({e["id"]: e}, {e["id"]: c}, jour=JOUR, contexte="a" * 40,
                                      resoudre=lambda cs: {k: {"sha1": "b" * 40, "pourquoi": v} for k, v in cs.items()}, **kw)


def commentaire(verdict="tester", **kw):
    return {"description": "Reprend une session de travail dans le projet.", "statut_usage": "inconnu",
            "recommandation": {"verdict": verdict, "pourquoi": "Reprise des sessions du projet de veille."},
            "contexte_sections": {"profil": "projet"}, **kw}


def test_commentaire_qui_recommande_exige_la_provenance():
    e = entree(verdict="ignorer")
    avant = json.dumps(e)
    erreurs = appliquer(e, commentaire("tester"), exiger_provenance=True)
    assert len(erreurs) == 1 and "provenance` obligatoire" in erreurs[0]
    assert json.dumps(e) == avant
    assert appliquer(e, commentaire("tester", provenance=[affirmation(source="contexte:profil")]), exiger_provenance=True) == []
    assert e["provenance"][0]["source"] == "contexte:profil"


def test_commentaire_sans_exigence_laisse_les_appels_existants_inchanges():
    e = entree(verdict="ignorer")
    assert appliquer(e, commentaire("tester")) == [] and "provenance" not in e


def test_commentaire_ignorer_ne_porte_pas_de_provenance():
    e = entree(verdict="ignorer")
    assert appliquer(e, commentaire("ignorer", provenance=[affirmation()]), exiger_provenance=True)[0].endswith("ignorer (D127)")
    assert appliquer(e, commentaire("ignorer"), exiger_provenance=True) == []
    assert "provenance" not in e and e["historique"][-1]["changement"] == "commentaire révisé"


def test_commentaire_garde_la_provenance_existante_si_elle_reste_valide():
    e = entree(provenance=[affirmation(source="contexte:profil")], sections={"profil": "x"})
    assert appliquer(e, commentaire("utiliser"), exiger_provenance=True) == []
    assert e["provenance"][0]["source"] == "contexte:profil"
    # une section qui n'est plus citée rend l'ancienne provenance invalide : l'agent doit la refaire
    erreurs = appliquer(e, {**commentaire("utiliser"), "contexte_sections": {}}, exiger_provenance=True)
    assert erreurs and "section non citée" in erreurs[0]


def test_changement_de_provenance_garde_l_ancienne_valeur_et_la_raison():
    ancienne = [affirmation()]
    e = entree(provenance=ancienne)
    nouvelle = [affirmation(affirmation="Autre fait.", releve_le="2026-10-14")]
    assert appliquer(e, commentaire("utiliser", provenance=nouvelle, raison_correction="la page a changé"), exiger_provenance=True) == []
    assert e["provenance"] == nouvelle
    h = [x for x in e["historique"] if x["changement"] == "provenance corrigée"]
    assert h == [{"date": JOUR, "changement": "provenance corrigée", "avant": ancienne, "raison": "la page a changé"}]
    assert "raison_correction" not in e


def test_changement_de_recommandation_garde_l_ancienne_valeur():
    e = entree(verdict="utiliser", provenance=[affirmation()])
    assert appliquer(e, commentaire("tester", provenance=[affirmation()]), exiger_provenance=True) == []
    h = [x for x in e["historique"] if x["changement"] == "recommandation corrigée"]
    assert h[0]["avant"] == {"verdict": "utiliser", "pourquoi": "Reprise des sessions du projet de veille."}
    assert h[0]["raison"] == "commentaire révisé"


def test_passage_a_ignorer_retire_la_provenance_et_la_garde_dans_l_historique():
    prov = [affirmation()]
    e = entree(verdict="tester", provenance=prov)
    assert appliquer(e, commentaire("ignorer"), exiger_provenance=True) == []
    assert "provenance" not in e
    assert {"date": JOUR, "changement": "provenance corrigée", "avant": prov, "raison": "verdict passé à ignorer"} in e["historique"]


def test_raison_correction_invalide():
    e = entree(provenance=[affirmation()])
    assert "raison_correction" in appliquer(e, commentaire("utiliser", raison_correction=" "), exiger_provenance=True)[0]


# ----------------------------------------------------------------------------------------------- appliquer : provenance seule

def test_provenance_seule_ajoute_sans_refaire_le_commentaire():
    e = entree()
    avant = (e["description"], e["recommandation"], e["contexte_empreinte"])
    assert appliquer(e, {"provenance": [affirmation()]}) == []
    assert e["provenance"] == [affirmation()] and e["maj_le"] == JOUR
    assert (e["description"], e["recommandation"], e["contexte_empreinte"]) == avant
    assert e["historique"][-1] == {"date": JOUR, "changement": "provenance ajoutée"}


def test_provenance_seule_refuse_ignorer_non_commentee_et_retiree():
    assert "réservée" in appliquer(entree(verdict="ignorer"), {"provenance": [affirmation()]})[0]
    non_commentee = entree()
    non_commentee["commentee"] = False
    assert "réservée" in appliquer(non_commentee, {"provenance": [affirmation()]})[0]
    retiree = entree()
    retiree["retiree"] = True
    assert "réservée" in appliquer(retiree, {"provenance": [affirmation()]})[0]


def test_provenance_seule_deja_presente_exige_la_raison():
    ancienne = [affirmation()]
    e = entree(provenance=ancienne)
    nouvelle = [affirmation(releve_le="2026-10-14")]
    assert "raison_correction` obligatoire" in appliquer(e, {"provenance": nouvelle})[0]
    assert e["provenance"] == ancienne
    assert appliquer(e, {"provenance": nouvelle, "raison_correction": "relue le 14/10"}) == []
    assert e["provenance"] == nouvelle
    assert e["historique"][-1]["avant"] == ancienne and e["historique"][-1]["raison"] == "relue le 14/10"
    # même valeur : rien ne change
    nb = len(e["historique"])
    assert appliquer(e, {"provenance": nouvelle}) == [] and len(e["historique"]) == nb


def test_provenance_seule_source_contexte_doit_etre_citee_par_la_fiche():
    e = entree(sections={"profil": "projet"})
    assert appliquer(e, {"provenance": [affirmation(source="contexte:profil")]}) == []
    assert "section non citée" in appliquer(entree(), {"provenance": [affirmation(source="contexte:profil")]})[0]


# ----------------------------------------------------------------------------------------------- fusionner

def extraite(e, **kw):
    return EntreeExtraite(produit=e["produit"], categorie=e["categorie"], nom=e["nom"], usage=kw.get("usage", e["usage"]),
                          description_source=kw.get("source", e["description_source"]), url=URL, libelle="Doc",
                          origine="test", usage_nature="syntaxe")


def test_documentation_modifiee_sous_une_fiche_qui_recommande():
    prov = [affirmation()]
    e = entree(verdict="tester", provenance=prov)
    res, modif = cat.fusionner(base(e), [extraite(e, source="Resume a session. New text.")], {"test"}, jour=JOUR)
    f = res[e["id"]]
    assert modif["description_source_modifiee"] == [e["id"]] and f["commentee"] is False
    assert "provenance" not in f
    h = {x["changement"]: x for x in f["historique"][-2:]}
    assert h["description d'origine modifiée dans la documentation"]["avant"] == "Resume a session."
    assert h["description d'origine modifiée dans la documentation"]["raison"] == "modifié dans la documentation"
    assert h["provenance corrigée"]["avant"] == prov
    assert cat.provenance_due(f) is False, "non commentée : la fiche repasse d'abord par un commentaire"


def test_documentation_modifiee_sous_une_fiche_ignorer_n_est_pas_touchee():
    e = entree(verdict="ignorer")
    res, _ = cat.fusionner(base(e), [extraite(e, usage="claude --resume [session]")], {"test"}, jour=JOUR)
    assert res[e["id"]]["historique"][-1] == {"date": JOUR, "changement": "usage modifié dans la documentation"}
    assert "provenance" not in res[e["id"]]


# ----------------------------------------------------------------------------------------------- lot provenance

def test_lot_provenance_ordre_plafond_et_exclusions(monkeypatch):
    monkeypatch.setattr(cat, "PROVENANCE_MAX", 3)
    ents = [entree("b", "tester"), entree("a", "tester"), entree("z", "utiliser"), entree("m", "utiliser", "skills"),
            entree("i", "ignorer"), entree("p", "utiliser", provenance=[affirmation()])]
    retiree = entree("r", "utiliser")
    retiree["retiree"] = True
    non_commentee = entree("n", "utiliser")
    non_commentee["commentee"] = False
    b = base(*ents, retiree, non_commentee)
    assert [b[k]["nom"] for k in cat.provenance_detail(b)] == ["z", "m", "a"], "utiliser d'abord, puis catégorie, puis id ; plafond 3"
    assert len(cat.provenance_detail(b, maximum=None)) == 4


# ----------------------------------------------------------------------------------------------- valider.py --kb

def kb(tmp_path, *entrees, perimetre="claude"):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    cat.ecrire(tmp_path, perimetre, base(*entrees))
    return ["--perimetre", perimetre, "--racine", str(tmp_path), "--kb"]


def test_valider_signale_les_fiches_qui_recommandent_sans_provenance(tmp_path, capsys):
    args = kb(tmp_path, entree("a", "utiliser"), entree("b", "tester"), entree("c", "ignorer"),
              entree("d", "utiliser", provenance=[affirmation()]))
    assert valider.main(args) == 0
    sortie = capsys.readouterr().out
    assert "2 fiches utiliser/tester sans provenance (D127)" in sortie
    assert "claude-code-commandes-a" in sortie and "claude-code-commandes-c" not in sortie


def test_valider_sans_avertissement_quand_tout_est_source(tmp_path, capsys):
    assert valider.main(kb(tmp_path, entree("a", provenance=[affirmation()]), entree("c", "ignorer"))) == 0
    assert "provenance" not in capsys.readouterr().out


def test_valider_refuse_une_provenance_mal_formee_ou_sur_ignorer(tmp_path, capsys):
    e = entree("a", provenance=[affirmation()])
    e["provenance"][0]["releve_le"] = "hier"
    assert valider.main(kb(tmp_path, e)) == 1
    assert "`releve_le` doit être AAAA-MM-JJ" in capsys.readouterr().err
    i = entree("i", "ignorer")
    i["provenance"] = [affirmation()]
    assert valider.main(kb(tmp_path, i)) == 1
    assert "ne recommande pas" in capsys.readouterr().err


def test_valider_signale_une_affirmation_a_revoir(tmp_path, capsys):
    e = entree("a", provenance=[affirmation(revoir_le="2026-10-14")])
    assert valider.main(kb(tmp_path, e)) == 0
    assert "à revérifier" in capsys.readouterr().out


def test_valider_source_contexte_doit_etre_une_section_de_la_fiche(tmp_path, capsys):
    e = entree("a", provenance=[affirmation(source="contexte:profil")], sections={"profil": "projet"})
    assert valider.main(kb(tmp_path, e)) == 0
    capsys.readouterr()
    e["contexte_sections"] = {}
    assert valider.main(kb(tmp_path, e)) == 1
    assert "section non citée" in capsys.readouterr().err


# ----------------------------------------------------------------------------------------------- CLI et orchestrateur

def test_cli_lot_provenance_de_bout_en_bout(tmp_path, capsys):
    ent = [entree(f"c{i:02}", "tester") for i in range(30)] + [entree("zz", "ignorer")]
    args = kb(tmp_path, *ent)[:-1]  # sans --kb
    assert cli.main(["lots", *args]) == 0
    assert "provenance" in capsys.readouterr().out
    assert cli.main(["a-commenter", *args, "--lot", "provenance"]) == 0
    lot = json.loads(capsys.readouterr().out)
    assert [x["nom"] for x in lot] == [f"c{i:02}" for i in range(25)] and all("provenance" in x for x in lot)
    assert orchestrateur.lots_dus(tmp_path, "claude") >= 30, "toutes les fiches dues comptent, pas seulement le plafond"
    f = tmp_path / "provenance.json"
    f.write_text(json.dumps({x["id"]: {"provenance": [affirmation()]} for x in lot}), encoding="utf-8")
    assert cli.main(["appliquer", *args, "--fichier", str(f)]) == 0
    capsys.readouterr()
    assert valider.main([*args, "--kb"]) == 0
    assert "5 fiches utiliser/tester sans provenance" in capsys.readouterr().out
    assert cli.main(["a-commenter", *args, "--lot", "provenance"]) == 0
    assert [x["nom"] for x in json.loads(capsys.readouterr().out)] == [f"c{i:02}" for i in range(25, 30)]


def test_cli_appliquer_commentaire_complet_exige_la_provenance(tmp_path, capsys):
    e = entree("a", "ignorer")
    args = kb(tmp_path, e)[:-1]
    f = tmp_path / "c.json"
    f.write_text(json.dumps({e["id"]: commentaire("tester", contexte_sections={})}), encoding="utf-8")
    avant = (tmp_path / "docs/data/kb/claude/commandes.json").read_bytes()
    assert cli.main(["appliquer", *args, "--fichier", str(f)]) == 1
    assert "provenance` obligatoire" in capsys.readouterr().err
    assert (tmp_path / "docs/data/kb/claude/commandes.json").read_bytes() == avant
    f.write_text(json.dumps({e["id"]: commentaire("tester", contexte_sections={}, provenance=[affirmation()])}), encoding="utf-8")
    assert cli.main(["appliquer", *args, "--fichier", str(f)]) == 0

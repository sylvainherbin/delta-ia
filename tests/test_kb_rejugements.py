"""D78 : demandes déclarées, extinction par commentaire et consommation par les passages kb."""

import json
from datetime import date

import pytest
import yaml

import catalogue as cli
import orchestrateur
import valider
from deltalib.kb import catalogue as cat
from deltalib.kb.modeles import EntreeExtraite


JOUR = "2026-10-04"
MOTIF = "CONTEXTE.md réécrit (organisation, worktrees)"
COURANTES = {"profil": "a" * 40}


def entree(ident="codex-commandes-exemple", verdict="tester", commente="2026-10-01"):
    e = cat.nouvelle_entree(EntreeExtraite(
        id=ident, produit="claude-code" if ident.startswith("claude-code-") else "codex", categorie="commandes",
        nom="exemple", usage="exemple", description_source="An example command.",
        url="https://example.org/commandes", libelle="Commandes", origine="test"), "2026-09-23")
    assert cat.appliquer_commentaires({ident: e}, {ident: commentaire(verdict)}, jour=commente,
                                     resoudre=lambda cs: cs) == []
    return e


def commentaire(verdict="tester"):
    return {"description": "Affiche les informations de la session en cours.", "statut_usage": "inconnu",
            "recommandation": {"verdict": verdict, "pourquoi": "Essai sur le projet de veille pour lire les missions."},
            "contexte_sections": {}}


def ecrire_demandes(racine, ids, jour=JOUR, motif=MOTIF, **options):
    chemin = racine / "kb-rejugements.yaml"
    chemin.write_text(yaml.safe_dump([{"date": jour, "motif": motif, "ids": ids, **options}], allow_unicode=True), encoding="utf-8")
    return chemin


@pytest.mark.parametrize("commente,du", [("2026-10-03", True), ("2026-10-04", False), ("2026-10-05", False)])
@pytest.mark.parametrize("sections", [{}, [], None])
def test_date_du_dernier_commentaire_et_sections_vides(commente, du, sections):
    e = entree(commente=commente)
    e["contexte_sections"] = sections
    demandes = {e["id"]: [{"date": JOUR, "motif": MOTIF}]}
    det = cat.perimees_detail({e["id"]: e}, COURANTES, rejugements=demandes)
    assert bool(det) is du
    if du:
        assert det == [{"id": e["id"], "categorie": "rejugement", "motif": f"rejugement demandé ({MOTIF})"}]


def test_maj_documentaire_et_adoption_n_eteignent_pas_la_demande():
    e = entree()
    demandes = {e["id"]: [{"date": JOUR, "motif": MOTIF}]}
    cat.appliquer_adoptions({e["id"]: e}, [e["id"]], jour="2026-10-05")
    e["historique"].append({"date": "2026-10-06", "changement": "de nouveau dans la documentation"})
    e["maj_le"] = "2026-10-06"
    assert cat.classer(e, COURANTES, rejugements=demandes) == ("rejugement", f"rejugement demandé ({MOTIF})")
    assert cat.appliquer_commentaires({e["id"]: e}, {e["id"]: commentaire()}, jour="2026-10-06") == []
    assert cat.classer(e, COURANTES, rejugements=demandes) is None


@pytest.mark.parametrize("changement", ["commentaire révisé", "réévaluée"])
def test_dernier_commentaire_revise_eteint_la_demande(changement):
    e = entree()
    e["historique"].append({"date": JOUR, "changement": changement})
    assert cat.motif_rejugement(e, {e["id"]: [{"date": JOUR, "motif": MOTIF}]}) is None


def test_seules_les_fiches_commentees_actives_et_listees_sont_dues():
    entrees = {k: entree(k) for k in ("active", "non-commentee", "retiree", "hors-liste")}
    entrees["non-commentee"]["commentee"] = False
    entrees["retiree"]["retiree"] = True
    demandes = {k: [{"date": JOUR, "motif": MOTIF}] for k in entrees if k != "hors-liste"}
    assert cat.perimees(entrees, COURANTES, rejugements=demandes) == ["active"]
    assert cat.perimees(entrees, {}, rejugements=demandes) == ["active"], "D78 ne dépend pas de la présence de CONTEXTE"


def test_ordre_et_plafond_communs_aux_trois_declencheurs():
    entrees = {f"r-{i:02}": entree(f"r-{i:02}", "ignorer") for i in range(12)}
    entrees.update({"r-u": entree("r-u", "utiliser"), "r-t": entree("r-t", "tester")})
    demandes = {k: [{"date": JOUR, "motif": MOTIF}] for k in entrees}
    for k, v in (("s-u", "utiliser"), ("s-t", "tester"), ("s-i", "ignorer")):
        entrees[k] = entree(k, v)
        entrees[k]["contexte_sections"] = {"profil": {"sha1": "b" * 40, "pourquoi": "Profil."}}
    entrees["adoption"] = entree("adoption", "ignorer")
    cat.appliquer_adoptions(entrees, ["adoption"], jour=JOUR)
    lot = cat.perimees(entrees, COURANTES, rejugements=demandes)
    assert len(lot) == cat.PERIMEES_MAX == 10
    assert lot == ["r-u", "s-u", "r-t", "s-t", "adoption", "r-00", "r-01", "r-02", "r-03", "r-04"]
    assert len(cat.perimees_detail(entrees, COURANTES, maximum=None, rejugements=demandes)) == 18


@pytest.mark.parametrize("contenu", [None, "", "# Aucune demande\n", "[]\n"])
def test_yaml_absent_ou_vide(tmp_path, capsys, contenu):
    if contenu is not None:
        (tmp_path / "kb-rejugements.yaml").write_text(contenu, encoding="utf-8")
    assert cat.charger_rejugements(tmp_path) == {}
    assert cli.main(["lots", "--perimetre", "openai", "--racine", str(tmp_path)]) == 0
    sortie = capsys.readouterr()
    assert "0 fiches dues" in sortie.out and not sortie.err


def test_id_inconnu_averti_sans_erreur_ni_confusion_de_perimetre(tmp_path, capsys):
    ids = ["claude-code-commandes-exemple", "codex-commandes-exemple"]
    for per, ident in zip(("claude", "openai"), ids):
        cat.ecrire(tmp_path, per, {ident: entree(ident)})
    ecrire_demandes(tmp_path, [*ids, "inconnu", "inconnu"], jour=date.fromisoformat(JOUR))
    assert cli.main(["lots", "--perimetre", "openai", "--racine", str(tmp_path)]) == 0
    sortie = capsys.readouterr()
    assert "1 fiches dues" in sortie.out
    assert "id inconnus dans la base : inconnu" in sortie.err
    assert not any(ident in sortie.err for ident in ids), "le YAML est commun aux deux bases"


def test_derniere_demande_prevaut_et_ids_doubles_ne_dupliquent_pas_le_lot(tmp_path):
    e = entree(commente=JOUR)
    cat.ecrire(tmp_path, "openai", {e["id"]: e})
    (tmp_path / "kb-rejugements.yaml").write_text(yaml.safe_dump([
        {"date": "2026-10-05", "motif": "seconde demande", "ids": [e["id"], e["id"]]},
        {"date": "2026-10-03", "motif": "première demande", "ids": [e["id"]]}]), encoding="utf-8")
    demandes = cat.charger_rejugements(tmp_path)
    det = cat.perimees_detail({e["id"]: e}, COURANTES, rejugements=demandes)
    assert det == [{"id": e["id"], "categorie": "rejugement", "motif": "rejugement demandé (seconde demande)"}]


@pytest.mark.parametrize("contenu", ["{}", "[", "- date: hier\n  motif: x\n  ids: []\n",
                                      "- date: 2026-10-04\n  motif: ''\n  ids: []\n",
                                      "- date: 2026-10-04\n  motif: x\n  ids: codex-commandes-exemple\n"])
def test_yaml_invalide_signale_explicitement(tmp_path, capsys, contenu):
    (tmp_path / "kb-rejugements.yaml").write_text(contenu, encoding="utf-8")
    assert cli.main(["lots", "--perimetre", "openai", "--racine", str(tmp_path)]) == 1
    assert "kb-rejugements.yaml" in capsys.readouterr().err


@pytest.mark.parametrize("perimetre,produit", [("claude", "claude-code"), ("openai", "codex")])
def test_plafond_30_jusqu_au_dernier_rejugement_puis_10_malgre_les_sections(tmp_path, capsys, perimetre, produit):
    (tmp_path / "CONTEXTE.md").write_text("# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n", encoding="utf-8")
    entrees = {f"{produit}-commandes-{i:02}": entree(f"{produit}-commandes-{i:02}") for i in range(35)}
    for e in entrees.values():
        e["contexte_sections"] = {"profil": {"sha1": "b" * 40, "pourquoi": "Profil."}}
    ids = list(entrees)[:2]
    cat.ecrire(tmp_path, perimetre, entrees)
    chemin = ecrire_demandes(tmp_path, ids, plafond=30)
    contenu_yaml = chemin.read_bytes()
    args = ["--perimetre", perimetre, "--racine", str(tmp_path)]
    for n, plafond in enumerate((30, 30, 10)):
        demandes = cat.charger_rejugements(tmp_path)
        assert cat.PERIMEES_MAX == 10
        assert cat.plafond_perimees(entrees, demandes) == plafond
        assert len(cat.perimees(entrees, COURANTES, rejugements=demandes)) == plafond
        assert len(cat.perimees_detail(entrees, COURANTES, maximum=None, rejugements=demandes)) == 35 - n
        assert len(cat.perimees(entrees, COURANTES, maximum=5, rejugements=demandes)) == 5
        assert cli.main(["lots", *args]) == 0
        ligne = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("perimees"))
        assert f"{plafond} entrées ce lancement sur {35 - n} dues" in ligne
        assert ligne.endswith(f"plafond {plafond}" + (", rattrapage D78" if n < 2 else ""))
        assert cli.main(["a-commenter", *args, "--lot", "perimees"]) == 0
        lot = json.loads(capsys.readouterr().out)
        assert len(lot) == plafond
        assert all(e["motif"] == "section:profil" for e in lot), "une section prioritaire ne masque pas le plafond D78"
        assert orchestrateur.lots_dus(tmp_path, perimetre) == 35 - n, "le décompte reste exhaustif"
        if n < len(ids):
            assert cat.appliquer_commentaires(entrees, {ids[n]: commentaire()}, jour=JOUR,
                                             resoudre=lambda cs: cs) == []
            cat.ecrire(tmp_path, perimetre, entrees)
    assert chemin.read_bytes() == contenu_yaml, "le retour à 10 ne nécessite aucune édition de la demande"


@pytest.mark.parametrize("inverser", [False, True])
def test_plafond_maximum_des_demandes_actives_meme_si_elles_se_chevauchent(tmp_path, inverser):
    e = entree()
    entrees = {e["id"]: e}
    cat.ecrire(tmp_path, "openai", entrees)
    demandes = [{"date": "2026-10-03", "motif": "ancienne", "ids": [e["id"]], "plafond": 40},
                {"date": JOUR, "motif": "dernière", "ids": [e["id"], e["id"]], "plafond": 30}]
    if inverser:
        demandes.reverse()
    (tmp_path / "kb-rejugements.yaml").write_text(yaml.safe_dump(demandes), encoding="utf-8")
    rejugements = cat.charger_rejugements(tmp_path)
    assert cat.motif_rejugement(e, rejugements) == "rejugement demandé (dernière)"
    assert cat.plafond_perimees(entrees, rejugements) == 40
    assert cat.appliquer_commentaires(entrees, {e["id"]: commentaire()}, jour="2026-10-03") == []
    assert cat.plafond_perimees(entrees, rejugements) == 30
    assert cat.appliquer_commentaires(entrees, {e["id"]: commentaire()}, jour=JOUR) == []
    assert cat.plafond_perimees(entrees, rejugements) == 10


@pytest.mark.parametrize("plafond", [10, 50])
def test_bornes_du_plafond_acceptees(tmp_path, plafond):
    e = entree()
    cat.ecrire(tmp_path, "openai", {e["id"]: e})
    ecrire_demandes(tmp_path, [e["id"]], plafond=plafond)
    assert cat.plafond_perimees({e["id"]: e}, cat.charger_rejugements(tmp_path)) == plafond


@pytest.mark.parametrize("plafond", [9, 51, -1, 0, 30.0, "30", None, True, False, [], {}])
def test_plafond_hors_bornes_ou_non_entier_refuse(tmp_path, capsys, plafond):
    ecrire_demandes(tmp_path, [], plafond=plafond)
    with pytest.raises(ValueError, match="plafond entier de 10 à 50"):
        cat.charger_rejugements(tmp_path)
    assert cli.main(["lots", "--perimetre", "openai", "--racine", str(tmp_path)]) == 1
    assert "kb-rejugements.yaml : demande 1 : plafond entier de 10 à 50" in capsys.readouterr().err


def test_demandes_sans_fiche_due_ne_rehaussent_pas_le_plafond(tmp_path, capsys):
    entrees = {k: entree(k, commente=JOUR if k == "recommentee" else "2026-10-01")
               for k in ("non-commentee", "retiree", "recommentee", "hors-liste")}
    entrees["non-commentee"]["commentee"] = False
    entrees["retiree"]["retiree"] = True
    cat.ecrire(tmp_path, "openai", entrees)
    ecrire_demandes(tmp_path, ["non-commentee", "retiree", "recommentee", "inconnu"], plafond=50)
    assert cat.plafond_perimees(entrees, cat.charger_rejugements(tmp_path)) == 10
    assert "id inconnus dans la base : inconnu" in capsys.readouterr().err


@pytest.mark.parametrize("contenu", ["[", "{}", "- date: 2026-10-04\n  motif: x\n  ids: []\n  plafond: 51\n"])
def test_lots_dus_yaml_invalide_avertit_et_garde_les_autres_declencheurs(tmp_path, capsys, contenu):
    (tmp_path / "CONTEXTE.md").write_text("# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n", encoding="utf-8")
    entrees = {k: entree(k, "ignorer") for k in ("section", "adoption", "ordinaire", "rejugement")}
    entrees["section"]["contexte_sections"] = {"profil": {"sha1": "b" * 40, "pourquoi": "Profil."}}
    entrees["ordinaire"]["commentee"] = False
    cat.appliquer_adoptions(entrees, ["adoption"], jour=JOUR)
    cat.ecrire(tmp_path, "openai", entrees)
    (tmp_path / "kb-rejugements.yaml").write_text(contenu, encoding="utf-8")
    assert orchestrateur.lots_dus(tmp_path, "openai") == 3
    avertissement = capsys.readouterr().err
    assert "! AVERTISSEMENT" in avertissement and "kb-rejugements.yaml" in avertissement
    assert "poursuite sans rejugements D78" in avertissement


def test_cli_orchestrateur_journal_et_extinction_sans_effacer_le_yaml(tmp_path, capsys, monkeypatch):
    class DateFixee(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 5)

    monkeypatch.setattr(cat, "date", DateFixee)
    (tmp_path / "CONTEXTE.md").write_text("# Profil\n<!-- ctx-id: profil -->\n\nUn profil.\n", encoding="utf-8")
    e = entree()
    cat.ecrire(tmp_path, "openai", {e["id"]: e})
    demande = ecrire_demandes(tmp_path, [e["id"]])
    contenu_yaml = demande.read_bytes()
    avant = {p: p.read_bytes() for p in (tmp_path / "docs/data").rglob("*") if p.is_file()}
    args = ["--perimetre", "openai", "--racine", str(tmp_path)]
    assert cli.main(["lots", *args]) == 0
    sortie = capsys.readouterr().out
    assert "1 fiches dues" in sortie and "perimees" in sortie
    assert cli.main(["a-commenter", *args, "--lot", "perimees"]) == 0
    lot = json.loads(capsys.readouterr().out)
    assert [(x["id"], x["motif"]) for x in lot] == [(e["id"], f"rejugement demandé ({MOTIF})")]
    assert orchestrateur.lots_dus(tmp_path, "openai") == 1
    assert all(p.read_bytes() == contenu for p, contenu in avant.items()), "la demande ne modifie pas la base"
    f = tmp_path / "commentaires.json"
    f.write_text(json.dumps({e["id"]: commentaire("utiliser")}), encoding="utf-8")
    assert cli.main(["appliquer", *args, "--fichier", str(f)]) == 0
    assert valider.main([*args, "--kb"]) == 0
    capsys.readouterr()
    journal = json.loads((cat.dossier(tmp_path, "openai") / "reevaluations.jsonl").read_text())
    assert journal == {"date": "2026-10-05", "id": e["id"], "verdict_avant": "tester", "verdict_apres": "utiliser",
                       "motif": f"rejugement demandé ({MOTIF})"}
    assert cli.main(["a-commenter", *args, "--lot", "perimees"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert orchestrateur.lots_dus(tmp_path, "openai") == 0
    assert demande.read_bytes() == contenu_yaml


# ------------------------------------------------------------------------------------ suivi : catalogue.py rejugements

def _suivi(tmp_path, capsys, *args):
    code = cli.main(["rejugements", "--racine", str(tmp_path), *args])
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def test_suivi_sans_fichier_ni_demande(tmp_path, capsys):
    assert _suivi(tmp_path, capsys)[:2] == (0, "aucune demande\n")
    (tmp_path / "kb-rejugements.yaml").write_text("[]\n", encoding="utf-8")
    assert _suivi(tmp_path, capsys)[:2] == (0, "aucune demande\n")
    code, out, _ = _suivi(tmp_path, capsys, "--json")
    assert code == 0 and json.loads(out)["openai"]["demandes"] == []


def test_suivi_yaml_invalide_renvoie_1(tmp_path, capsys):
    (tmp_path / "kb-rejugements.yaml").write_text("[", encoding="utf-8")
    code, _, err = _suivi(tmp_path, capsys)
    assert code == 1 and "kb-rejugements.yaml : YAML invalide" in err


def test_suivi_demande_active_eteinte_inconnus_plafond_et_estimation(tmp_path, capsys):
    anciennes = {f"codex-commandes-{i:02}": entree(f"codex-commandes-{i:02}") for i in range(25)}
    anciennes["codex-commandes-recommentee"] = entree("codex-commandes-recommentee", commente=JOUR)
    cat.ecrire(tmp_path, "openai", anciennes)
    cat.ecrire(tmp_path, "claude", {"claude-code-commandes-x": entree("claude-code-commandes-x")})
    ids = [*list(anciennes)[:25], "codex-commandes-recommentee", "codex-fantome", "claude-code-fantome", "sans-prefixe"]
    ecrire_demandes(tmp_path, ids, plafond=20)
    (tmp_path / "kb-rejugements.yaml").write_text(
        (tmp_path / "kb-rejugements.yaml").read_text(encoding="utf-8")
        + yaml.safe_dump([{"date": "2026-10-01", "motif": "éteinte", "ids": ["codex-commandes-recommentee"]}]),
        encoding="utf-8")
    code, out, err = _suivi(tmp_path, capsys, "--perimetre", "openai", "--json")
    assert code == 0 and "id inconnus" not in err
    o = json.loads(out)
    assert list(o) == ["openai"]
    v = o["openai"]
    assert v["plafond_effectif"] == 20 and v["dus_total_perimees"] == 25 and v["estimation"] is True
    assert v["passages_restants_estimes"] == 2  # ceil(25 / 20)
    active, eteinte = v["demandes"]
    assert active["active"] and len(active["ids_dus"]) == 25 and active["ids_recommentes"] == ["codex-commandes-recommentee"]
    assert sorted(active["ids_inconnus"]) == ["codex-fantome", "sans-prefixe"]
    assert not eteinte["active"] and eteinte["ids_dus"] == [] and eteinte["ids_recommentes"] == ["codex-commandes-recommentee"]
    # texte : une ligne par demande et par périmètre, estimation étiquetée
    code, out, _ = _suivi(tmp_path, capsys, "--perimetre", "claude")
    assert code == 0 and "claude-code-fantome" in out and "(estimation)" in out and "plafond effectif 10" in out
    assert out.count("| éteinte |") == 2, "les demandes sans fiche due dans le périmètre y sont éteintes"


def test_suivi_retour_a_10_apres_extinction(tmp_path, capsys):
    e = entree(commente=JOUR)
    cat.ecrire(tmp_path, "openai", {e["id"]: e})
    ecrire_demandes(tmp_path, [e["id"]], plafond=30)
    v = json.loads(_suivi(tmp_path, capsys, "--perimetre", "openai", "--json")[1])["openai"]
    assert v["plafond_effectif"] == 10 and v["passages_restants_estimes"] == 0
    assert v["demandes"][0]["active"] is False

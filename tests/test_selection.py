"""Sélection hebdomadaire de 3 à 5 essais (scripts/selection.py, deltalib/selection.py) : classement, retours, gel, caducité."""

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

import selection as cli
from deltalib import selection as sel

JOUR = date(2026, 10, 12)  # lundi de 2026-W42
SEMAINE = "2026-W42"


def fiche(ident, produit="claude-code", categorie="commandes", nom=None, pourquoi="Essayer pour voir.", verdict="tester",
          ajout="2026-09-01", exemple=None, usage=None, description="Une commande.", disponibilite=None, **autres):
    return {"id": ident, "produit": produit, "categorie": categorie, "nom": nom or ident, "usage": usage or f"/{ident}",
            "exemple": exemple, "description": description, "description_source": description, "disponibilite": disponibilite,
            "statut_usage": "inconnu", "recommandation": {"verdict": verdict, "pourquoi": pourquoi}, "commentee": True,
            "retiree": False, "historique": [{"date": ajout, "changement": "ajoutée à l'inventaire"}], **autres}


def depot(tmp_path: Path, fiches=(), priorites=("trading-sim d'abord", "ce qui allège les limites hebdomadaires"), elements=(),
          essais=None) -> Path:
    racine = tmp_path / "depot"
    for per in ("claude", "openai"):
        (racine / "docs" / "data" / "kb" / per).mkdir(parents=True)
    par_cat: dict[tuple, list] = {}
    for f in fiches:
        per = "claude" if f["produit"].startswith("claude") else "openai"
        par_cat.setdefault((per, f["categorie"]), []).append(f)
    for (per, cat), liste in par_cat.items():
        (racine / "docs" / "data" / "kb" / per / f"{cat}.json").write_text(json.dumps({"entrees": liste}), encoding="utf-8")
    for per in ("claude", "openai", "actu"):
        (racine / "docs" / "data" / per).mkdir(parents=True, exist_ok=True)
    if elements:
        (racine / "docs" / "data" / "claude" / "2026-10-10.json").write_text(json.dumps({"elements": list(elements)}), encoding="utf-8")
    (racine / "profil.yaml").write_text(yaml.safe_dump({"priorites": list(priorites)}, allow_unicode=True), encoding="utf-8")
    if essais:
        (racine / "kb-essais.yaml").write_text(yaml.safe_dump(essais), encoding="utf-8")
    return racine


def retours(racine: Path, *lignes):
    d = racine / "rapports" / "selection"
    d.mkdir(parents=True, exist_ok=True)
    (d / "retours.yaml").write_text(yaml.safe_dump([{"date": a, "id": b, "retour": c} for a, b, c in lignes]), encoding="utf-8")


def lancer(racine: Path, *args, jour="2026-10-12"):
    return cli.main(["--racine", str(racine), "--jour", jour, *args])


def ids_de(capsys, racine, *args, jour="2026-10-12"):
    capsys.readouterr()
    assert lancer(racine, "--json", *args, jour=jour) == 0
    return [e["id"] for e in json.loads(capsys.readouterr().out)["entrees"]]


def douze(prefixe="c", produit="claude-code", categories=None):
    return [fiche(f"{prefixe}{n:02d}", produit=produit, categorie=(categories or ["commandes", "parametres", "skills"])[n % 3])
            for n in range(12)]


# --- classement et raisons ---------------------------------------------------------------------------------------------

def test_budget_jamais_plus_de_cinq(tmp_path, capsys):
    racine = depot(tmp_path, douze() + douze("x", produit="codex"))
    assert len(ids_de(capsys, racine)) == 5
    assert len(ids_de(capsys, racine, "--taille", "3", "--refaire")) == 3
    for faux in ("6", "2", "0"):
        assert lancer(racine, "--taille", faux) == 2
    assert lancer(racine, "--revoir-apres", "-1") == 2


def test_priorites_du_profil_classent_et_expliquent(tmp_path, capsys):
    racine = depot(tmp_path, [
        fiche("a-neutre", categorie="skills", pourquoi="Rien de particulier."),
        fiche("b-trading", pourquoi="À tenter avant un audit de trading-sim."),
        fiche("c-limites", pourquoi="Montre les limites hebdomadaires."),
    ])
    capsys.readouterr()
    assert lancer(racine, "--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in doc["entrees"]] == ["b-trading", "c-limites", "a-neutre"]
    # priorité 1 (poids 2) : 1 mot propre × 2 pts × 2 = 4 ; priorité 2 (poids 1) : « limites » + « hebdomadaires » = 4 pts
    assert doc["entrees"][0]["classement"][0].startswith("priorité 1 « trading-sim d'abord » : trading-sim (+4)")
    assert doc["entrees"][1]["classement"][0].startswith("priorité 2 « ce qui allège les limites hebdomadaires »")
    assert doc["entrees"][2]["classement"] == ["aucun lien établi avec tes priorités : retenue faute de mieux"]
    assert doc["entrees"][0]["quoi"] == "Essayer b-trading : /b-trading"


def test_egalite_departagee_par_date_puis_id(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("z1", ajout="2026-08-01"), fiche("a2", ajout="2026-08-01"), fiche("m3", ajout="2026-08-20", categorie="skills")],
                   priorites=())
    assert ids_de(capsys, racine) == ["m3", "a2", "z1"]


def test_deux_entrees_au_plus_par_categorie(tmp_path, capsys):
    racine = depot(tmp_path, [fiche(f"p{n}", categorie="parametres", pourquoi="trading-sim") for n in range(4)]
                   + [fiche("autre", categorie="skills")])
    ids = ids_de(capsys, racine)
    assert len([i for i in ids if i.startswith("p")]) == 2 and "autre" in ids


def test_fiche_recente_et_verdict_utiliser_pesent(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("vieille", ajout="2026-07-01"), fiche("neuve", ajout="2026-10-08", categorie="skills"),
                              fiche("adopter", verdict="utiliser", categorie="mcp")], priorites=())
    capsys.readouterr()
    lancer(racine, "--json")
    doc = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in doc["entrees"]] == ["neuve", "adopter", "vieille"]
    assert "fiche ajoutée le 2026-10-08 (+3)" in doc["entrees"][0]["classement"]


def test_retire_commentee_et_ignorer_ne_sont_pas_candidats(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("ok"), fiche("retiree", retiree=True), fiche("ignoree", verdict="ignorer"),
                              fiche("sans-commentaire", commentee=False)])
    assert ids_de(capsys, racine) == ["ok"]


# --- retours ---------------------------------------------------------------------------------------------------------

def test_connu_sans_interet_et_utile_ne_reviennent_pas(tmp_path, capsys):
    racine = depot(tmp_path, [fiche(i, categorie=c) for i, c in (("a", "commandes"), ("b", "skills"), ("c", "mcp"), ("d", "plugins"))])
    retours(racine, ("2026-10-01", "a", "connu"), ("2026-10-01", "b", "sans_interet"), ("2026-10-01", "c", "utile"))
    assert ids_de(capsys, racine) == ["d"]


def test_a_revoir_revient_apres_le_delai_reglable(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("r"), fiche("n", categorie="skills")], priorites=())
    retours(racine, ("2026-10-01", "r", "a_revoir"))
    assert ids_de(capsys, racine) == ["n"]                                      # 11 jours : trop tôt (28 par défaut)
    assert sorted(ids_de(capsys, racine, "--revoir-apres", "10", "--refaire")) == ["n", "r"]
    assert ids_de(capsys, racine, "--revoir-apres", "28", "--refaire", jour="2026-10-12") == ["n"]
    assert sorted(ids_de(capsys, racine, "--refaire", jour="2026-10-29")) == ["n", "r"]  # 28 jours exactement


def test_dernier_retour_l_emporte(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x")])
    retours(racine, ("2026-09-01", "x", "connu"), ("2026-09-20", "x", "a_revoir"))
    assert ids_de(capsys, racine, "--revoir-apres", "7") == ["x"]


def test_retours_voisins_ponderent_le_classement(tmp_path, capsys):
    f = [fiche("passe-utile", categorie="parametres"), fiche("passe-vain", categorie="skills"),
         fiche("voisin-p", categorie="parametres"), fiche("voisin-s", categorie="skills")]
    racine = depot(tmp_path, f, priorites=())
    retours(racine, ("2026-10-01", "passe-utile", "utile"), ("2026-10-01", "passe-vain", "sans_interet"))
    capsys.readouterr()
    lancer(racine, "--json")
    doc = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in doc["entrees"]] == ["voisin-p", "voisin-s"]
    assert "retours passés sur claude-code/parametres (+2)" in doc["entrees"][0]["classement"]
    assert "retours passés sur claude-code/skills (-2)" in doc["entrees"][1]["classement"]


def test_essai_declare_exclut(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("essaye"), fiche("libre", categorie="skills")],
                   essais=[{"date": "2026-10-05", "id": "essaye", "par": "m-1"}])
    assert ids_de(capsys, racine) == ["libre"]


@pytest.mark.parametrize("contenu", ["- {date: '2026-10-01', id: x, retour: bof}", "- {date: hier, id: x, retour: connu}",
                                      "texte seul", "- {id: x, retour: connu}"])
def test_retours_mal_formes_arretent_au_lieu_de_s_ignorer(tmp_path, capsys, contenu):
    racine = depot(tmp_path, [fiche("x")])
    (racine / "rapports" / "selection").mkdir(parents=True)
    (racine / "rapports" / "selection" / "retours.yaml").write_text(contenu, encoding="utf-8")
    assert lancer(racine) == 1
    assert "retour" in capsys.readouterr().err
    assert not (racine / "rapports" / "selection" / f"{SEMAINE}.json").exists()


# --- gel par semaine -------------------------------------------------------------------------------------------------

def test_la_selection_est_figee_dans_la_semaine(tmp_path, capsys):
    racine = depot(tmp_path, douze())
    premiere = ids_de(capsys, racine)
    depot_fiches = racine / "docs" / "data" / "kb" / "claude" / "commandes.json"
    d = json.loads(depot_fiches.read_text())
    d["entrees"].append(fiche("nouvelle", pourquoi="trading-sim, limites hebdomadaires", ajout="2026-10-12"))
    depot_fiches.write_text(json.dumps(d))
    assert ids_de(capsys, racine, jour="2026-10-16") == premiere               # même semaine ISO : relue telle quelle
    assert "nouvelle" in ids_de(capsys, racine, "--refaire", jour="2026-10-16")
    assert ids_de(capsys, racine, jour="2026-10-19") != premiere               # semaine suivante : nouvelle sélection


def test_relecture_annote_le_retour_sans_toucher_au_fichier(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x")])
    ids_de(capsys, racine)
    fichier = racine / "rapports" / "selection" / f"{SEMAINE}.json"
    avant = fichier.read_text()
    retours(racine, ("2026-10-13", "x", "utile"))
    capsys.readouterr()
    lancer(racine, "--json")
    e = json.loads(capsys.readouterr().out)["entrees"][0]
    assert (e["retour"], e["retour_le"]) == ("utile", "2026-10-13") and fichier.read_text() == avant


def test_dry_run_n_ecrit_rien(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x")])
    assert lancer(racine, "--dry-run") == 0
    assert not (racine / "rapports").exists()


def test_fichier_de_semaine_corrompu_est_signale(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x")])
    d = racine / "rapports" / "selection"
    d.mkdir(parents=True)
    (d / f"{SEMAINE}.json").write_text("{pas du json", encoding="utf-8")
    assert lancer(racine) == 1 and "--refaire" in capsys.readouterr().err
    assert lancer(racine, "--refaire") == 0


def test_semaine_invalide(tmp_path):
    racine = depot(tmp_path, [fiche("x")])
    assert cli.main(["--racine", str(racine), "--semaine", "2026-W99"]) == 2
    assert cli.main(["--racine", str(racine), "--semaine", "2026-W41", "--jour", "2026-10-12"]) == 2


@pytest.mark.parametrize("jour,semaine", [("2026-10-19", "2026-W43"), ("2027-01-01", "2026-W53"),
                                         ("2027-01-04", "2027-W01"), ("2024-12-30", "2025-W01")])
def test_fichiers_et_contrat_iso_json_markdown(tmp_path, jour, semaine):
    racine = depot(tmp_path, douze())
    assert lancer(racine, jour=jour) == 0
    dossier = racine / sel.DOSSIER
    doc = json.loads((dossier / f"{semaine}.json").read_text())
    assert doc["semaine"] == semaine and doc["jour"] == jour
    lignes = (dossier / f"{semaine}.md").read_text().splitlines()
    assert len(lignes) == len(doc["entrees"]) == 5
    for ligne, entree in zip(lignes, doc["entrees"]):
        assert entree["nom"] in ligne and entree["pourquoi"] in ligne
        assert {"rang", "id", "quoi", "pourquoi", "caduque_si", "classement"} <= entree.keys()
    assert all("retour" not in e for e in doc["entrees"])
    (dossier / f"{semaine}.md").unlink()
    assert lancer(racine, jour=jour) == 0  # reconstitue le bref d'une sélection déjà figée
    assert (dossier / f"{semaine}.md").read_text().splitlines() == lignes


def test_markdown_aplatit_et_abrege_sans_changer_le_bref_existant(tmp_path):
    racine = depot(tmp_path, [fiche("x", nom="Titre\nsur deux lignes", pourquoi="Raison " * 100)])
    assert lancer(racine) == 0
    doc = sel.lire_figee(racine / sel.DOSSIER, SEMAINE)
    md = (racine / sel.DOSSIER / f"{SEMAINE}.md").read_text()
    assert len(md.splitlines()) == 1 and "Titre sur deux lignes" in md and "…" in md
    assert "[x]" in sel.rendre_bref(doc)


def test_semaine_figee_incoherente_est_refusee(tmp_path):
    racine = depot(tmp_path, [fiche("x")])
    assert lancer(racine) == 0
    chemin = racine / sel.DOSSIER / f"{SEMAINE}.json"
    doc = json.loads(chemin.read_text())
    doc["semaine"] = "2026-W99"
    chemin.write_text(json.dumps(doc))
    assert lancer(racine) == 1


def test_aucune_donnee_personnelle_dans_docs(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x")])
    avant = {p: p.read_bytes() for p in (racine / "docs").rglob("*") if p.is_file()}
    retours(racine, ("2026-10-01", "x", "a_revoir"))
    lancer(racine, "--refaire")
    assert {p: p.read_bytes() for p in (racine / "docs").rglob("*") if p.is_file()} == avant
    assert (racine / "rapports" / "selection" / f"{SEMAINE}.json").exists()


# --- présentations répétées -------------------------------------------------------------------------------------------

def test_proposee_sans_retour_perd_des_points_puis_ne_revient_plus(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("vu", pourquoi="trading-sim"), fiche("frais", categorie="skills")])

    def scores(jour):
        capsys.readouterr()
        assert lancer(racine, "--json", jour=jour) == 0
        return {e["id"]: e["score"] for e in json.loads(capsys.readouterr().out)["entrees"]}

    assert scores("2026-09-21") == {"vu": 4, "frais": 0}
    assert scores("2026-09-28") == {"vu": 1, "frais": -3}    # -3 par présentation antérieure sans retour
    assert scores("2026-10-05") == {"vu": -2, "frais": -6}
    assert scores("2026-10-12") == {}                        # 3 présentations sans retour : écartées


def test_un_retour_remet_le_compteur_de_presentations_a_zero(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("vu", pourquoi="trading-sim")])
    for j in ("2026-09-21", "2026-09-28", "2026-10-05"):
        ids_de(capsys, racine, jour=j)
    retours(racine, ("2026-10-06", "vu", "a_revoir"))
    assert ids_de(capsys, racine, "--revoir-apres", "1", jour="2026-10-12") == ["vu"]


# --- caducité --------------------------------------------------------------------------------------------------------

def test_caducite_tiree_de_la_fiche():
    assert sel.caducite(["Disponible depuis v2.1.234, à 200 $ par mois."]).startswith("caduque si change : version citée v2.1.234 ; prix cité 200 $ par mois")
    assert "limites ou tarifs cités (quota)" in sel.caducite(["Un quota hebdomadaire s'applique."])
    assert "disponibilité (forfait Max uniquement)" in sel.caducite(["x"], disponibilite="forfait Max uniquement")
    assert sel.caducite(["Version 3.4.5 de l'outil"], version="9.9.9").endswith("version citée v9.9.9, v3.4.5")


def test_caducite_absente_est_dite_sans_rien_inventer():
    c = sel.caducite(["Une commande qui affiche le répertoire courant."])
    assert c == sel.SANS_CADUCITE and "non renseignée" in c


def test_caducite_dans_la_selection(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("avec", description="Depuis v2.1.7, limite de 5 sessions.", categorie="skills"),
                              fiche("sans", description="Affiche le dossier.")], priorites=())
    capsys.readouterr()
    lancer(racine, "--json")
    par_id = {e["id"]: e for e in json.loads(capsys.readouterr().out)["entrees"]}
    assert "version citée v2.1.7" in par_id["avec"]["caduque_si"]
    assert par_id["sans"]["caduque_si"] == sel.SANS_CADUCITE


# --- nouveautés de la veille -----------------------------------------------------------------------------------------

def element(ident, impact="moyen", action="Essayer `codex --version`.", certitude="officiel", **autres):
    return {"id": ident, "produit": "claude", "titre": f"Titre {ident}", "version": None, "impact": impact, "certitude": certitude,
            "date_publication": "2026-10-09", "resume": "Résumé.", "pour_toi": "Concerne trading-sim.",
            "action": {"description": action}, **autres}


def test_nouveautes_de_la_veille_entrent_avec_pour_toi_et_version(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("f", categorie="skills")], elements=[
        element("e-fort", "fort", version="1.2.3"), element("e-faible", "faible"), element("e-rumeur", "fort", certitude="non_confirme"),
        element("e-sans-action", "fort", action=None),
        element("e-reverif", "fort", action="Revérifier le 09/10/2026 le forfait ; aucune échéance publiée.")])
    capsys.readouterr()
    lancer(racine, "--json")
    doc = json.loads(capsys.readouterr().out)
    par_id = {e["id"]: e for e in doc["entrees"]}
    assert set(par_id) == {"e-fort", "f"}
    e = par_id["e-fort"]
    assert e["origine"] == "veille" and e["pourquoi"] == "Concerne trading-sim."
    assert e["caduque_si"] == "caduque si change : version citée v1.2.3"
    assert "nouveauté de la veille, impact fort (+7)" in e["classement"]


def test_veille_trop_ancienne_ou_plafonnee(tmp_path, capsys):
    elements = [element(f"e{n}", "fort") for n in range(5)]
    racine = depot(tmp_path, [fiche(f"f{n}", categorie=("skills", "mcp", "plugins")[n % 3]) for n in range(4)], elements=elements)
    ids = ids_de(capsys, racine)
    assert len([i for i in ids if i.startswith("e")]) == sel.VEILLE_MAX and len(ids) == 5
    assert ids_de(capsys, racine, "--refaire", jour="2026-10-20") == ids_de(capsys, racine, "--refaire", jour="2026-10-20") \
        and not [i for i in ids_de(capsys, racine, "--refaire", jour="2026-10-20") if i.startswith("e")]  # plus de 7 jours


# --- sorties et cas limites ------------------------------------------------------------------------------------------

def test_sortie_texte_trois_lignes_par_entree_et_bref(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x", pourquoi="Pour trading-sim.", exemple="/x --vite")])
    capsys.readouterr()
    assert lancer(racine) == 0
    sortie = capsys.readouterr().out.splitlines()
    assert sortie[1] == "1. Essayer x : /x --vite" and sortie[2] == "   Pourquoi : Pour trading-sim."
    assert sortie[3] == f"   {sel.SANS_CADUCITE[0].upper()}{sel.SANS_CADUCITE[1:]}"
    assert "Classement" not in "\n".join(sortie) and "écrite" in sortie[4]
    assert lancer(racine, "--bref") == 0
    assert capsys.readouterr().out.splitlines() == ["Sélection 2026-W42 (1 essais)", "1. Essayer x : /x --vite [x]"]
    assert lancer(racine, "--expliquer") == 0 and "Classement (" in capsys.readouterr().out


def test_aucun_candidat_est_signale(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x", verdict="ignorer")])
    capsys.readouterr()
    assert lancer(racine) == 0
    assert "! AVERTISSEMENT aucun candidat" in capsys.readouterr().out
    assert lancer(racine, "--bref") == 0 and "aucune entrée à proposer" in capsys.readouterr().out


def test_base_absente_est_une_erreur(tmp_path, capsys):
    racine = depot(tmp_path, [])
    assert lancer(racine) == 1 and "base de référence vide" in capsys.readouterr().err


def test_priorites_vides(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x")], priorites=())
    capsys.readouterr()
    lancer(racine, "--json")
    assert json.loads(capsys.readouterr().out)["entrees"][0]["classement"] == ["aucun lien établi avec tes priorités : retenue faute de mieux"]


def test_mots_de_priorite():
    mots = {m: p for m, _, p in sel.mots_de_priorite("ce qui débloque Codex en CLI + tmux + remote control")}
    assert mots == {"debloque": 2, "codex": 1, "cli": 1, "tmux": 2, "remote": 2, "control": 1}


def test_la_sortie_publique_ne_porte_aucun_identifiant_de_mission(tmp_path, capsys):
    racine = depot(tmp_path, [fiche("x")], essais=[{"date": "2026-10-05", "id": "autre", "par": "m-df96b681179f"}])
    lancer(racine, "--refaire")
    assert "m-df96" not in (racine / "rapports" / "selection" / f"{SEMAINE}.json").read_text()

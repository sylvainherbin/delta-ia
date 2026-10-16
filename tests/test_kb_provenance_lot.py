"""D128 : provenance des fiches qui recommandent (D127) reprise en masse, mode Batch, par les crédits API (A1).

A1 est remplacé par un faux module (`delta.operer.credits_api`) : aucun appel réseau, aucune clé."""

import json
import sys
import types

import pytest

import provenance_lot as cli
import valider
from deltalib.kb import catalogue as cat
from deltalib.kb import provenance_lot as pl
from deltalib.kb.modeles import EntreeExtraite

URL = "https://code.claude.com/docs/en/commands"
CONTEXTE = ("# Profil\n<!-- ctx-id: profil -->\n\nSylvain pilote ses agents depuis l'iPhone.\n\n"
            "## Projets\n<!-- ctx-id: projets -->\n\nDelta-IA, veille quotidienne.\n")
LU_LE = "2026-10-15"


def entree(nom, verdict="utiliser", sections=None, provenance=None):
    e = cat.nouvelle_entree(EntreeExtraite(
        produit="claude-code", categorie="commandes", nom=nom, usage=f"/{nom}", description_source=f"Run /{nom}.",
        url=URL, libelle="commands", origine="cc-commandes", usage_nature="syntaxe"), "2026-09-23")
    c = {"description": "Reprend une session de travail dans le projet de veille.", "statut_usage": "inconnu",
         "recommandation": {"verdict": verdict, "pourquoi": "Utile pour la veille Delta-IA."}, "contexte_sections": {}}
    assert cat.appliquer_commentaires({e["id"]: e}, {e["id"]: c}, jour="2026-10-01", contexte="a" * 40) == []
    if sections is not None:
        e["contexte_sections"] = sections
    if provenance:
        e["provenance"] = provenance
    return e


def extraites_de(entrees):
    return {e["id"]: EntreeExtraite(produit=e["produit"], categorie=e["categorie"], nom=e["nom"], usage=e["usage"],
                                    description_source=e["description_source"], url=URL, libelle="commands",
                                    origine="cc-commandes", usage_nature="syntaxe") for e in entrees}


@pytest.fixture
def depot(tmp_path):
    (tmp_path / "CONTEXTE.md").write_text(CONTEXTE, encoding="utf-8")
    from deltalib.contexte import empreintes
    sha = empreintes(tmp_path)
    ents = [entree(f"c{i:02}", "tester" if i % 2 else "utiliser",
                   sections={"projets": {"sha1": sha["projets"], "pourquoi": "Veille."}}) for i in range(14)]
    ents.append(entree("ign", "ignorer"))
    ents.append(entree("deja", provenance=[{"affirmation": "x", "source": URL, "releve_le": "2026-10-01", "caduc_si": "y"}]))
    cat.ecrire(tmp_path, "claude", {e["id"]: e for e in ents})
    kb = tmp_path / "raw" / "kb" / "claude-code"
    kb.mkdir(parents=True)
    (kb / "empreintes.json").write_text(json.dumps({"cc-commandes/page": {
        "url": URL + ".md", "empreinte": "0", "recupere_le": f"{LU_LE}T03:00:00+00:00"}}), encoding="utf-8")
    return tmp_path, {e["id"]: e for e in ents}


def preparer(racine, ents, **kw):
    return pl.preparer(racine, "claude", extraites=extraites_de(ents.values()), horodatage=kw.pop("horodatage", "20261016-100000"), **kw)


def reponse(custom_id, sortie, stop="end_turn", usage=None):
    return {"custom_id": custom_id, "result": {"type": "succeeded", "message": {
        "stop_reason": stop, "content": [{"type": "text", "text": json.dumps(sortie, ensure_ascii=False)}],
        "usage": usage or {"input_tokens": 1500, "output_tokens": 400, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 900}}}}


def bonne(source=URL + "#c00"):
    return {"recommandation_tient": True, "motif": "", "provenance": [
        {"affirmation": "La commande existe dans la page des commandes.", "source": source, "caduc_si": "La commande disparaît."},
        {"affirmation": "Delta-IA fait une veille quotidienne.", "source": "contexte:projets", "caduc_si": "CONTEXTE.md ne décrit plus Delta-IA."}]}


# ----------------------------------------------------------------------------------------------- préparation

def test_premier_lot_limite_et_requetes_batch(depot):
    racine, ents = depot
    m = preparer(racine, ents, maximum=50)
    assert m["premier"] and len(m["fiches"]) == pl.PREMIER_LOT_MAX, "premier lot plafonné à 10 malgré --max 50"
    assert "claude-code-commandes-ign" not in m["fiches"] and "claude-code-commandes-deja" not in m["fiches"]
    f = m["fiches"]["claude-code-commandes-c00"]
    assert f["releve_le"] == LU_LE and f["urls"] == [URL] and f["sections"] == ["projets"]
    reqs = pl.charger_requetes(racine, m)
    assert len(reqs) == 10 and reqs[0]["custom_id"] == "f0001"
    p = reqs[0]["params"]
    assert p["model"] == pl.MODELE_DEFAUT and p["output_config"]["format"]["type"] == "json_schema"
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}, "consigne commune mise en cache"
    contenu = json.loads(p["messages"][0]["content"])
    assert contenu["contexte"]["projets"]["texte"] == "Delta-IA, veille quotidienne."
    assert contenu["sources_permises"] == [URL, "contexte:projets"]
    assert "releve_le" not in json.dumps(contenu), "le modèle ne fournit jamais la date de relevé"


def test_lot_en_cours_et_suite_non_autorisee_refuses(depot):
    racine, ents = depot
    m = preparer(racine, ents)
    with pytest.raises(pl.LotRefuse, match="lot en cours"):
        preparer(racine, ents, horodatage="20261016-100001")
    m["statut"] = "applique"
    pl.ecrire_manifeste(racine, m)
    with pytest.raises(pl.LotRefuse, match="présenté à Sylvain"):
        preparer(racine, ents, horodatage="20261016-100002")
    with pytest.raises(pl.LotRefuse):
        pl.autoriser(racine, "  ")
    pl.autoriser(racine, "Sylvain via Delta-pilote", jour="2026-10-17")
    m2 = preparer(racine, ents, horodatage="20261016-100003")
    assert not m2["premier"] and len(m2["fiches"]) == 14, "suite autorisée : toutes les fiches dues"


def test_fiches_ecartees_sans_lecture_datee_ou_documentation_changee(depot):
    racine, ents = depot
    ext = extraites_de(ents.values())
    ext["claude-code-commandes-c00"].usage = "/c00 --nouveau"
    del ext["claude-code-commandes-c02"]
    m = pl.preparer(racine, "claude", maximum=5, extraites=ext, horodatage="20261016-100000")
    assert "documentation en cache différente" in m["ecartees"]["claude-code-commandes-c00"]
    assert "absente de la documentation" in m["ecartees"]["claude-code-commandes-c02"]
    assert len(m["fiches"]) == 5
    (racine / "raw/kb/claude-code/empreintes.json").write_text("{}", encoding="utf-8")
    m["statut"] = "abandonne"
    pl.ecrire_manifeste(racine, m)
    with pytest.raises(pl.LotRefuse, match="jour de lecture"):
        preparer(racine, ents, horodatage="20261016-100001")


def test_section_modifiee_ecarte_la_fiche(depot):
    racine, ents = depot
    (racine / "CONTEXTE.md").write_text(CONTEXTE.replace("veille quotidienne", "veille"), encoding="utf-8")
    with pytest.raises(pl.LotRefuse, match="section projets modifiée"):
        preparer(racine, ents)


# ----------------------------------------------------------------------------------------------- résultats et application

def test_application_pose_la_provenance_et_trie_les_refus(depot):
    racine, ents = depot
    m = preparer(racine, ents)
    ids = {f["custom_id"]: k for k, f in m["fiches"].items()}
    res = [reponse("f0001", bonne()),
           reponse("f0002", {"recommandation_tient": False, "motif": "La page ne parle plus de cette option.", "provenance": []}),
           reponse("f0003", bonne(source="https://ailleurs.example/doc")),
           reponse("f0004", bonne(source="contexte:profil")),
           reponse("f0005", bonne(), stop="max_tokens"),
           {"custom_id": "f0006", "result": {"type": "expired"}},
           reponse("f0007", {"recommandation_tient": True, "motif": "", "provenance": []}),
           reponse("f0008", bonne()), reponse("f0008", bonne())]
    b = pl.appliquer(racine, m, res, jour="2026-10-16")
    assert b["posees"] == sorted([ids["f0001"], ids["f0008"]])
    assert set(b["a_revoir"]) == {ids["f0002"]}
    assert "source non envoyée" in b["rejets"][ids["f0003"]] and "source non envoyée" in b["rejets"][ids["f0004"]]
    assert "max_tokens" in b["rejets"][ids["f0005"]] and b["rejets"][ids["f0006"]] == "requête expired"
    assert "liste de 1 à 8" in b["rejets"][ids["f0007"]]
    assert b["rejets"][ids["f0009"]] == "aucun résultat"
    assert b["jetons"]["input_tokens"] == 1500 * 7 and b["compte"]["expired"] == 1
    e = cat.charger(racine, "claude")[ids["f0001"]]
    assert all(a["releve_le"] == LU_LE for a in e["provenance"]), "date de lecture de la page, pas celle du modèle"
    assert e["historique"][-1] == {"date": "2026-10-16", "changement": "provenance ajoutée"}
    assert e["recommandation"] == ents[ids["f0001"]]["recommandation"], "la recommandation n'est jamais modifiée"
    a_revoir = cat.charger(racine, "claude")[ids["f0002"]]
    assert "provenance" not in a_revoir or not a_revoir["provenance"]
    assert pl.lots(racine)[0]["statut"] == "applique"
    assert valider.main(["--perimetre", "claude", "--racine", str(racine), "--kb"]) == 0


def test_fiche_modifiee_entre_preparation_et_application_est_sautee(depot):
    racine, ents = depot
    m = preparer(racine, ents)
    entrees = cat.charger(racine, "claude")
    k1, k2 = [k for k, f in m["fiches"].items() if f["custom_id"] in ("f0001", "f0002")]
    entrees[k1]["recommandation"]["pourquoi"] = "Révisé entre-temps."
    entrees[k2]["provenance"] = [{"affirmation": "x", "source": URL, "releve_le": "2026-10-16", "caduc_si": "y"}]
    cat.ecrire(racine, "claude", entrees)
    b = pl.appliquer(racine, m, [reponse("f0001", bonne()), reponse("f0002", bonne())], jour="2026-10-16")
    assert b["posees"] == [] and "révisée" in b["sautees"][k1] and "plus due" in b["sautees"][k2]


# ----------------------------------------------------------------------------------------------- CLI et pont A1

@pytest.fixture
def faux_a1(monkeypatch):
    soumis, etat = [], {"resultats": None}
    mod = types.ModuleType("delta.operer.credits_api")
    mod.soumettre_lot = lambda usage, requetes: soumis.append((usage, requetes)) or {"id": "msgbatch_test"}
    mod.relever_lot = lambda ident: etat["resultats"]
    for nom, m in (("delta", types.ModuleType("delta")), ("delta.operer", types.ModuleType("delta.operer")),
                   ("delta.operer.credits_api", mod)):
        monkeypatch.setitem(sys.modules, nom, m)
    couts = iter([0.5, 0.5612])
    monkeypatch.setattr(cli, "cout_usage", lambda usage=pl.USAGE_A1: next(couts))
    return soumis, etat


def test_cli_chaine_complete_avec_cout_par_lot(depot, faux_a1, monkeypatch, capsys):
    racine, ents = depot
    soumis, etat = faux_a1
    monkeypatch.setattr(pl, "extraction_courante", lambda r, p: extraites_de(ents.values()))
    args = ["--racine", str(racine)]
    assert cli.main(["preparer", "--perimetre", "claude", *args]) == 0
    assert cli.main(["soumettre", *args]) == 0
    assert soumis[0][0] == "delta-ia-provenance" and len(soumis[0][1]) == 10
    assert cli.main(["relever", *args]) == cli.CODE_EN_COURS
    etat["resultats"] = [reponse(f"f{i:04d}", bonne()) for i in range(1, 11)]
    assert cli.main(["relever", *args]) == 0
    capsys.readouterr()
    assert cli.main(["appliquer", *args]) == 0
    sortie = capsys.readouterr().out
    assert "10/10 provenances posées" in sortie and "0.0612 $ (A1" in sortie
    assert 'delta-kb(claude): provenance — 10 entrées' in sortie and "présenter à Sylvain" in sortie
    assert cli.main(["preparer", "--perimetre", "claude", *args]) == 1
    assert "présenté à Sylvain" in capsys.readouterr().err
    assert cli.main(["etat", *args]) == 0
    assert "4 fiches utiliser/tester sans provenance" in capsys.readouterr().out


def test_cli_credits_epuises_rend_le_code_5(depot, faux_a1, monkeypatch, capsys):
    racine, ents = depot
    monkeypatch.setattr(pl, "extraction_courante", lambda r, p: extraites_de(ents.values()))

    def epuise(usage, requetes):
        raise SystemExit(5)
    monkeypatch.setattr(sys.modules["delta.operer.credits_api"], "soumettre_lot", epuise)
    assert cli.main(["preparer", "--perimetre", "claude", "--racine", str(racine)]) == 0
    assert cli.main(["soumettre", "--racine", str(racine)]) == cli.CODE_CREDITS
    assert pl.lot_courant(racine)["statut"] == "prepare"


def test_cli_appliquer_refuse_pendant_la_chaine(depot, monkeypatch, capsys):
    racine, ents = depot
    preparer(racine, ents)
    monkeypatch.setattr(cli.garde, "verrou_chaine", lambda r: (True, 4242))
    assert cli.main(["appliquer", "--racine", str(racine)]) == 1
    assert "chaîne de nuit en cours" in capsys.readouterr().err

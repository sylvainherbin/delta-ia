"""Pont du bilan OPÉRER des réglages vers les constats internes des fiches de modèles."""
import json
import shutil
import sys
from datetime import date

import pytest
import yaml
from conftest import RACINE

import reglages_pont as rp

JOUR = date(2026, 10, 22)

FAMILLE = """date_releve: '2026-10-20'
famille: claude
executants_operer:
- claude
- claude:<role>
- claude-cloud
modeles:
- modele: claude-sonnet-5-5
  modele_operer: sonnet
  aliases_modele:
  - sonnet
  - claude-sonnet-5-5
  nom: Claude Sonnet 5.5
  constats_internes:
  - date: '2026-10-21'
    titre: Constat manuel
    constat: 'Un constat écrit à la main,
      sur deux lignes.'
    source: Observation interne
  efforts:
  - effort: high
  - effort: medium
  sources:
  - url: https://exemple.test
- modele: claude-opus-5-5
  modele_operer: opus
  aliases_modele:
  - opus
  constats_internes: []
  efforts:
  - effort: high
  sources:
  - url: https://exemple.test
"""


@pytest.fixture
def depot(tmp_path):
    (tmp_path / "kb-modeles").mkdir()
    (tmp_path / "kb-modeles" / "claude.yaml").write_text(FAMILLE, encoding="utf-8")
    return tmp_path


def mission(i, relue=True, ok=True, corrections=0, duree=600.0, echec=False, remplacee=False, defauts=None, jetons=None):
    return {"mission": f"m-{i:012x}", "relue": relue, "ok_premier_tour": ok if relue else False, "corrections": corrections,
            "echec": echec, "remplacee": remplacee, "duree_a_relire_s": duree,
            "defauts_declares": 1 if defauts else 0, "defauts": defauts or {"BLOQUANT": None, "A_NOTER": None},
            "jetons_mesures": jetons}


def groupe(missions, executant="claude:dev-x", modele="sonnet", effort="high", nature="code"):
    return {"nature": nature, "executant": executant, "modele": modele, "effort": effort, "details": missions}


def export(*groupes, jusqu_au="2026-10-22T11:00:00+02:00", missions=None):
    return {"version": 1, "vue": "reglages_bilan", "jusqu_au": jusqu_au,
            "missions": missions if missions is not None else sum(len(g["details"]) for g in groupes), "groupes": list(groupes)}


def ecrire(dossier, doc, nom="bilan.json"):
    chemin = dossier / nom
    chemin.write_text(json.dumps(doc), encoding="utf-8")
    return chemin


def lancer(depot, doc, source="principal", **kw):
    return rp.mettre_a_jour(depot, {source: ecrire(depot, doc, f"{source}.json")}, aujourd_hui=JOUR, **kw)


def constats(depot, fiche="claude-sonnet-5-5"):
    doc = yaml.safe_load((depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8"))
    return next(m for m in doc["modeles"] if m["modele"] == fiche)["constats_internes"]


def six_missions(debut=0, **kw):
    return [mission(debut + i, **kw) for i in range(6)]


def test_effectif_sous_le_seuil_aucun_constat(depot):
    avant = (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8")
    r = lancer(depot, export(groupe([mission(i) for i in range(4)])))
    assert (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8") == avant
    assert r["ecrits"] == []
    assert r["ecartes"]["sous_seuil"] == [{"source": "principal", "fiche": "claude-sonnet-5-5", "effort": "high", "nature": "code",
                                           "missions": 4, "relues": 4}]


def test_seuil_compte_les_missions_relues_pas_les_ouvertes(depot):
    missions = [mission(i) for i in range(3)] + [mission(10 + i, relue=False) for i in range(5)]
    r = lancer(depot, export(groupe(missions)))
    assert r["ecrits"] == [] and r["ecartes"]["sous_seuil"][0]["relues"] == 3


def test_constat_manuel_conserve_et_automatique_ajoute(depot):
    r = lancer(depot, export(groupe(six_missions())))
    assert r["ecrits"] == ["claude-sonnet-5-5|auto:principal:high:code"]
    cs = constats(depot)
    assert cs[0] == {"date": "2026-10-21", "titre": "Constat manuel",
                     "constat": "Un constat écrit à la main, sur deux lignes.", "source": "Observation interne"}
    assert cs[1]["cle_auto"] == "auto:principal:high:code" and cs[1]["date"] == "2026-10-22"
    # le bloc manuel est recopié tel quel, pas reformaté
    assert "    constat: 'Un constat écrit à la main,\n      sur deux lignes.'\n" in (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8")


def test_second_passage_idempotent_meme_si_le_jour_change(depot):
    doc = export(groupe(six_missions()))
    lancer(depot, doc)
    apres = (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8")
    r = lancer(depot, doc)
    assert r["ecrits"] == [] and r["inchanges"] == ["claude-sonnet-5-5|auto:principal:high:code"]
    assert (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8") == apres
    doc["jusqu_au"] = "2026-10-29T11:00:00+02:00"
    lancer(depot, doc)
    assert (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8") == apres  # seul le jour changeait


def test_constat_automatique_remplace_pas_duplique(depot):
    lancer(depot, export(groupe(six_missions())))
    r = lancer(depot, export(groupe(six_missions() + six_missions(debut=50, ok=False)), jusqu_au="2026-10-29T11:00:00+02:00"))
    assert r["ecrits"] == ["claude-sonnet-5-5|auto:principal:high:code"]
    auto = [c for c in constats(depot) if c.get("cle_auto")]
    assert len(auto) == 1 and auto[0]["date"] == "2026-10-29" and "12 missions, dont 12 relues" in auto[0]["constat"]
    assert len(constats(depot)) == 2  # le manuel est toujours là


def test_une_cle_par_source_et_par_nature(depot):
    lancer(depot, export(groupe(six_missions()), groupe(six_missions(debut=20), nature="relecture")))
    rp.mettre_a_jour(depot, {"essai": ecrire(depot, export(groupe(six_missions(debut=40))), "essai.json")}, aujourd_hui=JOUR)
    cles = sorted(c["cle_auto"] for c in constats(depot) if c.get("cle_auto"))
    assert cles == ["auto:essai:high:code", "auto:principal:high:code", "auto:principal:high:relecture"]
    assert "instance d'essai" in next(c for c in constats(depot) if c.get("cle_auto") == "auto:essai:high:code")["titre"]


def test_alias_d_une_meme_fiche_et_roles_confondus(depot):
    g1 = groupe(six_missions(), executant="claude:dev-a", modele="sonnet")
    g2 = groupe(six_missions(debut=30), executant="claude-cloud", modele="claude-sonnet-5-5")
    lancer(depot, export(g1, g2))
    auto = [c for c in constats(depot) if c.get("cle_auto")]
    assert len(auto) == 1 and "12 missions, dont 12 relues" in auto[0]["constat"]


def test_mission_presente_dans_deux_groupes_comptee_une_fois(depot):
    ms = six_missions()
    lancer(depot, export(groupe(ms, executant="claude:a"), groupe(ms[:2], executant="claude:b")))
    assert "6 missions, dont 6 relues" in next(c for c in constats(depot) if c.get("cle_auto"))["constat"]


def test_couple_sans_fiche_signale_pas_devine(depot):
    avant = (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8")
    r = lancer(depot, export(
        groupe(six_missions(), modele="haiku"),                                  # modèle absent de la famille
        groupe(six_missions(debut=10), effort="max"),                            # effort absent de la fiche
        groupe(six_missions(debut=20), executant="inconnu:x"),                   # exécutant d'aucune famille
    ))
    assert (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8") == avant
    assert r["ecartes"]["sans_fiche"] == {"principal|claude|haiku|high": 6, "principal|claude|sonnet|max": 6,
                                          "principal|famille inconnue|sonnet|high": 6}


def test_alias_ambigu_dans_la_famille_pas_devine(depot):
    chemin = depot / "kb-modeles/claude.yaml"
    chemin.write_text(chemin.read_text(encoding="utf-8").replace("  - opus\n", "  - opus\n  - sonnet\n"), encoding="utf-8")
    r = lancer(depot, export(groupe(six_missions(), modele="sonnet")))
    assert r["ecrits"] == [] and "principal|claude|sonnet|high" in r["ecartes"]["sans_fiche"]


def test_nature_inconnue_et_reglage_absent_ecartes_avec_leur_compte(depot):
    r = lancer(depot, export(groupe(six_missions(), nature="inconnue"), groupe(six_missions(debut=20), modele=None, effort=None)))
    assert r["ecrits"] == [] and r["ecartes"]["nature_inconnue"] == 6 and r["ecartes"]["sans_reglage"] == 6


def test_valeurs_inconnues_restent_inconnues(depot):
    ms = [mission(i, corrections=None, duree=None) for i in range(6)]
    lancer(depot, export(groupe(ms)))
    txt = next(c for c in constats(depot) if c.get("cle_auto"))["constat"]
    assert "Corrections moyennes avant acceptation : inconnu." in txt
    assert "Durée médiane jusqu'à la relecture : inconnue." in txt
    assert "jetons mesurés pour 0 missions sur 6" in txt


def test_mediane_et_parts_calculees_sur_les_missions(depot):
    ms = [mission(i, ok=i < 4, corrections=i % 2, duree=60.0 * (i + 1), echec=(i == 0), defauts={"BLOQUANT": 1, "A_NOTER": 2})
          for i in range(6)]
    lancer(depot, export(groupe(ms)))
    txt = next(c for c in constats(depot) if c.get("cle_auto"))["constat"]
    assert "Acceptées dès le premier tour : 4 sur 6 (67 %)" in txt
    assert "Corrections moyennes avant acceptation : 0,50" in txt
    assert "Échecs : 1 sur 6" in txt
    assert "Durée médiane jusqu'à la relecture : 4 min (6 missions mesurées)" in txt  # médiane de 60..360 s = 210 s
    assert "bloquants 1,0, à noter 2,0" in txt
    assert "Effectif réduit" in txt


def test_aucun_chemin_machine_compte_ni_identifiant_dans_le_texte_publie(depot):
    ms = [mission(i) for i in range(12)]
    g = groupe(ms, executant="claude:dev-herbin-hp-essai", nature="code")
    lancer(depot, export(g, groupe(ms, executant="claude:/home/herbin/projets/x", nature="relecture")))
    auto = "\n".join(c["constat"] + c["titre"] + c["source"] for c in constats(depot) if c.get("cle_auto"))
    for interdit in ("m-0000000000", "/home", "~/", "herbin", "hp-essai", "dev-", "10.42", "ssh", "sudo", "@"):
        assert interdit not in auto, interdit


def test_garde_refuse_un_texte_prive():
    for t in ("voir /home/herbin/x", "mission m-0123456789ab", "machine 10.42.0.1", "ssh herbin@hote", "~/projets"):
        with pytest.raises(rp.ErreurPont):
            rp.refuser_si_prive(t)
    rp.refuser_si_prive("Observation interne automatique, poste principal, 12 missions, 54 %.")


def test_source_en_echec_visible_et_ses_constats_conserves(depot, capsys):
    lancer(depot, export(groupe(six_missions())), source="principal")
    avant = (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8")
    illisible = depot / "casse.json"
    illisible.write_text("{pas du json", encoding="utf-8")
    r = rp.mettre_a_jour(depot, {"principal": illisible}, aujourd_hui=JOUR)
    assert r["sources"] == [{"source": "principal", "statut": "echec", "motif": r["sources"][0]["motif"]}]
    assert "export illisible" in r["sources"][0]["motif"]
    assert r["obsoletes"] == [] and (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8") == avant
    # mauvaise vue : pas un export de bilan
    faux = ecrire(depot, {"version": 1, "vue": "autre", "groupes": []}, "faux.json")
    assert rp.mettre_a_jour(depot, {"essai": faux}, aujourd_hui=JOUR)["sources"][0]["statut"] == "echec"


def test_export_vide_est_une_reponse_pas_un_echec(depot):
    r = lancer(depot, export(missions=0), source="essai")
    assert r["sources"][0]["statut"] == "ok" and r["sources"][0]["missions"] == 0 and r["ecrits"] == []


def test_cellule_non_renouvelee_signalee_obsolete_et_conservee(depot):
    lancer(depot, export(groupe(six_missions()), groupe(six_missions(debut=20), nature="relecture")))
    r = lancer(depot, export(groupe(six_missions())))
    assert r["obsoletes"] == ["claude-sonnet-5-5|auto:principal:high:relecture"]
    assert any(c.get("cle_auto") == "auto:principal:high:relecture" for c in constats(depot))


def test_collecter_range_les_exports_et_note_les_echecs(tmp_path, monkeypatch):
    bilan = export(groupe(six_missions()))
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"principal": [sys.executable, "-c", f"print({json.dumps(json.dumps(bilan))})"],
                               "essai": [sys.executable, "-c", "import sys; sys.exit(255)"]}), encoding="utf-8")
    res = rp.collecter(tmp_path / "bilans", config=cfg)
    assert [(r["source"], r["statut"]) for r in res] == [("principal", "ok"), ("essai", "echec")]
    assert res[1]["motif"] == "code 255" and res[1]["chemin"] is None
    assert json.loads(open(res[0]["chemin"], encoding="utf-8").read())["vue"] == "reglages_bilan"
    assert res[0]["chemin"].endswith("-principal.json") and len(list((tmp_path / "bilans").iterdir())) == 1


def test_collecter_source_non_configuree_est_un_echec_pas_un_vide(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"principal": [sys.executable, "-c", "print('pas du json')"]}), encoding="utf-8")
    res = rp.collecter(tmp_path / "b", config=cfg)
    assert res[0]["statut"] == "echec" and "sortie inattendue" in res[0]["motif"]
    assert res[1] == {"source": "essai", "statut": "echec", "chemin": None, "motif": "commande non configurée", "missions": None}


def test_cli_code_3_quand_une_source_echoue(depot, capsys):
    ok = ecrire(depot, export(groupe(six_missions())), "ok.json")
    assert rp.main(["maj", "--racine", str(depot), "--export", f"principal={ok}"]) == 0
    casse = depot / "casse.json"
    casse.write_text("x", encoding="utf-8")
    assert rp.main(["maj", "--racine", str(depot), "--export", f"principal={ok}", "--export", f"essai={casse}"]) == 3
    assert "source essai : echec" in capsys.readouterr().out
    assert rp.main(["maj", "--racine", str(depot)]) == 2


def test_dry_run_n_ecrit_rien(depot):
    avant = (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8")
    r = lancer(depot, export(groupe(six_missions())), dry_run=True)
    assert r["ecrits"] and (depot / "kb-modeles/claude.yaml").read_text(encoding="utf-8") == avant


def test_catalogue_public_valide_sans_cle_auto_sur_les_vraies_fiches(tmp_path):
    from deltalib.kb import fiches_modeles as fm
    shutil.copytree(RACINE / "kb-modeles", tmp_path / "kb-modeles")
    rp.mettre_a_jour(tmp_path, {"principal": ecrire(tmp_path, export(
        groupe(six_missions(), executant="codex:x", modele="gpt-6.1-sol", effort="high"),
        groupe(six_missions(debut=20), modele="claude-sonnet-5-5", effort="medium"),
        groupe(six_missions(debut=40), executant="antigravity", modele="claude-sonnet-5-5", effort="medium")))}, aujourd_hui=JOUR)
    d = fm.construire_modeles(tmp_path)
    assert "cle_auto" not in json.dumps(d)
    for fiche in ("gpt-6.1-sol", "claude-sonnet-5-5", "antigravity-claude-sonnet-5-5"):
        assert any(c["titre"].startswith("Bilan automatique") for c in d["modeles"][fiche]["constats_internes"]), fiche
    # le constat manuel de la vraie fiche Sonnet 5.5 high reste en tête
    assert d["modeles"]["claude-sonnet-5-5"]["constats_internes"][0]["titre"].startswith("Développement borné")

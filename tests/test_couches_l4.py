"""Delta-IA en deux couches, lot L4 : instantané privé du bilan OPÉRER des réglages, essais OPÉRER et projection
modèle × effort sur les couples communs (conception §2.2.1). Source simulée par un exécuteur de test : aucune commande
réelle n'est lancée, aucun journal OPÉRER n'est lu."""

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

import couches as cli
from deltalib.couches import bilan as mod_bilan
from deltalib.couches import racines as mod_racines
from deltalib.couches import schemas
from deltalib.couches.stockage import empreinte
from test_couches import RACINE, _json, depot, instance  # noqa: F401 (fixtures)

T = datetime(2026, 10, 24, 13, 5, tzinfo=timezone.utc)
INDEX = json.loads((RACINE / "docs/commun/v1/index.json").read_text(encoding="utf-8"))
GENERATION = INDEX["generation"]
MODELES = json.loads((RACINE / "docs/commun/v1" / GENERATION / "kb/modeles.json").read_text(encoding="utf-8"))


def _groupe(executant, modele, effort, nature="code", missions=4, **autres):
    g = {"nature": nature, "executant": executant, "modele": modele, "effort": effort, "missions": missions,
         "missions_relues": missions - 1, "ok_premier_tour": 2, "part_ok_premier_tour": 2 / (missions - 1),
         "corrections_moyennes": 0.5, "defauts_moyens": {"BLOQUANT": None, "A_NOTER": None}, "echecs": 0,
         "jetons": {"statut": "partiel", "total_mesure": 1000, "missions_mesurees": 3, "missions_inconnues": 1, "autre": 1},
         "quota": {"statut": "inconnu", "moyenne_pct": None, "missions_estimees": 0, "missions_inconnues": missions,
                   "jauges": []},
         "indice_cout_qualite": {"statut": "inconnu"}, "details": [{"mission": "m-" + "0" * 12}]}
    g.update(autres)
    return g


GROUPES = [
    _groupe("claude:dev-delta", "opus", "high"),                       # alias unique → claude-opus-5-5 high
    _groupe("claude:design", "claude-opus-5-5", "high", nature="conception"),  # alias partagé, famille claude
    _groupe("antigravity", "claude-opus-5-5", "high"),                 # alias partagé, famille antigravity
    _groupe("claude-cloud", "opus", "xhigh"),                          # exécutant hors famille, alias unique
    _groupe("codex", "gpt-6.1-sol", "high", missions=9),
    _groupe("claude:chef-delta", None, None),                          # modèle et effort inconnus
    _groupe("inconnu-x", "claude-opus-5-5", "high"),                   # alias ambigu, aucune famille pour départager
    _groupe("codex", "gpt-9-imaginaire", "high"),                      # modèle sans fiche
    _groupe("codex", "gpt-6.1-sol", "hyper"),                          # effort sans fiche
]
BILAN = {"version": 1, "vue": "reglages_bilan", "depuis": None, "nature": None, "jusqu_au": "2026-10-24T15:00:00+02:00",
         "lignes_ignorees": 0, "missions": 30, "participations": 40, "missions_nature_inconnue": 0,
         "formule_indice": "…", "groupes": GROUPES}
ESSAIS = {"vue": "essai", "essais": [{"id": "e-1", "statut": "en_essai", "maturite": None, "fige_le": "2026-10-23T10:00:00+02:00",
                                      "protocole": {"fiche": "claude-code-commandes-agents", "version": "2.1.300", "titre": "x"},
                                      "clos": None}]}


class Source:
    """Exécuteur de test : rend le bilan (ou une erreur) et note les commandes reçues."""

    def __init__(self, bilan=BILAN, essais=ESSAIS, casser=None):
        self.bilan, self.essais, self.casser, self.commandes = bilan, essais, casser, []

    def __call__(self, commande):
        self.commandes.append(commande)
        if self.casser and self.casser in commande:
            raise mod_bilan.SourceIndisponible(f"{' '.join(commande[:3])} : code 1")
        return json.dumps(self.bilan if "reglages" in commande else self.essais)


@pytest.fixture
def lectrice(tmp_path):
    """Instance avec la génération commune publiée comme génération active (miroir), sans magasin personnel."""
    home = tmp_path / "home"
    home.mkdir()
    profil = tmp_path / "instance.json"
    _json(profil, {"schema": "delta.instance", "version": 1, "identite": "essai-l4", "mode": "essai", "home": str(home)})
    racines = mod_racines.resoudre(profil=profil, env={})
    shutil.copytree(RACINE / "docs/commun/v1" / GENERATION, racines.commun / GENERATION)
    _json(racines.commun_actif, {"schema": "delta.commun", "schema_version": 1, "vue": "actif", "generation": GENERATION,
                                 "manifest_sha256": INDEX["manifest_sha256"], "precedente": None, "origine": "synchro",
                                 "publie_le": INDEX["publie_le"]})
    return racines, profil


def _couple(modele, effort):
    return next(e["identite"] for e in MODELES["entrees"] if e["modele"] == modele and e["effort"] == effort)


def test_rattachement_par_modele_effort_et_famille_sans_supposition():
    proj = mod_bilan.projeter(mod_bilan.instantane_bilan(["operer"], BILAN, None, None, "2026-10-24T15:05:00+02:00"),
                              GENERATION, MODELES)
    opus_high, agy_high = _couple("claude-opus-5-5", "high"), _couple("antigravity-claude-opus-5-5", "high")
    assert sorted(proj["objets"]) == sorted({opus_high, agy_high, _couple("claude-opus-5-5", "xhigh"),
                                             _couple("gpt-6.1-sol", "high")})
    # deux groupes du même couple : gardés séparés par nature et exécutant, jamais additionnés
    groupes = proj["objets"][opus_high]["groupes"]
    assert [(g["nature"], g["executant"]) for g in groupes] == [("code", "claude:dev-delta"), ("conception", "claude:design")]
    assert [g["executant"] for g in proj["objets"][agy_high]["groupes"]] == ["antigravity"]
    motifs = {(g["executant"], g["modele"], g["effort"]): g["motif"] for g in proj["non_rattaches"]}
    assert motifs == {("claude:chef-delta", None, None): "modele_ou_effort_inconnu",
                      ("inconnu-x", "claude-opus-5-5", "high"): "alias_ambigu",
                      ("codex", "gpt-9-imaginaire", "high"): "modele_sans_fiche",
                      ("codex", "gpt-6.1-sol", "hyper"): "effort_sans_fiche"}
    assert not schemas.valider_personnel(proj, "modeles_efforts", "modeles-efforts.json")


def test_chaque_groupe_projete_egal_a_la_source_sans_details():
    inst = mod_bilan.instantane_bilan(["operer"], BILAN, None, None, "2026-10-24T15:05:00+02:00")
    proj = mod_bilan.projeter(inst, GENERATION, MODELES)
    vus = 0
    for o in proj["objets"].values():
        assert o["commun_empreinte"] == next(e["empreinte"] for e in MODELES["entrees"] if e["identite"] == o["objet"])
        assert o["bilan_empreinte"] == inst["sha256"] == empreinte(BILAN)
        for g in o["groupes"]:
            source = next(s for s in GROUPES if (s["executant"], s["modele"], s["effort"], s["nature"])
                          == (g["executant"], g["modele"], g["effort"], g["nature"]))
            for k in mod_bilan.CHAMPS_GROUPE:
                assert g[k] == source[k], k
            assert g["jetons"] == {k: source["jetons"][k] for k in mod_bilan.CHAMPS_JETONS}
            assert g["quota"] == {k: source["quota"][k] for k in mod_bilan.CHAMPS_QUOTA}
            assert "details" not in g and "indice_cout_qualite" not in g
            vus += 1
    assert vus == 5
    assert "m-" + "0" * 12 not in json.dumps(proj)
    # même entrée, mêmes octets
    assert json.dumps(proj, sort_keys=True) == json.dumps(mod_bilan.projeter(copy.deepcopy(inst), GENERATION, MODELES), sort_keys=True)


def test_null_et_absences_restent_inconnus():
    g = _groupe("codex", "gpt-6.1-sol", "high", part_ok_premier_tour=None, corrections_moyennes=None,
                jetons={"statut": "inconnu", "total_mesure": None, "missions_mesurees": 0, "missions_inconnues": 4},
                quota={})
    proj = mod_bilan.projeter(mod_bilan.instantane_bilan(["operer"], {**BILAN, "groupes": [g]}, None, None, "t"),
                              GENERATION, MODELES)
    [o] = proj["objets"].values()
    assert o["groupes"][0]["part_ok_premier_tour"] is None
    assert o["groupes"][0]["corrections_moyennes"] is None
    assert o["groupes"][0]["quota"] == {k: None for k in mod_bilan.CHAMPS_QUOTA}  # absent → null, jamais zéro
    # sans génération commune : aucun couple rattaché, tout reste non rattaché avec son motif
    vide = mod_bilan.projeter(mod_bilan.instantane_bilan(["operer"], BILAN, None, None, "t"), None, {})
    assert vide["objets"] == {} and {x["motif"] for x in vide["non_rattaches"]} == {"modele_ou_effort_inconnu", "modele_sans_fiche"}


def test_rafraichir_ecrit_les_instantanes_prives_et_le_second_lecteur_retrouve_le_meme(lectrice):
    racines, _ = lectrice
    source = Source()
    res = mod_bilan.rafraichir(racines, maintenant=T, executer=source)
    assert res["echecs"] == [] and res["bilan"] == res["essais"] == res["couples"] == "modifie"
    assert res["empreinte"] == empreinte(BILAN)
    for chemin in mod_bilan.chemins(racines).values():
        assert schemas.permissions_privees(chemin)
    inst = json.loads(mod_bilan.chemins(racines)["bilan"].read_text(encoding="utf-8"))
    assert not schemas.valider_personnel(inst, "reglages_bilan", "reglages-bilan.json")
    assert inst["commande"] == ["operer", "reglages", "bilan", "--json"] and inst["filtres"] == {"depuis": None, "nature": None}
    assert inst["bilan"] == BILAN  # résultat gardé tel quel, détails compris (privé)
    # second consommateur (pilote des réserves) : même commande, mêmes filtres → même empreinte que l'instantané
    _, direct = mod_bilan.lire_bilan(executer=Source())
    resume = mod_bilan.resume(racines, _couple("gpt-6.1-sol", "high"))
    assert resume["sha256"] == empreinte(direct) and resume["filtres"] == {"depuis": None, "nature": None}
    assert resume["couple"]["projection_a_jour"] is True
    assert [g["missions"] for g in resume["couple"]["groupes"]] == [9]
    # relance identique : rien ne change ; `--si-ancien` garde un instantané récent sans relancer OPÉRER
    assert mod_bilan.rafraichir(racines, maintenant=T, executer=Source())["bilan"] == "inchange"
    # `--si-ancien` garde un bilan récent sans relire le journal, mais relit les essais OPÉRER (essai ouvert entre-temps)
    nouvel_essai = {**ESSAIS, "essais": ESSAIS["essais"] + [{"id": "e-2", "statut": "en_essai", "protocole": {"fiche": "x"}}]}
    garde = Source(essais=nouvel_essai)
    res = mod_bilan.rafraichir(racines, si_ancien_h=24, maintenant=T, executer=garde)
    assert res["bilan"] == "garde" and res["essais"] == "modifie"
    assert garde.commandes == [mod_bilan.COMMANDE_ESSAIS]
    essais = json.loads(mod_bilan.chemins(racines)["essais"].read_text(encoding="utf-8"))
    assert [e["id"] for e in essais["essais"]] == ["e-1", "e-2"]


def test_filtres_declares_et_source_en_echec_sans_perte(lectrice):
    racines, _ = lectrice
    mod_bilan.rafraichir(racines, maintenant=T, executer=Source())
    avant = mod_bilan.chemins(racines)["bilan"].read_bytes()
    # source en échec : dernier instantané valide gardé, échec visible, essais relus quand même
    res = mod_bilan.rafraichir(racines, maintenant=T, executer=Source(casser="reglages"))
    assert res["echecs"] and res["essais"] == "inchange"
    assert mod_bilan.chemins(racines)["bilan"].read_bytes() == avant
    # filtres différents : exposés, empreinte différente, `--si-ancien` ne garde pas un instantané d'autres filtres
    filtre = Source(bilan={**BILAN, "nature": "code", "groupes": GROUPES[:1]})
    res = mod_bilan.rafraichir(racines, nature="code", si_ancien_h=24, maintenant=T, executer=filtre)
    assert filtre.commandes[0] == ["operer", "reglages", "bilan", "--json", "--nature", "code"]
    assert res["filtres"] == {"depuis": None, "nature": "code"} and res["empreinte"] != empreinte(BILAN)
    # sortie hors contrat : refusée, rien écrit
    with pytest.raises(mod_bilan.SourceIndisponible):
        mod_bilan.lire_bilan(executer=lambda c: json.dumps({"vue": "autre", "version": 1, "groupes": []}))


def test_cli_racines_et_bilan(lectrice, capsys):
    racines, profil = lectrice
    assert cli.main(["--instance", str(profil), "personnel", "bilan"]) == 1
    assert json.loads(capsys.readouterr().out)["statut"] == "absent"
    assert cli.main(["--instance", str(profil), "racines"]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["origine"] == "instance" and sortie["personnel"] == str(racines.personnel)
    mod_bilan.rafraichir(racines, maintenant=T, executer=Source())
    assert cli.main(["--instance", str(profil), "personnel", "bilan", "--couple", "modele-gpt-6-1-sol-high"]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["sha256"] == empreinte(BILAN) and sortie["couple"]["objet"].endswith("modele-gpt-6-1-sol-high")
    assert "m-" + "0" * 12 not in json.dumps(sortie)  # aucun détail de mission dans le résumé


def test_collecte_du_pont_alimente_l_instantane_partage_sans_second_collecteur(lectrice, tmp_path, monkeypatch):
    import reglages_pont as rp
    racines, _ = lectrice
    lancees = []

    class Fini:
        returncode, stdout = 0, json.dumps(BILAN)

    def faux_run(cmd, **_):
        lancees.append(cmd)
        return Fini()

    monkeypatch.setattr(rp.subprocess, "run", faux_run)
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"essai": None}), encoding="utf-8")
    res = rp.collecter(tmp_path / "bilans", config=cfg,
                       ranger=lambda cmd, doc: mod_bilan.enregistrer(racines, cmd, doc, maintenant=T)["bilan"])
    principal = next(r for r in res if r["source"] == "principal")
    assert principal["statut"] == "ok" and principal["instantane"] == "modifie"
    assert lancees == [["operer", "reglages", "bilan", "--json"]]  # une seule lecture du journal
    assert mod_bilan.resume(racines)["sha256"] == empreinte(BILAN)
    assert json.loads(Path(principal["chemin"]).read_text(encoding="utf-8")) == BILAN  # export du pont inchangé
    # bilan filtré : l'instantané partagé (sans filtre) n'est pas remplacé
    with pytest.raises(mod_bilan.SourceIndisponible):
        mod_bilan.enregistrer(racines, ["operer", "reglages", "bilan", "--json", "--nature", "code"], BILAN)
    # échec du rangement : noté, l'export reste
    res = rp.collecter(tmp_path / "bilans2", config=cfg, ranger=lambda cmd, doc: 1 / 0)
    assert next(r for r in res if r["source"] == "principal")["instantane"].startswith("non rangé")


def test_lecteur_python_memes_regles_que_le_lecteur_local(depot, instance):
    """Mêmes statuts et motifs que LecteurLocal.blocPersonnel (mcp/test/local.test.js) : commun très ancien, commun
    indisponible."""
    from datetime import timedelta

    from deltalib.couches.lecteur import Lecteur
    from deltalib.couches.projection import importer

    importer(depot, instance)
    ident = "kb:claude:claude-code-commandes-a"
    assert Lecteur(instance).fiche(ident)["personnel"]["statut"] == "importe"
    tard = datetime.now(timezone.utc) + timedelta(days=60)
    p = Lecteur(instance, maintenant=tard).fiche(ident)["personnel"]
    assert (p["statut"], p["motif"]) == ("a_revoir", "commun_tres_ancien")
    instance.commun_actif.unlink()
    p = Lecteur(instance).fiche(ident)["personnel"]
    assert (p["statut"], p["motif"]) == ("a_revoir", "commun_indisponible")

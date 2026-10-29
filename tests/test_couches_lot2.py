"""Delta-IA lot 2 : profil d'instance v2 de P1 (profil d'hôte) lu par les racines, instantané de l'instance (profil d'hôte et
réglages courants rattachés aux couples communs) pour la vue « Utile pour mon ORQYRA », avis à revoir jamais présenté comme
courant par le lecteur Python. Aucune commande OPÉRER réelle : exécuteur de test, politique écrite dans le dossier du test."""

import json
from datetime import datetime, timezone

import pytest

import couches as cli
from deltalib.couches import bilan as mod_bilan
from deltalib.couches import instance as mod_instance
from deltalib.couches import racines as mod_racines
from deltalib.couches import schemas
from test_couches import _json, depot, instance  # noqa: F401 (fixtures)
from test_couches_l4 import GENERATION, MODELES, Source, lectrice  # noqa: F401 (fixture)

T = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
INSTALLATION = "0f6d3c5e-8a1b-4c2d-9e7f-123456789abc"
HOTE = {"schema": "delta.hote", "version": 1, "id": "hp", "socle": ["moteur", "operer", "files", "tic", "pilote"],
        "couches_personnelles": [{"id": "tiroir", "libelle": "Tiroir", "ressources": ["tiroir/etat.json"]}],
        "migration": [], "lectures_ssh": []}


def _profil_v2(tmp_path, **autres):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    profil = tmp_path / "instance-v2.json"
    _json(profil, {"schema": "delta.instance", "version": 2, "identite": "essai-lot2", "mode": "essai", "home": str(home),
                   "hote": HOTE, "installation": INSTALLATION,
                   "executables": {"claude": str(home / ".local/bin/claude")}, **autres})
    return profil


def test_profil_v2_de_p1_accepte_et_retenu(tmp_path):
    profil = _profil_v2(tmp_path)
    r = mod_racines.resoudre(profil=profil, env={})
    assert r.origine == "instance" and r.profil == profil and r.etat == tmp_path / "home/.local/state/delta/essai-lot2"
    # hôte et installation n'existent qu'en v2 ; un v2 porte toujours son profil d'hôte
    d = json.loads(profil.read_text())
    _json(profil, {**d, "version": 1})
    with pytest.raises(mod_racines.RacinesInvalides, match="version 2"):
        mod_racines.resoudre(profil=profil, env={})
    _json(profil, {k: v for k, v in d.items() if k != "hote"})
    with pytest.raises(mod_racines.RacinesInvalides, match="profil d'hôte"):
        mod_racines.resoudre(profil=profil, env={})
    # instance lancée par K1 : profil installé désigné par OPERER_INSTANCE_PROFIL, sinon inconnu ; historique : aucun
    env = {"DELTA_INSTANCE": "x", "XDG_CONFIG_HOME": "/c", "XDG_STATE_HOME": "/s", "XDG_CACHE_HOME": "/k", "XDG_RUNTIME_DIR": "/r"}
    assert mod_racines.resoudre(env=env).profil is None
    assert str(mod_racines.resoudre(env={**env, "OPERER_INSTANCE_PROFIL": "/c/instance.json"}).profil) == "/c/instance.json"
    assert mod_racines.resoudre(historique=True, env={}, home=tmp_path).profil is None


def test_resume_du_profil_sans_ressource_ni_chemin(tmp_path):
    p = mod_instance.lire_profil(_profil_v2(tmp_path))
    assert p == {"statut": "present", "identite": "essai-lot2", "version": 2, "mode": "essai",
                 "hote": {"id": "hp", "version": 1, "socle": ["moteur", "operer", "files", "tic", "pilote"],
                          "couches_personnelles": [{"id": "tiroir", "libelle": "Tiroir"}]},
                 "executables": ["claude"]}
    assert str(tmp_path) not in json.dumps(p) and "tiroir/etat.json" not in json.dumps(p)
    assert mod_instance.lire_profil(None) == {"statut": "absent", "motif": "aucun_profil"}
    assert mod_instance.lire_profil(tmp_path / "absent.json")["motif"] == "profil_introuvable"
    casse = _profil_v2(tmp_path, hote={**HOTE, "socle": ["moteur"]})
    assert mod_instance.lire_profil(casse) == {"statut": "invalide", "motif": "hote_forme"}


def test_politique_resolue_comme_operer(tmp_path, lectrice):
    racines, _ = lectrice
    assert mod_instance.chemin_politique(racines, {"OPERER_POLICY_FILE": "/p.json", "OPERER_CONFIG_DIR": "/d"}) == \
        (mod_racines.Path("/p.json"), "OPERER_POLICY_FILE")
    assert mod_instance.chemin_politique(racines, {"OPERER_CONFIG_DIR": "/d"}) == (mod_racines.Path("/d/politique.json"),
                                                                                   "OPERER_CONFIG_DIR")
    assert mod_instance.chemin_politique(racines, {}) == (racines.configuration / "politique.json", "instance")
    hist = mod_racines.resoudre(historique=True, env={}, home=tmp_path)
    bin_operer = tmp_path / "discipline/bin/operer"
    bin_operer.parent.mkdir(parents=True)
    bin_operer.write_text("")
    assert mod_instance.chemin_politique(hist, {}, operer=str(bin_operer)) == \
        (tmp_path / "discipline/config/instance-policy.json", "operer")


def test_rafraichir_range_profil_et_reglages_rattaches(tmp_path, lectrice):
    racines, _ = lectrice
    politique = tmp_path / "politique.json"
    _json(politique, {"schema": "delta.instance-policy", "operer": {"reglage_missions": {"claude": {"effort": "high", "table": {
        "code": {"*": {"modele": "sonnet", "effort": "high", "motif": "mesuré"}, "S": {"modele": "opus", "effort": "high"}},
        "relecture": {"L": {"modele": "gpt-9-imaginaire", "effort": "high"}, "M": {"modele": "sonnet"}}}}}}})
    res = mod_bilan.rafraichir(racines, maintenant=T, executer=Source(), politique=politique, env={})
    assert res["echecs"] == [] and res["instance"] == "modifie" and res["reglages"] == "disponible" and res["profil"] == "present"
    doc = json.loads((racines.personnel / "instance.json").read_text())
    assert schemas.valider_personnel(doc, "instance", "instance.json") == []
    assert schemas.permissions_privees(racines.personnel / "instance.json")
    cases = {(c["nature"], c["taille"]): c for c in doc["reglages"]["cases"]}
    sonnet = next(e for e in MODELES["entrees"] if e["modele"] == "claude-sonnet-5-5" and e["effort"] == "high")
    assert cases[("code", "*")]["couple"] == sonnet["identite"] and cases[("code", "*")]["couple_empreinte"] == sonnet["empreinte"]
    assert cases[("code", "*")]["motif_reglage"] == "mesuré" and cases[("code", "S")]["couple"].endswith("claude-opus-5-5-high")
    # sans fiche ou sans effort : non rattachée, avec son motif, jamais rattachée par supposition (ni effort de famille)
    assert (cases[("relecture", "L")]["couple"], cases[("relecture", "L")]["non_rattache"]) == (None, "modele_sans_fiche")
    assert (cases[("relecture", "M")]["couple"], cases[("relecture", "M")]["non_rattache"]) == (None, "modele_ou_effort_inconnu")
    assert doc["reglages"]["origine"] == "option" and doc["reglages"]["commun_generation"] == GENERATION
    # verifier accepte l'instantané ; un contenu altéré est refusé
    doc["reglages"]["cases"] = []
    assert any("sha256" in e for e in schemas.valider_personnel(doc, "instance", "instance.json"))


def test_politique_absente_ou_illisible(tmp_path, lectrice):
    racines, _ = lectrice
    res = mod_bilan.rafraichir(racines, maintenant=T, executer=Source(), politique=tmp_path / "absente.json", env={})
    assert res["echecs"] == [] and res["reglages"] == "absent"
    doc = json.loads((racines.personnel / "instance.json").read_text())
    assert doc["reglages"] == {"statut": "absent", "motif": "politique_absente", "origine": "option", "cases": []}
    avant = (racines.personnel / "instance.json").read_bytes()
    (tmp_path / "casse.json").write_text("{", encoding="utf-8")
    res = mod_bilan.rafraichir(racines, maintenant=T, executer=Source(), politique=tmp_path / "casse.json", env={})
    # source en échec : signalée, le dernier instantané valide reste
    assert res["echecs"] and "politique" in res["echecs"][0] and res["instance"] is None
    assert (racines.personnel / "instance.json").read_bytes() == avant


def test_cli_rafraichir_avec_politique_et_racines_avec_profil(tmp_path, lectrice, capsys, monkeypatch):
    racines, profil = lectrice
    source = Source()

    class Fini:
        def __init__(self, commande):
            self.returncode, self.stdout = 0, source(commande)

    monkeypatch.setattr(mod_bilan.subprocess, "run", lambda commande, **_: Fini(commande))
    monkeypatch.delenv("OPERER_POLICY_FILE", raising=False)
    monkeypatch.delenv("OPERER_CONFIG_DIR", raising=False)
    politique = tmp_path / "p.json"
    _json(politique, {"operer": {}})
    assert cli.main(["--instance", str(profil), "personnel", "rafraichir", "--politique", str(politique)]) == 0
    assert json.loads(capsys.readouterr().out)["reglages"] == "absent"
    assert cli.main(["--instance", str(profil), "racines"]) == 0
    assert json.loads(capsys.readouterr().out)["profil"] == str(profil)


def test_lecteur_python_avis_a_revoir_en_precedent(depot, instance):
    """Comme LecteurLocal.blocPersonnel : un avis à revoir n'est jamais rendu comme avis courant."""
    from datetime import timedelta

    from deltalib.couches.lecteur import Lecteur
    from deltalib.couches.projection import importer
    from test_couches import MAINTENANT_FIXTURE

    importer(depot, instance)
    ident = "kb:claude:claude-code-commandes-a"
    p = Lecteur(instance, maintenant=MAINTENANT_FIXTURE).fiche(ident)["personnel"]
    assert p["statut"] == "importe" and p["avis"]["recommandation"] and "avis_precedent" not in p
    p = Lecteur(instance, maintenant=MAINTENANT_FIXTURE + timedelta(days=8)).fiche(ident)["personnel"]
    assert p["statut"] == "a_revoir" and p["avis"] is None and p["avis_precedent"]["recommandation"]


def test_site_public_lit_une_couche_nommee_et_jamais_la_couche_personnelle():
    """Le site public ne lit que `data/` ou `commun/v1/<génération>/` et dit laquelle (pied de page, L3) ; il n'a aucun
    chemin vers le magasin personnel, l'instantané de l'instance ni la vue « Utile pour mon ORQYRA »."""
    from test_couches import RACINE

    app = (RACINE / "docs/assets/app.js").read_text(encoding="utf-8")
    assert 'return enCommun() ? `${RACINE}commun/v1/${COUCHE.generation}/${rel}` : `${RACINE}data/${rel}`;' in app
    assert "function rendreCouche()" in app
    for interdit in ("personnel/", "instance.json", "utile_pour_instance", "bureau.js", "stdio.js", "overlay.json",
                     "reglages-bilan", "modeles-efforts"):
        assert interdit not in app, interdit

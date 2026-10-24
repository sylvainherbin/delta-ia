"""Delta-IA en deux couches, lot L2 : extraction tous systèmes, générateur isolé, textes bilingues et cache de traduction,
scission des sources, publication versionnée, miroir hors ligne et surveillance du producteur."""

import functools
import http.server
import json
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import commun_auto
import valider
from deltalib.couches import config as mod_config
from deltalib.couches import publication, schemas, scission, traduction
from deltalib.couches.controle import fidelite
from deltalib.couches.generateur import LectureRefusee, LecteurBorne, generer
from deltalib.couches.lecteur import Lecteur
from deltalib.couches.projection import ImportImpossible, importer
from deltalib.couches.sentinelles import Detecteur
from test_couches import RACINE, _json, depot, instance  # noqa: F401 (fixtures)

SENTINELLE = "sentinelle" + "-privee-l2-7f3a"
PAGE = """# Commands

## All commands

| Command | Purpose |
| --- | --- |
| `/a <arg>` | Runs /a. |
| `/winonly` | Windows only. Opens a PowerShell prompt. |
| `/macx` | Available on macOS. Opens the Keychain. |
| `/partout` | Works everywhere with `--flag`, see https://exemple.org/doc. |
"""
SOURCES = {"documentation": [{"id": "cc-commandes", "perimetre": "claude", "produit": "claude-code", "extracteur": "tableau",
                              "url": "https://code.claude.com/docs/en/commands.md", "statut": "ok",
                              "options": {"section": "All commands", "categorie": "commandes"}}]}


class Faux:
    """Rédacteur de test : « FR <texte> », repères conservés ; garde chaque charge reçue."""
    outil = "faux"

    def __init__(self, jetons_entree=100, casser=False):
        self.charges, self.jetons_entree, self.casser = [], jetons_entree, casser

    def traduire(self, charge):
        self.charges.append(dict(charge))
        reponse = {k: ("FR " + v).replace("⟦0⟧", "") if self.casser else "FR " + v for k, v in charge.items()}
        return reponse, {"jetons_entree": self.jetons_entree, "jetons_sortie": 50, "cout_usd_catalogue": 0.001,
                         "modele": "faux-1", "octets_envoyes": len(json.dumps(charge))}


@pytest.fixture
def depot2(depot):
    """Dépôt L1 + documentation lue (raw/kb), profil qui exclut Windows et macOS, sources modèles, sentinelles privées."""
    (depot / "sources.yaml").write_text(yaml.safe_dump(SOURCES), encoding="utf-8")
    page = depot / "raw" / "kb" / "claude-code" / "cc-commandes" / "page.md"
    page.parent.mkdir(parents=True)
    page.write_text(PAGE, encoding="utf-8")
    (depot / "profil.yaml").write_text(yaml.safe_dump({"base": {"exclure_systemes": ["windows", "macos"]},
                                                       "note": SENTINELLE}), encoding="utf-8")
    (depot / "CONTEXTE.md").write_text(f"# Contexte\n\n{SENTINELLE}\n", encoding="utf-8")
    cat = depot / "docs" / "data" / "kb" / "claude" / "commandes.json"
    doc = json.loads(cat.read_text(encoding="utf-8"))
    doc["entrees"][0]["retiree"] = True  # retirée chez l'instance, encore décrite par la documentation
    doc["entrees"][0]["recommandation"] = {"verdict": "tester", "pourquoi": f"Pour {SENTINELLE}."}
    doc["entrees"][1]["description"] = f"Utile à {SENTINELLE}."
    _json(cat, doc)
    (depot / "kb-modeles").mkdir()
    (depot / "kb-modeles" / "x.yaml").write_text(yaml.safe_dump({
        "famille": "x", "fournisseur": "X", "date_releve": "2026-10-20", "executants_operer": ["dev"],
        "modeles": [{"modele": "x-1", "nom": "X 1", "statut_usage": "utilise",
                     "constats_internes": [{"date": "2026-10-20", "titre": "t", "constat": f"Constat interne {SENTINELLE} long"}],
                     "efforts": [{"effort": "high", "usage": "x --effort high",
                                  "recommandation_operer": {"verdict": "utiliser", "pourquoi": "Missions de code longues"}}]}]}),
        encoding="utf-8")
    return depot


def _octets(dossier: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(dossier.rglob("*")) if p.is_file())


def _generation(racines) -> Path:
    return racines.commun / json.loads(racines.commun_actif.read_text(encoding="utf-8"))["generation"]


def _kb(racines, rel="kb/claude/commandes.json") -> dict:
    doc = json.loads((_generation(racines) / rel).read_text(encoding="utf-8"))
    return {f["id"]: f for f in doc["entrees"]}


# --- extraction couvrant les systèmes ---

def test_fiches_windows_macos_communes_sans_profil(depot2, instance):
    res = importer(depot2, instance, detecteur=Detecteur(["projet-sentinelle"]))
    fiches = _kb(instance)
    assert fiches["claude-code-commandes-winonly"]["systemes"] == ["windows"]
    assert fiches["claude-code-commandes-macx"]["systemes"] == ["macos"]
    assert fiches["claude-code-commandes-partout"]["systemes"] is None
    assert fiches["claude-code-commandes-a"]["retiree"] is False  # retirée par le profil, pas par l'éditeur
    couverture = json.loads((res.dossier / "manifest.json").read_text())["couverture_sources"]["base:claude"]
    assert set(couverture["ajoutees"]) == {"claude-code-commandes-winonly", "claude-code-commandes-macx",
                                           "claude-code-commandes-partout"}
    octets = _octets(res.dossier)
    assert b"exclure_systemes" not in octets and SENTINELLE.encode() not in octets
    assert fidelite(depot2, instance)[0] == []
    # L'extracteur retrouve la liste du profil après l'extraction.
    from deltalib.kb import extracteurs
    assert extracteurs._systemes_exclus is None


# --- frontière du générateur commun ---

def test_sentinelle_absente_de_l_entree_des_envois_et_de_la_sortie(depot2, instance, tmp_path):
    _json(depot2 / "docs" / "data" / "etat.json", {"releve_le": "2026-10-21", "pertinent_pour_profil": True,
                                                   "outils": {"x": SENTINELLE}, "comptes": {}})
    (depot2 / "kb-essais.yaml").write_text(yaml.safe_dump([{"date": "2026-10-21", "id": "claude-code-commandes-a",
                                                            "par": "m-x", "rapport": SENTINELLE}]), encoding="utf-8")
    faux = Faux()
    cache = tmp_path / "fr.json"
    importer(depot2, instance, detecteur=Detecteur(), traductions=cache, redacteur=faux, budget=50)
    entree = instance.production / "entree-commune"
    assert faux.charges and SENTINELLE.encode() not in _octets(entree)
    assert all(SENTINELLE not in json.dumps(c) for c in faux.charges)
    assert SENTINELLE.encode() not in _octets(_generation(instance)) and SENTINELLE.encode() not in cache.read_bytes()
    # Le générateur relancé seul n'ouvre que son entrée et le cache.
    gen = generer(entree, cache)
    assert gen.lus and all(Path(p).is_relative_to(entree.resolve()) or Path(p) == cache.resolve() for p in gen.lus)
    # Le magasin privé garde les rattachements des sources scindées.
    prive = json.loads((instance.personnel / "sources.json").read_text())
    assert SENTINELLE in json.dumps(prive)
    publique = json.loads((instance.production / "sources-publiques.json").read_text())
    assert "constats_internes" not in json.dumps(publique) and "x --effort high" in json.dumps(publique)


def test_lecteur_borne_refuse_hors_entree(tmp_path):
    (tmp_path / "entree").mkdir()
    (tmp_path / "profil.yaml").write_text("x", encoding="utf-8")
    lire = LecteurBorne([tmp_path / "entree"])
    with pytest.raises(LectureRefusee):
        lire(tmp_path / "profil.yaml")
    with pytest.raises(LectureRefusee):
        lire(tmp_path / "entree" / ".." / "profil.yaml")


def test_texte_prive_d_une_source_scindee_refuse(depot2, instance):
    cat = depot2 / "docs" / "data" / "kb" / "claude" / "commandes.json"
    doc = json.loads(cat.read_text(encoding="utf-8"))
    doc["entrees"][0]["description_source"] = f"Constat interne {SENTINELLE} long"
    _json(cat, doc)
    with pytest.raises(ImportImpossible, match="texte privé"):
        importer(depot2, instance, detecteur=Detecteur())
    assert not instance.commun_actif.exists()


# --- textes bilingues et cache ---

def test_cache_inchange_sur_relance_et_budget(depot2, instance, tmp_path):
    cache = tmp_path / "fr.json"
    faux = Faux()
    premier = importer(depot2, instance, detecteur=Detecteur(), traductions=cache, redacteur=faux, budget=1)
    assert premier.traduction["unites_envoyees"] == 1 and premier.textes["traduits_fr"] == 1
    importer(depot2, instance, detecteur=Detecteur(), traductions=cache, redacteur=faux, budget=100)
    envoyees = sum(len(c) for c in faux.charges)
    octets = cache.read_bytes()
    faux.charges.clear()
    relance = importer(depot2, instance, detecteur=Detecteur(), traductions=cache, redacteur=faux, budget=100)
    assert faux.charges == [] and relance.changements == [] and cache.read_bytes() == octets
    assert relance.textes["traduits_fr"] == relance.textes["textes"] == envoyees
    # Un seul extrait change : une seule unité renvoyée.
    cat = depot2 / "docs" / "data" / "kb" / "claude" / "commandes.json"
    doc = json.loads(cat.read_text(encoding="utf-8"))
    doc["entrees"][1]["description_source"] = "Runs /b differently."
    _json(cat, doc)
    importer(depot2, instance, detecteur=Detecteur(), traductions=cache, redacteur=faux, budget=100)
    assert [list(c.values()) for c in faux.charges] == [["Runs /b differently."]]
    # Les URL (et le code entre accents graves) sont masqués à l'envoi et rétablis au retour.
    fr = _kb(instance)["claude-code-commandes-partout"]["textes"]["description"]["fr"]
    assert fr["texte"].endswith("https://exemple.org/doc.")
    assert traduction.masquer("Use `a b` at https://x.org/y.") == ("Use ⟦0⟧ at ⟦1⟧.", ["`a b`", "https://x.org/y"])
    assert traduction.retablir("Utiliser ⟦0⟧ sur ⟦1⟧.", ["`a b`", "https://x.org/y"]) == "Utiliser `a b` sur https://x.org/y."
    assert traduction.retablir("Utiliser ⟦0⟧.", ["`a b`", "https://x.org/y"]) is None
    couts = (instance.production / "couts.jsonl").read_text().splitlines()
    assert len(couts) == 3 and json.loads(couts[0])["cout_usd_catalogue"] > 0


def test_traductions_refusees_sans_repere_ou_avec_contexte_ajoute(depot2, instance, tmp_path):
    cache = tmp_path / "fr.json"
    res = importer(depot2, instance, detecteur=Detecteur(), traductions=cache, redacteur=Faux(casser=True), budget=100)
    assert res.textes["traduits_fr"] == res.traduction["acceptees"]
    assert res.traduction["refusees"] >= 1  # `/partout` : repère perdu
    assert "texte" not in json.dumps(_kb(instance)["claude-code-commandes-partout"]["textes"]["description"].get("fr", {}))
    res = importer(depot2, instance, detecteur=Detecteur(), traductions=tmp_path / "fr2.json",
                   redacteur=Faux(jetons_entree=traduction.SURCOUT_MAX + 10_000), budget=100)
    assert res.traduction["lots_refuses"] == 1 and res.textes["traduits_fr"] == 0
    envois = (instance.production / "traductions-envois.jsonl").read_text().splitlines()
    assert json.loads(envois[-1])["erreur"] == "contexte_inattendu"


def test_enveloppe_validee_et_hors_empreinte(depot2, instance, tmp_path):
    importer(depot2, instance, detecteur=Detecteur(), traductions=tmp_path / "fr.json", redacteur=Faux(), budget=100)
    doc = json.loads((_generation(instance) / "kb/claude/commandes.json").read_text())
    fiche = next(f for f in doc["entrees"] if f["id"] == "claude-code-commandes-winonly")
    assert schemas.empreinte_fiche(fiche["identite"], schemas.contenu_factuel(fiche)) == fiche["empreinte"]
    sans = {k: v for k, v in fiche.items() if k != "textes"}
    assert schemas.empreinte_fiche(sans["identite"], schemas.contenu_factuel(sans)) == fiche["empreinte"]

    def erreurs(modif):
        d = json.loads(json.dumps(doc))
        modif(next(f for f in d["entrees"] if f["id"] == "claude-code-commandes-winonly"))
        return schemas.valider_commun(d, "x", Detecteur(), set())
    assert erreurs(lambda f: None) == []
    assert erreurs(lambda f: f["textes"]["description"]["fr"].update(source_sha256="0" * 64))
    assert erreurs(lambda f: f["textes"]["description"]["en"].update(texte="Autre."))
    assert erreurs(lambda f: f["textes"]["description"].update(de={"texte": "x"}))
    assert erreurs(lambda f: f["textes"].update(exemple={"en": {}}))
    # Lecteur : français demandé, sinon repli anglais annoncé ; un avis importé n'est pas périmé par la traduction.
    lecteur = Lecteur(instance, langue="fr")
    bloc = lecteur.fiche("kb:claude:claude-code-commandes-a")
    assert bloc["commun"]["textes"]["description"]["langue"] == "fr"
    assert bloc["personnel"]["statut"] == "importe"


# --- scission des sources ---

def test_scission_reelle_sans_perte_ni_rattachement_public():
    publique, privee = scission.scinder_sources(RACINE)
    assert publique, "sources modèles ou méthodes attendues dans le dépôt"
    for rel in publique:
        source = scission.lire_modele(RACINE / rel) if rel.endswith(".yaml") else scission.lire_methode(RACINE / rel)
        assert scission.recomposer(publique[rel], privee[rel]) == source, rel
        texte = json.dumps(publique[rel], ensure_ascii=False)
        for cle in ("constats_internes", "sources_internes", "recommandation_operer", "statut_usage", "executants_operer",
                    "modele_operer", "jauges_operer", "corps"):
            assert f'"{cle}"' not in texte, (rel, cle)
    assert publique.get("kb-modeles/forfaits.yaml", {}) == {}
    assert scission.textes_prives(privee)


# --- publication, miroir et surveillance ---

@pytest.fixture
def serveur(tmp_path):
    route = tmp_path / "site" / "commun" / "v1"
    route.mkdir(parents=True)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Silencieux, directory=str(tmp_path / "site")))
    fil = threading.Thread(target=httpd.serve_forever, daemon=True)
    fil.start()
    yield route, f"http://127.0.0.1:{httpd.server_address[1]}/commun/v1/", httpd
    httpd.shutdown()


class _Silencieux(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _lectrice(tmp_path, nom="lectrice"):
    home = tmp_path / nom
    home.mkdir()
    _json(tmp_path / f"{nom}.json", {"schema": "delta.instance", "version": 1, "identite": nom, "home": str(home)})
    from deltalib.couches import racines as mod_racines
    return mod_racines.resoudre(profil=tmp_path / f"{nom}.json", env={})


def test_publication_route_versionnee(depot2, instance, tmp_path):
    route = tmp_path / "route"
    t0 = datetime(2026, 10, 24, 6, 45, tzinfo=timezone.utc)
    g1 = importer(depot2, instance, detecteur=Detecteur()).generation
    assert publication.publier(instance, route, t0) == {"generation": g1, "precedente": None, "nouvelle": True}
    assert publication.valider_route(route) == []
    assert valider.main(["--publication", str(route)]) == 0
    assert publication.publier(instance, route, t0 + timedelta(days=1))["nouvelle"] is False
    index = json.loads((route / "index.json").read_text())
    assert index["publie_le"].startswith("2026-10-25") and index["perimetres"]["claude"]["dernier_jour"] is None
    _json(depot2 / "docs" / "data" / "claude" / "index.json", {"perimetre": "claude", "agent": "claude-code",
                                                               "maj_le": "2026-10-22", "jours": [
                                                                   {"date": "2026-10-22", "genere_le": "2026-10-22T04:10:00+02:00",
                                                                    "impact": {"fort": 1}, "elements": 1, "ecartes": 0}]})
    g2 = importer(depot2, instance, detecteur=Detecteur()).generation
    assert publication.publier(instance, route, t0)["precedente"] == g1
    index = json.loads((route / "index.json").read_text())
    assert index["perimetres"]["claude"]["dernier_jour"] == "2026-10-22"
    assert b'"impact"' not in (route / g2 / "veille" / "claude.json").read_bytes()
    _json(depot2 / "docs" / "data" / "actu" / "index.json", {"perimetre": "actu", "maj_le": "2026-10-23",
                                                             "jours": [{"date": "2026-10-23", "genere_le": "2026-10-23T04:20:00+02:00"}]})
    g3 = importer(depot2, instance, detecteur=Detecteur()).generation
    publication.publier(instance, route, t0)
    assert sorted(p.name for p in route.iterdir()) == sorted(["index.json", g2, g3])
    (route / g3 / "kb" / "noms.json").write_text("{}", encoding="utf-8")
    assert publication.valider_route(route)


def test_miroir_hors_ligne_echec_reseau_et_304(depot2, instance, tmp_path, serveur):
    route, url, httpd = serveur
    importer(depot2, instance, detecteur=Detecteur())
    publication.publier(instance, route)
    lectrice = _lectrice(tmp_path)
    assert publication.synchroniser(lectrice, url)["statut"] == "nouvelle"
    assert publication.synchroniser(lectrice, url)["statut"] == "inchange"  # 304 sur If-Modified-Since
    httpd.shutdown()
    httpd.server_close()
    lecteur = Lecteur(lectrice, personnel=True)
    bloc = lecteur.fiche("claude-code-commandes-winonly")
    assert bloc["commun"]["statut"] == "disponible" and bloc["commun"]["fraicheur"] == "recente"
    assert bloc["personnel"]["statut"] == "non_personnalise"  # instance neuve : aucun avis hérité
    actif = lectrice.commun_actif.read_bytes()
    echec = publication.synchroniser(lectrice, url)
    assert echec["statut"] == "echec" and "réseau" in echec["erreur"]
    assert lectrice.commun_actif.read_bytes() == actif
    lecteur = Lecteur(lectrice)
    assert lecteur.commun_statut == "disponible" and lecteur.fiche("/winonly")["commun"]["derniere_erreur_synchro"]


def test_generation_alteree_sur_le_serveur_refusee(depot2, instance, tmp_path, serveur):
    route, url, _ = serveur
    importer(depot2, instance, detecteur=Detecteur())
    publication.publier(instance, route)
    lectrice = _lectrice(tmp_path)
    g1 = publication.synchroniser(lectrice, url)["generation"]
    _json(depot2 / "docs" / "data" / "actu" / "index.json", {"perimetre": "actu", "maj_le": "2026-10-23",
                                                             "jours": [{"date": "2026-10-23", "genere_le": "2026-10-23T04:20:00+02:00"}]})
    importer(depot2, instance, detecteur=Detecteur())
    g2 = publication.publier(instance, route)["generation"]
    veille = route / g2 / "veille" / "actu.json"
    saine = veille.read_bytes()
    veille.write_bytes(saine.replace(b"2026-10-23", b"2026-10-24"))
    import os
    os.utime(route / "index.json", (datetime.now().timestamp() + 5,) * 2)  # Last-Modified à la seconde : index récent
    res = publication.synchroniser(lectrice, url)
    assert res["statut"] == "echec" and "refusée" in res["erreur"]
    assert json.loads(lectrice.commun_actif.read_text())["generation"] == g1
    assert sorted(p.name for p in lectrice.commun.iterdir()) == [g1]
    synchro = json.loads(publication.chemin_synchro(lectrice).read_text())
    assert synchro["generation"] == g1 and synchro["etag"] is None and synchro["last_modified"] is None
    # Relance sur le même serveur : pas de 304 trompeur, l'échec et son erreur restent.
    res = publication.synchroniser(lectrice, url)
    assert res["statut"] == "echec" and json.loads(publication.chemin_synchro(lectrice).read_text())["erreur"]
    # Serveur rétabli : la nouvelle génération arrive, l'erreur s'efface, les validateurs suivent g2.
    veille.write_bytes(saine)
    res = publication.synchroniser(lectrice, url)
    assert res == {"statut": "nouvelle", "generation": g2, "erreur": None}
    synchro = json.loads(publication.chemin_synchro(lectrice).read_text())
    assert synchro["generation"] == g2 and synchro["erreur"] is None and synchro["last_modified"]
    assert synchro["publie_le"] == json.loads((route / "index.json").read_text())["publie_le"]
    assert publication.synchroniser(lectrice, url)["statut"] == "inchange"


def test_fraicheur_avis_et_surveillance():
    t = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    iso = lambda h: (t - timedelta(hours=h)).isoformat()  # noqa: E731
    assert publication.fraicheur(t, iso(1), iso(2)) == "recente"
    assert publication.fraicheur(t, iso(1), iso(30)) == "ancienne"
    assert publication.fraicheur(t, iso(200), iso(2)) == "tres_ancienne"
    assert publication.fraicheur(t, None, None, "2026-10-23") == "recente"
    assert publication.fraicheur(t, None, None, None) is None
    index = {"schema": "delta.manifest", "schema_version": 1, "vue": "publication", "generation": "g-" + "0" * 16,
             "manifest_sha256": "0" * 64, "publie_le": iso(2), "precedente": None, "cycle_attendu_h": 24,
             "perimetres": {p: {"dernier_jour": "2026-10-24"} for p in ("claude", "openai", "actu")}}
    assert publication.surveiller(index, t) == {"ok": True, "alertes": [], "age_h": 2.0}
    index["publie_le"] = iso(40)
    index["perimetres"]["openai"]["dernier_jour"] = "2026-10-20"
    alertes = publication.surveiller(index, t)["alertes"]
    assert any(a.startswith("cycle_manque") for a in alertes) and any("openai" in a for a in alertes)


def test_avis_a_revoir_quand_le_commun_est_tres_ancien(depot2, instance):
    importer(depot2, instance, detecteur=Detecteur())
    tard = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert Lecteur(instance, maintenant=tard).fiche("kb:claude:claude-code-commandes-a")["personnel"]["statut"] == "a_revoir"


# --- configuration, service et route du dépôt ---

def test_configuration_bootstrap_et_locale(instance):
    conf = mod_config.charger(instance)
    assert conf["mode"] == "lecteur" and conf["reference_base_url"].endswith("/commun/v1/")
    assert conf["production"]["budget_traduction"] == 0
    _json(instance.config, {"mode": "producteur", "production": {"budget_traduction": 40}})
    conf = mod_config.charger(instance)
    assert conf["mode"] == "producteur" and conf["production"]["budget_traduction"] == 40
    _json(instance.config, {"inconnue": 1})
    with pytest.raises(mod_config.ConfigInvalide):
        mod_config.charger(instance)


def test_commun_auto_ne_publie_que_sa_route():
    assert commun_auto.est_publie("docs/commun/v1/index.json")
    assert commun_auto.est_publie("kb-traductions/fr.json")
    assert not commun_auto.est_publie("docs/data/versions.json")
    assert not commun_auto.est_publie("docs/commun/v1")  # le dossier lui-même n'est jamais un fichier publié
    assert not commun_auto.est_publie("profil.yaml")


def test_route_publiee_du_depot_valide():
    route = RACINE / "docs" / "commun" / "v1"
    if not (route / "index.json").is_file():
        pytest.skip("aucune route commune publiée dans ce dépôt")
    assert publication.valider_route(route) == []
    index = json.loads((route / "index.json").read_text())
    octets = _octets(route / index["generation"])
    for cle in (b'"pour_toi"', b'"recommandation"', b'"statut_usage"', b'"impact"', b'"constats_internes"',
                b'"recommandation_operer"', b'"contexte_sections"', b'"verdict"'):
        assert cle not in octets, cle
    cache = RACINE / "kb-traductions" / "fr.json"
    if cache.is_file():
        traduction.Cache(cache)  # forme v1 valide


def test_cli_surveiller_route(tmp_path, depot2, instance, capsys):
    import couches as cli
    route = tmp_path / "route"
    importer(depot2, instance, detecteur=Detecteur())
    publication.publier(instance, route)
    assert cli.main(["surveiller", "--route", str(route)]) == 1  # périmètres sans jour couvert
    assert "perimetre_absent" in capsys.readouterr().out
    shutil.rmtree(route)
    assert cli.main(["surveiller", "--route", str(route)]) == 1


def test_commun_auto_commit_limite_a_la_route(depot2, instance, monkeypatch):
    import subprocess

    def g(*args):
        return subprocess.run(["git", "-C", str(depot2), *args], capture_output=True, text=True, check=True).stdout
    g("init", "-q", "-b", "main")
    g("-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A")
    g("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "base")
    monkeypatch.setattr(commun_auto.mod_racines, "resoudre", lambda **_: instance)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")
    t0 = datetime(2026, 10, 24, 6, 45, tzinfo=timezone.utc)
    message = commun_auto.publier(depot2, t0)
    assert message.startswith("commun-auto : g-")
    assert g("status", "--porcelain") == ""
    publies = g("show", "--name-only", "--format=%s", "HEAD").split("\n")
    assert publies[0].startswith("delta(commun): 2026-10-24 — génération g-")
    assert all(p.startswith("docs/commun/v1/") for p in publies[1:] if p)
    assert publication.valider_route(depot2 / "docs" / "commun" / "v1") == []
    (depot2 / "profil.yaml").write_text("modifié\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="hors de la route"):
        commun_auto.publier(depot2, t0)
    g("checkout", "-q", "profil.yaml")
    g("checkout", "-q", "-b", "autre")
    with pytest.raises(RuntimeError, match="main"):
        commun_auto.publier(depot2, t0)

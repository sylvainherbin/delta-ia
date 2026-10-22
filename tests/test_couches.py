"""Delta-IA en deux couches, lot L1 : racines, classement, import privé, projection commune et lecteur."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

import couches as cli
import valider
from deltalib.couches import classement as cl
from deltalib.couches import racines as mod_racines
from deltalib.couches import schemas
from deltalib.couches.controle import fidelite
from deltalib.couches.lecteur import Lecteur
from deltalib.couches.projection import ImportImpossible, importer
from deltalib.couches.sentinelles import Detecteur, termes_instance
from deltalib.couches.stockage import MagasinOccupe, verrou

RACINE = Path(__file__).resolve().parent.parent
# Sentinelles construites à l'exécution : aucun motif réel dans un fichier suivi.
COURRIEL = "sentinelle" + "@" + "prive-exemple.fr"
CHEMIN = "/home/" + "sentinelle/projets/secret"
MISSION = "m-" + "0123456789ab"
PROJET = "projet-sentinelle"


def _json(chemin: Path, doc) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fiche_kb(ident, nom, **extra):
    return {"id": ident, "produit": "claude-code", "categorie": "commandes", "nom": nom, "gabarit": "court",
            "groupe": None, "origine": "cc-commandes", "usage": f"{nom} <arg>", "usage_nature": "syntaxe",
            "description_source": f"Runs {nom}.", "description": f"Lance {nom}.", "exemple": f"{nom} x",
            "exemple_origine": "source", "disponibilite": None, "statut_usage": "inconnu",
            "recommandation": {"verdict": "tester", "pourquoi": "Pour ton projet."}, "commentee": True,
            "contexte_empreinte": "0" * 40, "contexte_sections": {"projet.x": {"sha1": "1" * 40, "pourquoi": "lié"}},
            "retiree": False, "maj_le": "2026-10-20",
            "sources": [{"url": "https://code.claude.com/docs/en/commands", "libelle": "commands", "officielle": True}],
            "historique": [{"date": "2026-10-20", "changement": "ajoutée à l'inventaire"}], **extra}


@pytest.fixture
def depot(tmp_path):
    """Dépôt producteur minimal : une catégorie de la base, un quotidien, versions, journaux privés, sans profil."""
    d = tmp_path / "depot"
    data = d / "docs" / "data"
    _json(data / "kb" / "claude" / "commandes.json", {
        "perimetre": "claude", "categorie": "commandes", "maj_le": "2026-10-20", "total": 3, "commentees": 3,
        "contexte_empreinte": "0" * 40, "entrees": [
            _fiche_kb("claude-code-commandes-a", "/a"),
            _fiche_kb("claude-code-commandes-b", "/b", description=f"Utile pour {PROJET} dans {CHEMIN}"),
            _fiche_kb("claude-code-commandes-c", "/c", champ_futur="valeur nouvelle",
                      description_source=f"Contact {COURRIEL}"),
        ]})
    (data / "kb" / "claude" / "reevaluations.jsonl").write_text(json.dumps(
        {"date": "2026-10-21", "id": "claude-code-commandes-a", "motif": "contexte", "verdict_avant": "tester",
         "verdict_apres": "utiliser"}, ensure_ascii=False) + "\n", encoding="utf-8")
    _json(data / "kb" / "a-tester.json", {"genere_le": "2026-10-21T04:00:00+02:00", "total": 1, "tronque": False, "entrees": [
        {"id": "claude-code-commandes-a", "produit": "claude-code", "categorie": "commandes", "nom": "/a", "usage": "/a <arg>",
         "usage_nature": "syntaxe", "exemple": "/a x", "verdict": "tester", "pourquoi": "essai", "essai":
         {"date": "2026-10-21", "par": MISSION}, "date_ajout": "2026-10-20"}]})
    _json(data / "claude" / "2026-10-21.json", {
        "date": "2026-10-21", "genere_le": "2026-10-21T04:10:00+02:00", "perimetre": "claude", "agent": "claude-code",
        "contexte_empreinte": "0" * 40, "synthese": f"Rien pour {PROJET}.", "ecartes": [], "sources_en_echec": [],
        "elements": [{"id": "claude-code-2.1.400", "ids_bruts": ["cc-2.1.400"], "produit": "claude-code",
                      "version": "2.1.400", "date_publication": "2026-10-20", "type": "nouveaute",
                      "titre": "Nouvelle option", "resume": f"Option utile à {PROJET}.", "impact": "fort",
                      "pour_toi": f"Teste-la dans {CHEMIN}.", "projets_concernes": [PROJET],
                      "action": {"description": "essayer", "etapes": ["claude --x"], "effort": "5min"},
                      "certitude": "officiel", "contexte_sections": {}, "kb_refs": ["claude-code-commandes-a"],
                      "sources": [{"url": "https://github.com/anthropics/claude-code/releases", "libelle": "notes",
                                   "officielle": True}]}]})
    _json(data / "versions.json", [{"outil": "Claude Code", "version": "2.1.399", "detectee_le": "2026-10-21",
                                    "methode": "claude --version", "derniere_publiee": "2.1.400",
                                    "source_derniere": "https://github.com/anthropics/claude-code/releases",
                                    "statut": "en_retard", "pertinent_pour_profil": True, "note": f"poste de {PROJET}"}])
    _json(data / "etat.json", {"releve_le": "2026-10-21", "pertinent_pour_profil": True, "outils": {}, "comptes": {}})
    (d / "kb-essais.yaml").write_text(yaml.safe_dump([{"date": "2026-10-21", "id": "claude-code-commandes-a",
                                                       "par": MISSION, "rapport": "rapports/x.md"}]), encoding="utf-8")
    (d / "kb-rejugements.yaml").write_text(yaml.safe_dump([{"date": "2026-10-04", "plafond": 30, "motif": "contexte",
                                                            "ids": ["claude-code-commandes-b"]}]), encoding="utf-8")
    return d


@pytest.fixture
def instance(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    profil = tmp_path / "instance.json"
    _json(profil, {"schema": "delta.instance", "version": 1, "identite": "essai-l1", "mode": "essai", "home": str(home)})
    return mod_racines.resoudre(profil=profil, env={})


def _empreintes(dossier: Path) -> dict:
    return {p.relative_to(dossier).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(dossier.rglob("*")) if p.is_file()}


def _detecteur():
    return Detecteur([PROJET])


def _octets_generation(racines) -> bytes:
    actif = json.loads(racines.commun_actif.read_text(encoding="utf-8"))
    dossier = racines.commun / actif["generation"]
    return b"".join(p.read_bytes() for p in sorted(dossier.rglob("*")) if p.is_file())


# --- racines ---

def test_racines_profil_instance_par_defaut_et_declarees(tmp_path):
    home = tmp_path / "h"
    _json(tmp_path / "p.json", {"schema": "delta.instance", "version": 1, "identite": "neuve", "mode": "neuf",
                                "home": str(home), "racines": {"cache": str(home / "c")}})
    r = mod_racines.resoudre(profil=tmp_path / "p.json", env={})
    assert r.etat == home / ".local/state/delta/neuve" and r.cache == home / "c" and r.origine == "instance"
    assert r.personnel == home / ".local/state/delta/neuve/delta-ia/personnel"
    assert r.commun == home / "c/delta-ia/commun"


def test_racines_refus(tmp_path):
    with pytest.raises(mod_racines.RacinesInvalides, match="non désignées"):
        mod_racines.resoudre(env={})
    _json(tmp_path / "p.json", {"schema": "delta.instance", "version": 1, "identite": "x", "mode": "neuf",
                                "home": str(tmp_path / "h"), "racines": {"etat": "/var/ailleurs"}})
    with pytest.raises(mod_racines.RacinesInvalides, match="HOME"):
        mod_racines.resoudre(profil=tmp_path / "p.json", env={})
    _json(tmp_path / "q.json", {"schema": "delta.instance", "version": 1, "identite": "x", "mode": "neuf",
                                "home": str(tmp_path), "inconnue": 1})
    with pytest.raises(mod_racines.RacinesInvalides, match="clés inconnues"):
        mod_racines.resoudre(profil=tmp_path / "q.json", env={})
    with pytest.raises(mod_racines.RacinesInvalides, match="incomplètes"):
        mod_racines.resoudre(env={"DELTA_INSTANCE": "x", "XDG_STATE_HOME": "/a"})


def test_racines_environnement_et_historique(tmp_path):
    env = {"DELTA_INSTANCE": "i", "XDG_CONFIG_HOME": "/i/conf", "XDG_STATE_HOME": "/i/etat", "XDG_CACHE_HOME": "/i/cache",
           "XDG_RUNTIME_DIR": "/i/run"}
    r = mod_racines.resoudre(env=env, historique=True)  # l'instance de l'environnement prime : pas de mélange
    assert (r.etat, r.origine) == (Path("/i/etat"), "environnement")
    h = mod_racines.resoudre(env={}, historique=True, home=tmp_path)
    assert h.etat == tmp_path / ".local/state/delta" and h.cache == tmp_path / ".cache/delta" and h.origine == "historique"


# --- classement ---

def test_classement_chemins_et_heritage():
    assert cl.famille_de("claude/2026-10-21.json") == "quotidien"
    assert cl.famille_de("kb/openai/skills.json") == "kb_catalogue"
    assert cl.famille_de("kb/claude/reevaluations.jsonl") == "reevaluations"
    assert cl.famille_de("divers/nouveau.json") is None
    assert cl.classer("kb_catalogue", "entrees[].usage") == cl.COMMUN
    assert cl.classer("kb_catalogue", "entrees[].description") == cl.SCINDER
    assert cl.classer("kb_catalogue", "entrees[].recommandation.nouveau") == cl.PERSONNEL  # sous un conteneur P
    assert cl.classer("kb_catalogue", "entrees[].champ_futur") == cl.INCONNU
    assert cl.classer("modeles", "modeles.*.prix_api.entree_usd") == cl.COMMUN
    assert cl.classer("modeles", "modeles.*.prix_api.note") == cl.SCINDER  # texte libre en attente en L1
    assert cl.classer("modeles", "modeles.*.constats_internes[].constat") == cl.PERSONNEL
    chemins = {n for n, _, _ in cl.feuilles("modeles", {"modeles": {"gpt-x": {"sources_champs": {"spec": {"url": "u"}}}}})}
    assert chemins == {"modeles.*.sources_champs.*.url"}


# --- import ---

def test_import_separe_les_couches(depot, instance):
    avant = _empreintes(depot)
    res = importer(depot, instance, _detecteur())
    assert _empreintes(depot) == avant  # entrées lues sans modification, rien écrit dans le dépôt
    octets = _octets_generation(instance).decode("utf-8")
    for interdit in (COURRIEL, CHEMIN, MISSION, PROJET, "pour_toi", "recommandation", "statut_usage", "champ_futur",
                     "valeur nouvelle", "contexte_sections", "impact", "Lance /a"):
        assert interdit not in octets, interdit
    lecteur = Lecteur(instance)
    assert lecteur.commun_statut == "disponible"
    fiche_c = lecteur.fiches["kb:claude:claude-code-commandes-c"]
    assert "description_source" not in fiche_c and fiche_c["usage"] == "/c <arg>"  # seul le champ suspect est retenu
    assert lecteur.fiches["kb:claude:claude-code-commandes-b"]["description_source"] == "Runs /b."
    veille = lecteur.fiches["veille:claude:claude-code-2.1.400"]
    assert veille["publications"][0]["jour"] == "2026-10-21" and veille["publications"][0]["version"] == "2.1.400"
    assert "titre" not in veille["publications"][0]  # texte S en attente
    assert lecteur.fiches["version:claude-code"]["derniere_publiee"] == "2.1.400"
    motifs = {(r["objet"], r["chemin"], r["motif"]) for r in res.refus}
    assert ("kb:claude:claude-code-commandes-c", "entrees[].champ_futur", "champ_inconnu") in motifs
    assert ("kb:claude:claude-code-commandes-c", "entrees[].description_source", "donnee_personnelle:courriel") in motifs
    attente = json.loads((instance.personnel / "en_attente.json").read_text(encoding="utf-8"))["objets"]
    champs_c = attente["kb:claude:claude-code-commandes-c"][0]["champs"]
    assert champs_c["champ_futur"] == "valeur nouvelle" and COURRIEL in champs_c["description_source"]
    assert PROJET in attente["kb:claude:claude-code-commandes-b"][0]["champs"]["description"]
    erreurs, comptes = fidelite(depot, instance)
    assert erreurs == [] and comptes["essais"] == 1 and comptes["essais_a_tester"] == 1 and comptes["reevaluations"] == 1


def test_import_retrouve_avis_et_essais(depot, instance):
    importer(depot, instance, _detecteur())
    bloc = Lecteur(instance).fiche("claude-code-commandes-a")["personnel"]
    assert bloc["statut"] == "importe"
    assert bloc["avis"]["recommandation"] == {"verdict": "tester", "pourquoi": "Pour ton projet."}
    assert bloc["essais"] == [{"date": "2026-10-21", "par": MISSION, "rapport": "rapports/x.md", "source": "kb-essais.yaml"}]
    assert bloc["reevaluations"][0]["verdict_apres"] == "utiliser"
    assert any(h["fichier"] == "docs/data/kb/a-tester.json" and h["champs"]["essai"]["par"] == MISSION
               for h in bloc["historique_importe"])
    veille = Lecteur(instance).fiche("veille:claude:claude-code-2.1.400")["personnel"]
    assert veille["historique_importe"][0]["champs"]["impact"] == "fort"
    rejuge = Lecteur(instance).fiche("claude-code-commandes-b")["personnel"]
    assert rejuge["rejugements"] == [{"date": "2026-10-04", "plafond": 30, "motif": "contexte", "source": "kb-rejugements.yaml"}]


def test_relance_idempotente_et_profil_absent(depot, instance):
    assert not (depot / "profil.yaml").exists() and not (depot / "CONTEXTE.md").exists()
    premier = importer(depot, instance, _detecteur())
    etat = _empreintes(instance.etat)
    cache = _empreintes(instance.cache)
    second = importer(depot, instance, _detecteur())
    assert second.generation == premier.generation and second.changements == []
    assert _empreintes(instance.etat) == etat and _empreintes(instance.cache) == cache
    overlay = json.loads((instance.personnel / "overlay.json").read_text(encoding="utf-8"))
    assert overlay["profil_empreinte"] is None
    (depot / "profil.yaml").write_text("priorites: []\n", encoding="utf-8")
    troisieme = importer(depot, instance, _detecteur())
    assert troisieme.generation == premier.generation  # le commun ne dépend pas du profil
    assert json.loads((instance.personnel / "overlay.json").read_text(encoding="utf-8"))["profil_empreinte"]


def test_droits_prives_et_racines_hors_depot(depot, instance, tmp_path):
    importer(depot, instance, _detecteur())
    for chemin in (instance.personnel, instance.personnel / "overlay.json", instance.commun_actif):
        assert schemas.permissions_privees(chemin)
    dedans = mod_racines.Racines(*(depot / "docs" / "data" / n for n in ("c", "e", "k", "r")), origine="essai")
    with pytest.raises(ImportImpossible, match="dépôt producteur"):
        importer(depot, dedans, _detecteur())
    assert not (depot / "docs" / "data" / "e").exists()


def test_verrou_un_seul_ecrivain(depot, instance):
    with verrou(instance.verrous, "couches-import"):
        with pytest.raises(MagasinOccupe):
            importer(depot, instance, _detecteur())


def test_collision_et_id_manquant_refuses(depot, instance):
    _json(depot / "docs" / "data" / "kb" / "openai" / "commandes.json", {
        "perimetre": "openai", "categorie": "commandes", "maj_le": "2026-10-20", "total": 1,
        "entrees": [_fiche_kb("claude-code-commandes-a", "/a")]})
    with pytest.raises(ImportImpossible, match="collision"):
        importer(depot, instance, _detecteur())


def test_fichier_inconnu_refuse_jamais_exporte(depot, instance):
    _json(depot / "docs" / "data" / "nouveau.json", {"x": COURRIEL})
    res = importer(depot, instance, _detecteur())
    assert {"objet": "fichier:nouveau.json", "fichier": "docs/data/nouveau.json", "chemin": None,
            "motif": "fichier_inconnu"} in res.refus
    assert COURRIEL not in _octets_generation(instance).decode("utf-8")


# --- validation et lecture ---

def test_generation_alteree_ou_version_inconnue_indisponible(depot, instance):
    importer(depot, instance, _detecteur())
    actif = json.loads(instance.commun_actif.read_text(encoding="utf-8"))
    dossier = instance.commun / actif["generation"]
    assert valider.main(["--commun", str(dossier)]) == 0
    cible = dossier / "kb" / "claude" / "commandes.json"
    doc = json.loads(cible.read_text(encoding="utf-8"))
    doc["entrees"][0]["pour_toi"] = "injecté"
    cible.write_text(json.dumps(doc), encoding="utf-8")
    lecteur = Lecteur(instance)
    assert lecteur.commun_statut == "indisponible" and "invalide" in lecteur.motif
    assert lecteur.fiche("claude-code-commandes-a")["commun"]["statut"] == "indisponible"
    assert valider.main(["--commun", str(dossier)]) == 1
    actif["schema_version"] = 2
    instance.commun_actif.write_text(json.dumps(actif), encoding="utf-8")
    assert "non prise en charge" in Lecteur(instance).motif


def test_validation_refuse_champ_p_meme_avec_empreintes_recalculees(depot, instance, tmp_path):
    importer(depot, instance, _detecteur())
    actif = json.loads(instance.commun_actif.read_text(encoding="utf-8"))
    copie = tmp_path / "copie" / actif["generation"]
    shutil.copytree(instance.commun / actif["generation"], copie)
    cible = copie / "kb" / "claude" / "commandes.json"
    doc = json.loads(cible.read_text(encoding="utf-8"))
    doc["entrees"][0]["statut_usage"] = "utiliser"
    cible.write_text(json.dumps(doc), encoding="utf-8")
    manifest = json.loads((copie / "manifest.json").read_text(encoding="utf-8"))
    for f in manifest["fichiers"]:
        if f["chemin"] == "kb/claude/commandes.json":
            f["taille"], f["sha256"] = cible.stat().st_size, hashlib.sha256(cible.read_bytes()).hexdigest()
    (copie / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    erreurs = schemas.valider_generation(copie, Detecteur())
    assert any("champs non communs" in e or "génération incohérente" in e for e in erreurs)


def test_lecteur_public_sans_personnel_et_instance_neuve(depot, instance):
    importer(depot, instance, _detecteur())
    public = Lecteur(instance, personnel=False)
    assert "personnel" not in public.fiche("claude-code-commandes-a")
    assert "avis_local" not in public.chercher("/a")["resultats"][0]
    shutil.rmtree(instance.personnel)
    neuve = Lecteur(instance)
    assert neuve.fiche("/a")["personnel"] == {"couche": "personnel", "statut": "non_personnalise", "magasin": "absent",
                                               "avis": None}


def test_lecteur_resolution_recherche_et_avis_a_revoir(depot, instance):
    importer(depot, instance, _detecteur())
    lecteur = Lecteur(instance)
    assert lecteur.resoudre("/b") == ["kb:claude:claude-code-commandes-b"]
    assert lecteur.fiche("inexistant")["statut"] == "introuvable"
    resultats = lecteur.chercher("runs /a")["resultats"]
    assert resultats[0]["identite"] == "kb:claude:claude-code-commandes-a" and resultats[0]["avis_local"]
    chemin = depot / "docs" / "data" / "kb" / "claude" / "commandes.json"
    doc = json.loads(chemin.read_text(encoding="utf-8"))
    doc["entrees"][0]["usage"] = "/a <autre>"
    _json(chemin, doc)
    overlay_avant = (instance.personnel / "overlay.json").read_bytes()
    importer(depot, instance, _detecteur())
    (instance.personnel / "overlay.json").write_bytes(overlay_avant)  # avis rendu sur l'ancien fait
    assert Lecteur(instance).fiche("/a")["personnel"]["statut"] == "a_revoir"


def test_termes_instance_lus_a_l_execution(tmp_path):
    (tmp_path / "CONTEXTE.md").write_text("# Contexte\n", encoding="utf-8")
    termes = termes_instance(None, home=tmp_path / "quelquun", contexte=tmp_path / "CONTEXTE.md")
    assert termes == ["quelquun"]
    d = Detecteur(["quelquun"])
    assert d.motif("voir /Users/me/.codex et /Users/my-project/src") is None  # exemples de documentation
    assert d.motif("chemin " + CHEMIN) == "chemin personnel"
    assert d.motif("ai@example.com") is None and d.motif(COURRIEL) == "courriel"
    assert d.motif("Quelquun a écrit") == "terme de l'instance"
    assert d.motif({"cle": MISSION}) == "trace OPÉRER"


def test_cli_codes(depot, instance, tmp_path, capsys, monkeypatch):
    profil = tmp_path / "instance.json"
    monkeypatch.delenv("DELTA_INSTANCE", raising=False)
    assert cli.main(["fiche", "x"]) == 2
    assert cli.main(["--instance", str(profil), "importer", "--depot", str(depot)]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["generation"].startswith("g-") and COURRIEL not in json.dumps(sortie)
    assert cli.main(["--instance", str(profil), "verifier", "--depot", str(depot)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_donnees_reelles_du_depot(tmp_path):
    """Critère de fin L1 sur les données suivies du dépôt : fidélité, commun sans P, relance idempotente, entrées
    inchangées. Un champ nouveau d'un producteur est refusé (signalé), pas une erreur de ce test."""
    home = tmp_path / "home"
    home.mkdir()
    _json(tmp_path / "i.json", {"schema": "delta.instance", "version": 1, "identite": "reel", "mode": "essai", "home": str(home)})
    racines = mod_racines.resoudre(profil=tmp_path / "i.json", env={})
    suivis = [RACINE / p for p in ("kb-essais.yaml", "kb-rejugements.yaml", "profil.yaml") if (RACINE / p).is_file()]
    avant = _empreintes(RACINE / "docs" / "data") | {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in suivis}
    premier = importer(RACINE, racines)
    assert importer(RACINE, racines).changements == []
    apres = _empreintes(RACINE / "docs" / "data") | {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in suivis}
    assert apres == avant
    erreurs, comptes = fidelite(RACINE, racines)
    assert erreurs == [] and comptes["identites_communes"] > 1000
    assert schemas.valider_generation(premier.dossier, Detecteur(termes_instance(RACINE))) == []

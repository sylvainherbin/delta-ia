"""Import privé et projection commune conservatrice (lot L1 de la conception « Delta-IA en deux couches », §2.2 et §6 étape 1).

Lit, sans les modifier, `docs/data/**` et les journaux privés du dépôt producteur (`kb-essais.yaml`, `kb-rejugements.yaml`,
empreinte de `profil.yaml`), puis écrit hors du dépôt :
- une génération commune `<cache>/delta-ia/commun/<generation>/` (fiches de la base, méthodes, modèles, veille, versions
  publiées, noms) limitée aux champs C certains, avec son manifeste, validée avant de devenir active ;
- le magasin privé `<etat>/delta-ia/personnel/` : avis, essais, réévaluations et rejugements par identité (`overlay.json`),
  textes S, champs inconnus et champs C retenus pour donnée personnelle (`en_attente.json`), relevé d'import (`import.json`).
Les vues dérivées (index, semaine, recherche, récents, à tester) ne sont pas recopiées au commun : elles se recalculeront
depuis le commun (lot L2) ; leurs champs P et S vont au magasin privé. Même entrée, mêmes octets : une relance ne réécrit rien.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import classement as cl
from . import schemas
from .racines import Racines
from .sentinelles import Detecteur, termes_instance
from .stockage import dossier_prive, ecrire, serialiser, sha256_fichier, verrou

# Journaux privés du dépôt producteur lus par l'import (D119, rejugements), et profil dont seule l'empreinte est gardée.
ESSAIS, REJUGEMENTS, PROFIL = "kb-essais.yaml", "kb-rejugements.yaml", "profil.yaml"
ORDRE = ("kb_catalogue", "methodes", "modeles", "quotidien", "versions", "a_tester", "recent", "index_veille", "etat",
         "recherche", "semaine", "index_semaine", "noms")  # reevaluations : rattachées ligne par ligne
AVIS = ("kb_catalogue", "methodes", "modeles")  # familles dont `statut_usage` et `recommandation` sont l'avis courant


class ImportImpossible(RuntimeError):
    """Entrée illisible, collision d'identités, écriture refusée ou entrées modifiées pendant l'import."""


@dataclass
class Unite:
    """Une fiche (ou la racine d'un fichier) dans un fichier source : ses arbres C, P et S reconstruits feuille à feuille."""
    commun: dict = field(default_factory=dict)
    personnel: dict = field(default_factory=dict)
    attente: dict = field(default_factory=dict)


@dataclass
class Entree:
    rel: str  # relatif au dépôt
    octets: bytes
    sha256: str


@dataclass
class Resultat:
    generation: str
    dossier: Path
    comptes: dict
    refus: list
    changements: list[str]


def slug_outil(outil) -> str | None:
    """`Codex CLI (terminal)` → `codex-cli-terminal` : identité stable d'une ligne de versions, qui n'a pas d'id."""
    slug = re.sub(r"[^a-z0-9]+", "-", outil.lower()).strip("-") if isinstance(outil, str) else ""
    return slug or None


def _placer(arbre: dict, chemin: list, valeur) -> None:
    noeud = arbre
    for cle in chemin[:-1]:
        noeud = noeud.setdefault(f"#{cle}" if isinstance(cle, int) else cle, {})
    noeud[f"#{chemin[-1]}" if isinstance(chemin[-1], int) else chemin[-1]] = valeur


def _figer(valeur):
    """Dictionnaires dont toutes les clés sont des indices (`#3`) → listes, dans l'ordre d'origine."""
    if not isinstance(valeur, dict):
        return valeur
    if valeur and all(isinstance(k, str) and k.startswith("#") and k[1:].isdigit() for k in valeur):
        return [_figer(valeur[k]) for k in sorted(valeur, key=lambda k: int(k[1:]))]
    return {k: _figer(v) for k, v in valeur.items()}


def _documents(entree: Entree) -> list:
    try:
        texte = entree.octets.decode("utf-8")
        if entree.rel.endswith(".jsonl"):
            return [json.loads(ligne) for ligne in texte.splitlines() if ligne.strip()]
        return [json.loads(texte)]
    except (UnicodeDecodeError, ValueError) as e:
        raise ImportImpossible(f"{entree.rel}: JSON illisible ({e})") from e


class Projection:
    """Répartition des feuilles classées de chaque fichier entre unités (fiche ou racine de fichier) et couches."""

    def __init__(self, detecteur: Detecteur):
        self.detecteur = detecteur
        self.unites: dict[str, dict[str, Unite]] = {}  # fichier → identité → unité, dans l'ordre d'apparition
        self.racines: dict[str, dict] = {}  # fichier → champs C de sa racine
        self.refus: list[dict] = []
        self.ids_kb: dict[str, str] = {}  # id de fiche → identité `kb:<perimetre>:<id>`

    def _identite(self, famille: str, rel: str, doc, reel: list) -> tuple[str, list] | None:
        parties = rel.split("/")
        if famille == "quotidien" and len(reel) >= 2 and reel[0] == "elements":
            return f"veille:{parties[0]}:{doc['elements'][reel[1]].get('id')}", reel[2:]
        if famille in ("kb_catalogue", "methodes", "modeles", "a_tester", "recent") and len(reel) >= 2 and reel[0] == "entrees":
            ident = doc["entrees"][reel[1]].get("id")
            espace = {"kb_catalogue": f"kb:{parties[-2]}:", "methodes": "kb:delta:methodes:",
                      "modeles": "kb:delta:modeles:"}.get(famille)
            return (espace + ident if espace else self.ids_kb.get(ident, f"kb:introuvable:{ident}")), reel[2:]
        if famille == "modeles" and len(reel) >= 2 and reel[0] in ("modeles", "forfaits"):
            return f"kb:delta:{reel[0]}:{reel[1]}", reel[2:]
        if famille == "versions" and reel and isinstance(reel[0], int):
            return f"version:{slug_outil(doc[reel[0]].get('outil'))}", reel[1:]
        return None

    def _controler_ids(self, famille: str, rel: str, doc) -> None:
        if famille == "versions":
            slugs = [slug_outil(x.get("outil")) if isinstance(x, dict) else None for x in doc] if isinstance(doc, list) else []
            if None in slugs or len(set(slugs)) != len(slugs):
                raise ImportImpossible(f"docs/data/{rel}: outil absent ou en double")
            return
        cle = {"quotidien": "elements"}.get(famille, "entrees")
        if famille not in ("quotidien", "kb_catalogue", "methodes", "modeles", "a_tester", "recent"):
            return
        membres = doc.get(cle) if isinstance(doc, dict) else None
        if not isinstance(membres, list):
            return
        vus: set = set()
        for m in membres:
            ident = m.get("id") if isinstance(m, dict) else None
            if not isinstance(ident, str) or not ident:
                raise ImportImpossible(f"docs/data/{rel}: membre de `{cle}` sans id")
            if ident in vus:
                raise ImportImpossible(f"docs/data/{rel}: id en double {ident}")
            vus.add(ident)

    def ajouter(self, rel: str, famille: str, doc) -> None:
        self._controler_ids(famille, rel, doc)
        unites = self.unites.setdefault(rel, {})
        racine: dict = {}
        for norm, reel, valeur in cl.feuilles(famille, doc):
            classe = cl.classer(famille, norm)
            porteur = self._identite(famille, rel, doc, reel)
            ident, sous = porteur if porteur else (f"fichier:{rel}", reel)
            u = unites.setdefault(ident, Unite())
            sous = sous or ["valeur"]
            if classe == cl.COMMUN:
                nature = self.detecteur.motif(valeur)
                if nature:
                    self.refus.append({"objet": ident, "fichier": f"docs/data/{rel}", "chemin": norm,
                                       "motif": f"donnee_personnelle:{nature}"})
                    _placer(u.attente, sous, valeur)
                else:
                    _placer(u.commun if porteur else racine, sous, valeur)
            elif classe == cl.PERSONNEL:
                _placer(u.personnel, sous, valeur)
            else:
                if classe == cl.INCONNU:
                    self.refus.append({"objet": ident, "fichier": f"docs/data/{rel}", "chemin": norm, "motif": "champ_inconnu"})
                _placer(u.attente, sous, valeur)
        self.racines[rel] = _figer(racine)

    def fiches(self, rel: str) -> list[tuple[str, dict]]:
        """(identité, champs C) des fiches d'un fichier ; une fiche dont l'identifiant a été retenu n'est pas exportée."""
        sortie = []
        for ident, u in self.unites.get(rel, {}).items():
            if ident.startswith("fichier:"):
                continue
            contenu = _figer(u.commun)
            cle = "outil" if ident.startswith("version:") else "id"
            if contenu.get(cle) is None and not ident.startswith(("kb:delta:modeles:", "kb:delta:forfaits:")):
                continue
            sortie.append((ident, contenu))
        return sortie


def _fiche(ident: str, contenu: dict) -> dict:
    return {"identite": ident, "empreinte": schemas.empreinte_fiche(ident, contenu), **contenu}


def _doc(famille: str, **champs) -> dict:
    return {"schema": schemas.COMMUN, "schema_version": schemas.VERSION, "famille": famille, **champs}


def _garder(racine: dict, cles: tuple) -> dict:
    return {k: racine[k] for k in cles if k in racine}


def construire_commun(p: Projection, familles: dict[str, list[str]]) -> dict[str, dict]:
    """Documents communs de la génération, par chemin relatif ; `familles` : famille → fichiers lus."""
    from ..kb.catalogue import construire_noms
    communs: dict[str, dict] = {}
    toutes_kb = []
    for rel in sorted(familles.get("kb_catalogue", [])):
        fiches = [_fiche(i, c) for i, c in p.fiches(rel)]
        toutes_kb += [{k: v for k, v in f.items() if k not in ("identite", "empreinte")} for f in fiches]
        communs[rel] = _doc("kb", **_garder(p.racines[rel], ("perimetre", "categorie", "maj_le")),
                            total=len(fiches), entrees=fiches)
    if "kb/methodes.json" in familles.get("methodes", []):
        fiches = [_fiche(i, c) for i, c in p.fiches("kb/methodes.json")]
        communs["kb/methodes.json"] = _doc("methodes", **_garder(p.racines["kb/methodes.json"], ("categorie", "maj_le", "origine")),
                                           total=len(fiches), entrees=fiches)
    if "kb/modeles.json" in familles.get("modeles", []):
        couples, modeles = [], {}
        for ident, contenu in p.fiches("kb/modeles.json"):
            if ident.startswith("kb:delta:forfaits:"):
                continue  # forfaits : S entier en L1
            if "id" in contenu:
                couples.append(_fiche(ident, contenu))
            else:
                modeles[ident[len("kb:delta:modeles:"):]] = _fiche(ident, contenu)
        collisions = {f["identite"] for f in couples} & {f["identite"] for f in modeles.values()}
        if collisions:
            raise ImportImpossible(f"collision d'identité entre couples et modèles : {sorted(collisions)[:3]}")
        r = p.racines["kb/modeles.json"]
        communs["kb/modeles.json"] = _doc(
            "modeles", **_garder(r, ("categorie", "date_releve", "maj_le", "origine")),
            **({"version_source": r["schema_version"]} if "schema_version" in r else {}),
            total=len(couples), total_modeles=len(modeles), entrees=couples, modeles=modeles)
    quotidiens = familles.get("quotidien", [])
    for perimetre in sorted({rel.split("/")[0] for rel in quotidiens}):
        publications: dict[str, list] = {}
        for rel in sorted(r for r in quotidiens if r.startswith(f"{perimetre}/")):
            racine = p.racines[rel]
            for ident, contenu in p.fiches(rel):
                publications.setdefault(ident, []).append(
                    {"jour": racine.get("date"), "agent": racine.get("agent"), "genere_le": racine.get("genere_le"),
                     **{k: v for k, v in contenu.items() if k != "id"}, "_id": contenu["id"]})
        fiches = []
        for ident, pubs in publications.items():
            id_brut = pubs[0]["_id"]
            fiches.append(_fiche(ident, {"id": id_brut, "publications": [
                {k: v for k, v in pub.items() if k != "_id"} for pub in pubs]}))
        fiches.sort(key=lambda f: (f["publications"][0]["jour"] or "", f["identite"]))
        communs[f"veille/{perimetre}.json"] = _doc("veille", perimetre=perimetre, total=len(fiches), entrees=fiches)
    if "versions.json" in familles.get("versions", []):
        fiches = [_fiche(i, c) for i, c in p.fiches("versions.json")]
        communs["versions.json"] = _doc("versions", total=len(fiches), entrees=fiches)
    if toutes_kb:
        communs["kb/noms.json"] = _doc("noms", noms=construire_noms(toutes_kb))
    return communs


def _index_commun(communs: dict) -> dict[str, dict]:
    index = {}
    for doc in communs.values():
        for f in doc.get("entrees", []) if isinstance(doc.get("entrees"), list) else []:
            index[f["identite"]] = f
        for f in (doc.get("modeles") or {}).values():
            index[f["identite"]] = f
    return index


def nouvel_objet(ident: str, fiche: dict | None) -> dict:
    """Objet personnel v1 (conception §2.2) d'une identité ; absence d'avis = `inconnu`/null, jamais `ignorer`."""
    if fiche is not None:
        statut = "reference_retiree" if fiche.get("retiree") else "importe"
    elif ident.startswith(("fichier:", "kb:delta:forfaits:")):
        statut = "importe"  # racine de fichier ou forfait (S entier en L1) : pas de fiche commune attendue
    else:
        statut = "reference_introuvable"
    return {"objet": ident, "commun_empreinte": fiche["empreinte"] if fiche else None, "statut": statut, "langue": "fr",
            "observe_le": None, "evalue_le": None, "statut_usage": "inconnu", "recommandation": None, "pour_toi": None,
            "action": None, "exemple_local": None, "essais": [], "reevaluations": [], "rejugements": [],
            "historique_importe": []}


def construire_personnel(p: Projection, communs: dict, reevaluations: list[tuple[str, list]],
                         journaux: dict[str, bytes]) -> tuple[dict, dict]:
    index = _index_commun(communs)
    overlay: dict[str, dict] = {}
    attente: dict[str, list] = {}

    def objet(ident: str) -> dict:
        if ident not in overlay:
            overlay[ident] = nouvel_objet(ident, index.get(ident))
        return overlay[ident]

    for rel, unites in p.unites.items():
        famille = cl.famille_de(rel)
        for ident, u in unites.items():
            perso, s = _figer(u.personnel), _figer(u.attente)
            if perso:
                o = objet(ident)
                o["historique_importe"].append({"fichier": f"docs/data/{rel}", "champs": perso})
                if famille in AVIS:
                    o["statut_usage"] = perso.get("statut_usage", o["statut_usage"])
                    o["recommandation"] = perso.get("recommandation", o["recommandation"])
            if s:
                attente.setdefault(ident, []).append({"fichier": f"docs/data/{rel}", "champs": s})
    for rel, lignes in reevaluations:
        perimetre = rel.split("/")[1]
        for ligne in lignes:
            if not isinstance(ligne, dict) or not ligne.get("id"):
                raise ImportImpossible(f"docs/data/{rel}: ligne de réévaluation sans id")
            ident = f"kb:{perimetre}:{ligne['id']}"
            inconnues = sorted(k for k in ligne if cl.classer("reevaluations", k) == cl.INCONNU)
            p.refus += [{"objet": ident, "fichier": f"docs/data/{rel}", "chemin": k, "motif": "champ_inconnu"} for k in inconnues]
            if inconnues:
                attente.setdefault(ident, []).append({"fichier": f"docs/data/{rel}", "champs": {k: ligne[k] for k in inconnues}})
            objet(ident)["reevaluations"].append({k: v for k, v in ligne.items() if k not in inconnues})
    for rel, cle_liste, champ in ((ESSAIS, None, "essais"), (REJUGEMENTS, "ids", "rejugements")):
        if rel not in journaux:
            continue
        try:
            lignes = yaml.safe_load(journaux[rel].decode("utf-8")) or []
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            raise ImportImpossible(f"{rel}: illisible ({e})") from e
        if not isinstance(lignes, list) or not all(isinstance(x, dict) for x in lignes):
            raise ImportImpossible(f"{rel}: liste d'objets attendue")
        for ligne in lignes:
            ids = [ligne.get("id")] if cle_liste is None else (ligne.get(cle_liste) or [])
            reste = {k: v for k, v in ligne.items() if k not in ("id", cle_liste)}
            for i in ids:
                objet(p.ids_kb.get(i, f"kb:introuvable:{i}"))[champ].append({**reste, "source": rel})
    return dict(sorted(overlay.items())), dict(sorted(attente.items()))


def _empreintes(depot: Path, rels) -> dict[str, str | None]:
    return {r: (sha256_fichier(depot / r) if (depot / r).is_file() else None) for r in rels}


def lire_entrees(depot: Path) -> list[Entree]:
    rels = sorted(p.relative_to(depot).as_posix() for p in (depot / "docs" / "data").rglob("*") if p.is_file())
    rels += [r for r in (ESSAIS, REJUGEMENTS, PROFIL) if (depot / r).is_file()]
    sortie = []
    for rel in rels:
        octets = (depot / rel).read_bytes()
        sortie.append(Entree(rel, octets, hashlib.sha256(octets).hexdigest()))
    return sortie


def projeter(entrees: list[Entree], detecteur: Detecteur) -> tuple[dict, dict, dict, Projection, list[str]]:
    """Sans écriture : (documents communs, overlay, en attente, projection, fichiers de docs/data de famille inconnue)."""
    p = Projection(detecteur)
    par_famille: dict[str, list[tuple[str, list]]] = {}
    inconnus = []
    for e in entrees:
        if not e.rel.startswith("docs/data/"):
            continue
        rel = e.rel[len("docs/data/"):]
        famille = cl.famille_de(rel)
        if famille is None:
            if not rel.endswith(".gitkeep"):
                inconnus.append(rel)
            continue
        par_famille.setdefault(famille, []).append((rel, _documents(e)))
    for rel, docs in par_famille.get("kb_catalogue", []):
        for x in docs[0].get("entrees", []) if isinstance(docs[0], dict) else []:
            if not isinstance(x, dict) or not x.get("id"):
                raise ImportImpossible(f"docs/data/{rel}: entrée sans id")
            if x["id"] in p.ids_kb:
                raise ImportImpossible(f"collision d'identité : {x['id']} présent deux fois dans la base")
            p.ids_kb[x["id"]] = f"kb:{rel.split('/')[1]}:{x['id']}"
    for famille in ORDRE:
        for rel, docs in par_famille.get(famille, []):
            p.ajouter(rel, famille, docs[0])
    familles = {f: [rel for rel, _ in lst] for f, lst in par_famille.items()}
    communs = construire_commun(p, familles)
    journaux = {e.rel: e.octets for e in entrees if e.rel in (ESSAIS, REJUGEMENTS)}
    overlay, attente = construire_personnel(p, communs, par_famille.get("reevaluations", []), journaux)
    return communs, overlay, attente, p, inconnus


def _manifeste(communs: dict) -> dict:
    fichiers = [{"chemin": rel, "taille": len(serialiser(doc)), "sha256": hashlib.sha256(serialiser(doc)).hexdigest()}
                for rel, doc in sorted(communs.items())]
    dates = [d for doc in communs.values() for d in _dates(doc)]
    return {"schema": schemas.MANIFEST, "schema_version": schemas.VERSION, "generation": schemas.generation_de(fichiers),
            "publie_le": None, "donnees_du": max(dates) if dates else None,
            "schemas_requis": [f"{schemas.COMMUN}@{schemas.VERSION}"], "langues": [],
            "couverture": {rel: doc.get("total", len(doc.get("noms", {}))) for rel, doc in sorted(communs.items())},
            "fichiers": fichiers}


def _dates(doc) -> list[str]:
    sortie = [doc[c][:10] for c in ("maj_le", "date_releve") if isinstance(doc.get(c), str)]
    for f in doc.get("entrees", []) if isinstance(doc.get("entrees"), list) else []:
        sortie += [pub["jour"] for pub in f.get("publications", []) if isinstance(pub.get("jour"), str)]
    return sortie


def importer(depot: Path, racines: Racines, detecteur: Detecteur | None = None) -> Resultat:
    """Import complet, sous le verrou du magasin. `ImportImpossible` si une règle de sûreté n'est pas tenue."""
    depot = depot.resolve()
    for nom in ("configuration", "etat", "cache", "runtime"):
        p = getattr(racines, nom).resolve()
        if p == depot or depot in p.parents:
            raise ImportImpossible(f"racine {nom} dans le dépôt producteur : aucune écriture n'y est permise")
    if not (depot / "docs" / "data").is_dir():
        raise ImportImpossible(f"{depot}: docs/data introuvable")
    detecteur = detecteur or Detecteur(termes_instance(depot))
    with verrou(racines.verrous, "couches-import"):
        return _importer(depot, racines, detecteur)


def _importer(depot: Path, racines: Racines, detecteur: Detecteur) -> Resultat:
    entrees = lire_entrees(depot)
    avant = {e.rel: e.sha256 for e in entrees}
    communs, overlay, attente, p, inconnus = projeter(entrees, detecteur)
    manifest = _manifeste(communs)
    generation = manifest["generation"]
    refus = p.refus + [{"objet": f"fichier:{r}", "fichier": f"docs/data/{r}", "chemin": None, "motif": "fichier_inconnu"}
                       for r in inconnus]
    profil = next((e for e in entrees if e.rel == PROFIL), None)
    comptes = {"entrees": len(avant), "objets_communs": len(_index_commun(communs)), "objets_personnels": len(overlay),
               "objets_en_attente": len(attente), "refus": len(refus)}
    prives = {
        "overlay.json": {"schema": schemas.PERSONNEL, "schema_version": schemas.VERSION, "vue": "overlay",
                         "commun_generation": generation, "profil_empreinte": profil.sha256 if profil else None,
                         "objets": overlay},
        "en_attente.json": {"schema": schemas.PERSONNEL, "schema_version": schemas.VERSION, "vue": "en_attente",
                            "commun_generation": generation, "objets": attente, "refus": refus},
        "import.json": {"schema": schemas.PERSONNEL, "schema_version": schemas.VERSION, "vue": "import",
                        "commun_generation": generation, "comptes": comptes,
                        "entrees": [{"chemin": r, "sha256": s} for r, s in sorted(avant.items())]},
    }
    for nom, doc in prives.items():
        erreurs = schemas.valider_personnel(doc, doc["vue"], nom)
        if erreurs:
            raise ImportImpossible(f"{nom} invalide : {erreurs[:3]}")
    if _empreintes(depot, avant) != avant:
        raise ImportImpossible("entrées modifiées pendant la lecture : import abandonné, rien n'est écrit")
    changements: list[str] = []
    dossier = _ecrire_generation(racines, communs, manifest, detecteur, changements)
    dossier_prive(racines.personnel)
    for nom, doc in prives.items():
        if ecrire(racines.personnel / nom, doc):
            changements.append(f"personnel/{nom}")
    _activer(racines, generation, dossier, changements)
    if _empreintes(depot, avant) != avant:
        raise ImportImpossible("entrées modifiées pendant l'import : relancer l'import")
    return Resultat(generation, dossier, comptes, refus, changements)


def _ecrire_generation(racines: Racines, communs: dict, manifest: dict, detecteur: Detecteur,
                       changements: list[str]) -> Path:
    """Construction dans `.tmp-<generation>/<generation>`, validation complète, puis renommage atomique du dossier."""
    generation = manifest["generation"]
    base = dossier_prive(racines.commun)
    cible = base / generation
    if cible.is_dir() and not schemas.valider_generation(cible, detecteur):
        return cible  # déjà construite et valide : relance sans écriture
    chantier = base / f".tmp-{generation}"
    if chantier.exists():
        shutil.rmtree(chantier)
    neuf = chantier / generation
    for rel, doc in communs.items():
        ecrire(neuf / rel, doc)
    ecrire(neuf / "manifest.json", manifest)
    erreurs = schemas.valider_generation(neuf, detecteur)
    if erreurs:
        shutil.rmtree(chantier)
        raise ImportImpossible(f"génération commune refusée : {erreurs[:5]}")
    if cible.exists():
        shutil.rmtree(cible)  # même nom mais invalide (interrompue, altérée) : remplacée
    neuf.rename(cible)
    chantier.rmdir()
    changements.append(f"commun/{generation}")
    return cible


def _activer(racines: Racines, generation: str, dossier: Path, changements: list[str]) -> None:
    """Pointeur vers la génération validée ; la précédente est gardée pour retour, les plus anciennes sont retirées."""
    try:
        actuel = json.loads(racines.commun_actif.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        actuel = {}
    actuel = actuel if isinstance(actuel, dict) else {}
    precedente = actuel.get("precedente")
    if actuel.get("generation") not in (None, generation):
        precedente = actuel["generation"]
    doc = {"schema": schemas.COMMUN, "schema_version": schemas.VERSION, "vue": "actif", "generation": generation,
           "manifest_sha256": sha256_fichier(dossier / "manifest.json"), "precedente": precedente}
    if ecrire(racines.commun_actif, doc):
        changements.append("commun-actif.json")
    for d in racines.commun.iterdir():
        if d.is_dir() and schemas.RE_GENERATION.fullmatch(d.name) and d.name not in (generation, precedente):
            shutil.rmtree(d)

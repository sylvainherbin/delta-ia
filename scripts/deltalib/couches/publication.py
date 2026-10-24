"""Publication versionnée additionnelle, miroir local et surveillance du producteur (conception §2.3, §6 étape 1, lot L2).

Route publiée (`docs/commun/v1/` du dépôt producteur, servie à `<site>/commun/v1/`), indépendante des routes actuelles :
- `<generation>/` : copie octet pour octet d'une génération validée (immuable, nommée par l'empreinte de ses fichiers) ;
- `index.json` : document de publication (`delta.manifest`, vue `publication`) : génération servie, empreinte de son
  manifeste, heure du cycle de publication, précédente génération gardée pour retour, cycle attendu, dernier jour couvert
  par périmètre. L'heure de publication vit ici et pas dans le manifeste : la même génération a les mêmes octets chez le
  producteur et dans chaque miroir.

Synchroniseur (instance lectrice) : requête conditionnelle sur `index.json` (ETag, Last-Modified), téléchargement des
seuls fichiers changés dans une génération provisoire, validation complète (schémas, empreintes, chemins), puis bascule
d'un seul pointeur. Un échec garde la dernière génération valide et consigne l'erreur ; un 304 renouvelle seulement
`verifie_le`. Aucune donnée personnelle n'est envoyée : une requête GET anonyme par fichier.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

from . import schemas
from .racines import Racines
from .sentinelles import Detecteur
from .stockage import dossier_prive, ecrire, ecrire_octets_public, ecrire_public, sha256_fichier, verrou

INDEX = "index.json"
AGENT = "Delta-IA-lecteur/1 (+https://ai.orqyra.io/)"
TAILLE_INDEX = 1 << 20
DELAI = 30


class PublicationImpossible(RuntimeError):
    pass


class SynchroEchec(RuntimeError):
    pass


def maintenant_iso(maintenant: datetime | None = None) -> str:
    return (maintenant or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _lire_json(chemin: Path):
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _derniers_jours(dossier: Path) -> dict:
    sortie = {}
    for chemin in sorted((dossier / "veille").glob("*.json")):
        doc = _lire_json(chemin) or {}
        jours = [j.get("date") for j in doc.get("jours") or [] if isinstance(j, dict) and isinstance(j.get("date"), str)]
        sortie[doc.get("perimetre", chemin.stem)] = {"dernier_jour": max(jours) if jours else None}
    return sortie


# --------------------------------------------------------------------------------------------------- producteur

def publier(racines: Racines, route: Path, maintenant: datetime | None = None, cycle_attendu_h: int = 24) -> dict:
    """Copie la génération active de l'instance productrice dans `route` et réécrit `index.json`. Garde la génération
    publiée précédente (retour), retire les plus anciennes. Rend {generation, precedente, nouvelle}."""
    actif = _lire_json(racines.commun_actif)
    if not isinstance(actif, dict) or not schemas.RE_GENERATION.fullmatch(str(actif.get("generation"))):
        raise PublicationImpossible("aucune génération commune active à publier")
    generation = actif["generation"]
    source = racines.commun / generation
    erreurs = schemas.valider_generation(source, Detecteur())
    if erreurs:
        raise PublicationImpossible(f"génération {generation} invalide : {erreurs[0]}")
    route.mkdir(parents=True, exist_ok=True)
    ancien = _lire_json(route / INDEX)
    ancien = ancien if isinstance(ancien, dict) and not schemas.valider_publication(ancien) else None
    cible = route / generation
    nouvelle = not cible.is_dir()
    if nouvelle:
        chantier = route / f".tmp-{generation}"
        if chantier.exists():
            shutil.rmtree(chantier)
        for f in sorted(p for p in source.rglob("*") if p.is_file()):
            ecrire_octets_public(chantier / f.relative_to(source), f.read_bytes())
        chantier.rename(cible)
    erreurs = schemas.valider_generation(cible, Detecteur())
    if erreurs:
        raise PublicationImpossible(f"copie publiée de {generation} invalide : {erreurs[0]}")
    manifest_sha = sha256_fichier(cible / "manifest.json")
    if ancien and ancien["generation"] != generation and (route / ancien["generation"]).is_dir():
        precedente = {"generation": ancien["generation"], "manifest_sha256": ancien["manifest_sha256"]}
    else:
        precedente = ancien.get("precedente") if ancien else None
    doc = {"schema": schemas.MANIFEST, "schema_version": schemas.VERSION, "vue": "publication", "generation": generation,
           "manifest_sha256": manifest_sha, "publie_le": maintenant_iso(maintenant), "precedente": precedente,
           "cycle_attendu_h": cycle_attendu_h, "perimetres": _derniers_jours(cible)}
    erreurs = schemas.valider_publication(doc)
    if erreurs:
        raise PublicationImpossible(f"index.json invalide : {erreurs[0]}")
    ecrire_public(route / INDEX, doc)
    garder = {generation} | ({precedente["generation"]} if precedente else set())
    for d in route.iterdir():
        if d.is_dir() and (schemas.RE_GENERATION.fullmatch(d.name) and d.name not in garder or d.name.startswith(".tmp-")):
            shutil.rmtree(d)
    return {"generation": generation, "precedente": precedente["generation"] if precedente else None, "nouvelle": nouvelle}


def valider_route(route: Path) -> list[str]:
    """Route publiée : index valide, génération servie et précédente valides et aux empreintes annoncées, rien d'autre."""
    doc = _lire_json(route / INDEX)
    if doc is None:
        return [f"{route}/{INDEX} illisible"]
    erreurs = schemas.valider_publication(doc)
    if erreurs:
        return erreurs
    attendues = {doc["generation"]: doc["manifest_sha256"]}
    if doc.get("precedente"):
        attendues[doc["precedente"]["generation"]] = doc["precedente"]["manifest_sha256"]
    for generation, sha in attendues.items():
        dossier = route / generation
        erreurs += [f"{generation}/{e}" for e in schemas.valider_generation(dossier, Detecteur())]
        if (dossier / "manifest.json").is_file() and sha256_fichier(dossier / "manifest.json") != sha:
            erreurs.append(f"{generation}: manifeste différent de l'index")
    for p in route.iterdir():
        if p.name != INDEX and p.name not in attendues:
            erreurs.append(f"{p.name}: entrée non annoncée par l'index")
    return erreurs


# --------------------------------------------------------------------------------------------------- lecteur

def telecharger(url: str, entetes: dict, limite: int) -> tuple[int, dict, bytes]:
    """GET anonyme : (statut, en-têtes, corps) ; 304 rendu sans corps ; au-delà de `limite` octets, erreur."""
    requete = urllib.request.Request(url, headers={"User-Agent": AGENT, **entetes})
    try:
        with urllib.request.urlopen(requete, timeout=DELAI) as r:
            corps = r.read(limite + 1)
            if len(corps) > limite:
                raise SynchroEchec(f"{url.rsplit('/', 1)[-1]} : au-delà de {limite} octets")
            return r.status or 200, {k.lower(): v for k, v in r.headers.items()}, corps
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, {k.lower(): v for k, v in e.headers.items()}, b""
        raise SynchroEchec(f"HTTP {e.code} sur {url.rsplit('/', 1)[-1]}") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise SynchroEchec(f"réseau indisponible ({type(e).__name__})") from e


def _etat(racines: Racines) -> dict:
    doc = _lire_json(racines.etat / "delta-ia" / "synchro.json")
    if not isinstance(doc, dict) or schemas.valider_synchro(doc):
        doc = {}
    base = {"schema": schemas.COMMUN, "schema_version": schemas.VERSION, "vue": "synchro", "source": None,
            "verifie_le": None, "derniere_tentative": None, "erreur": None, "etag": None, "last_modified": None,
            "publie_le": None, "generation": None}
    return {**base, **{k: v for k, v in doc.items() if k in base}}


def chemin_synchro(racines: Racines) -> Path:
    return racines.etat / "delta-ia" / "synchro.json"


def synchroniser(racines: Racines, base_url: str, maintenant: datetime | None = None, obtenir=telecharger) -> dict:
    """Met le miroir local à jour depuis la route publiée `base_url` (se terminant par `/`). Rend
    {statut: inchange|nouvelle|echec, generation, erreur}. Sous le verrou du magasin commun."""
    base_url = base_url if base_url.endswith("/") else base_url + "/"
    with verrou(racines.verrous, "couches-import"):
        etat = _etat(racines)
        etat["derniere_tentative"] = maintenant_iso(maintenant)
        etat["source"] = base_url
        try:
            res = _synchroniser(racines, base_url, etat, obtenir)
            etat["erreur"] = None
            etat["verifie_le"] = etat["derniere_tentative"]
        except SynchroEchec as e:
            etat["erreur"] = str(e)
            res = {"statut": "echec", "generation": etat.get("generation"), "erreur": str(e)}
        ecrire(chemin_synchro(racines), etat)
        return res


def _synchroniser(racines: Racines, base_url: str, etat: dict, obtenir) -> dict:
    actif = _lire_json(racines.commun_actif) or {}
    entetes = {}
    if etat.get("generation") and etat["generation"] == actif.get("generation"):
        if etat.get("etag"):
            entetes["If-None-Match"] = etat["etag"]
        if etat.get("last_modified"):
            entetes["If-Modified-Since"] = etat["last_modified"]
    statut, en_tetes, corps = obtenir(urljoin(base_url, INDEX), entetes, TAILLE_INDEX)
    if statut == 304:
        return {"statut": "inchange", "generation": actif.get("generation"), "erreur": None}
    if statut != 200:
        raise SynchroEchec(f"HTTP {statut} sur {INDEX}")
    try:
        index = json.loads(corps.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise SynchroEchec(f"{INDEX} illisible") from e
    erreurs = schemas.valider_publication(index)
    if erreurs:
        raise SynchroEchec(f"{INDEX} refusé : {erreurs[0]}")
    generation = index["generation"]
    etat.update(etag=en_tetes.get("etag"), last_modified=en_tetes.get("last-modified"), publie_le=index["publie_le"])
    dossier_local = racines.commun / generation
    if (actif.get("generation") == generation and actif.get("manifest_sha256") == index["manifest_sha256"]
            and dossier_local.is_dir()):
        etat["generation"] = generation
        _pointer(racines, generation, dossier_local, index["publie_le"])
        return {"statut": "inchange", "generation": generation, "erreur": None}
    base = dossier_prive(racines.commun)
    chantier = base / f".sync-{generation}"
    if chantier.exists():
        shutil.rmtree(chantier)
    neuf = chantier / generation
    try:
        _, _, octets = obtenir(urljoin(base_url, f"{generation}/manifest.json"), {}, TAILLE_INDEX * 8)
        if hashlib.sha256(octets).hexdigest() != index["manifest_sha256"]:
            raise SynchroEchec("manifeste différent de l'index")
        manifest = json.loads(octets.decode("utf-8"))
        fichiers = manifest.get("fichiers") if isinstance(manifest, dict) else None
        if not isinstance(fichiers, list):
            raise SynchroEchec("manifeste sans liste de fichiers")
        actif_dossier = racines.commun / str(actif.get("generation"))
        for f in fichiers:
            rel = f.get("chemin") if isinstance(f, dict) else None
            if not isinstance(rel, str) or rel.startswith("/") or ".." in rel.split("/") or not isinstance(f.get("taille"), int):
                raise SynchroEchec("chemin refusé dans le manifeste")
            local = actif_dossier / rel
            if local.is_file() and not local.is_symlink() and sha256_fichier(local) == f.get("sha256"):
                contenu = local.read_bytes()  # fichier inchangé : repris de la génération active
            else:
                _, _, contenu = obtenir(urljoin(base_url, f"{generation}/{rel}"), {}, min(f["taille"], schemas.TAILLE_MAX))
            _poser(neuf / rel, contenu)
        _poser(neuf / "manifest.json", octets)
        erreurs = schemas.valider_generation(neuf, Detecteur())
        if erreurs:
            raise SynchroEchec(f"génération {generation} refusée : {erreurs[0]}")
        if dossier_local.exists():
            shutil.rmtree(dossier_local)
        neuf.rename(dossier_local)
    finally:
        if chantier.exists():
            shutil.rmtree(chantier)
    etat["generation"] = generation
    _pointer(racines, generation, dossier_local, index["publie_le"])
    return {"statut": "nouvelle", "generation": generation, "erreur": None}


def _poser(chemin: Path, contenu: bytes) -> None:
    dossier_prive(chemin.parent)
    chemin.write_bytes(contenu)
    chemin.chmod(0o600)


def _pointer(racines: Racines, generation: str, dossier: Path, publie_le: str) -> None:
    from .projection import _activer
    _activer(racines, generation, dossier, [], origine="synchro", publie_le=publie_le)


# --------------------------------------------------------------------------------------------------- fraîcheur

def _age_h(horodatage: str | None, maintenant: datetime) -> float | None:
    if not isinstance(horodatage, str):
        return None
    try:
        t = datetime.fromisoformat(horodatage.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (maintenant - t).total_seconds() / 3600


def fraicheur(maintenant: datetime, verifie_le: str | None, publie_le: str | None, donnees_du: str | None = None,
              ancienne_h: int = 24, tres_ancienne_j: int = 7) -> str | None:
    """`recente`, `ancienne` (vérification ou publication > `ancienne_h`), `tres_ancienne` (> `tres_ancienne_j` jours) ;
    sans vérification ni publication (instance productrice), d'après le dernier jour des données ; None si rien de daté."""
    ages = [a for a in (_age_h(verifie_le, maintenant), _age_h(publie_le, maintenant)) if a is not None]
    if not ages and isinstance(donnees_du, str):
        a = _age_h(f"{donnees_du}T23:59:59+00:00", maintenant)
        ages = [a] if a is not None else []
    if not ages:
        return None
    pire = max(ages)
    return "tres_ancienne" if pire > tres_ancienne_j * 24 else "ancienne" if pire > ancienne_h else "recente"


def surveiller(index: dict, maintenant: datetime | None = None, marge_h: int = 6, retard_jours: int = 2) -> dict:
    """Producteur : cycle de publication manqué (`publie_le` plus vieux que le cycle attendu et la marge), périmètre dont
    le dernier jour couvert date de plus de `retard_jours`. Rend {ok, alertes, age_h}."""
    maintenant = maintenant or datetime.now(timezone.utc)
    erreurs = schemas.valider_publication(index)
    if erreurs:
        return {"ok": False, "alertes": [f"index_invalide: {erreurs[0]}"], "age_h": None}
    alertes = []
    age = _age_h(index["publie_le"], maintenant)
    if age is not None and age > index["cycle_attendu_h"] + marge_h:
        alertes.append(f"cycle_manque: dernière publication il y a {age:.0f} h (cycle {index['cycle_attendu_h']} h)")
    limite = (maintenant - timedelta(days=retard_jours)).date().isoformat()
    for perimetre in sorted(set(index["perimetres"]) | {"claude", "openai", "actu"}):
        jour = (index["perimetres"].get(perimetre) or {}).get("dernier_jour")
        if jour is None:
            alertes.append(f"perimetre_absent: {perimetre}")
        elif jour < limite:
            alertes.append(f"perimetre_en_retard: {perimetre} (dernier jour {jour})")
    return {"ok": not alertes, "alertes": alertes, "age_h": round(age, 1) if age is not None else None}

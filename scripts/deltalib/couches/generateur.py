"""Générateur commun isolé du profil (conception §3.1, lot L2).

Son entrée est un dossier écrit par l'étape de production (`<etat>/delta-ia/production/entree-commune/`) : documents
communs factuels déjà réduits à la liste positive, sans aucun fichier du dépôt producteur, du profil ni du magasin
personnel. Le générateur n'ouvre que ce dossier et le cache de traductions désigné ; toute autre lecture est refusée et
chaque lecture est relevée (`lus`), ce qui permet d'inspecter ce qu'il a reçu. Il ajoute l'enveloppe bilingue (`textes`),
appelle au besoin le rédacteur isolé (`traduction`) dans le budget donné, puis rend la génération et son manifeste.
Il n'écrit que le cache de traductions ; la génération est validée et activée par l'appelant.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import schemas
from .stockage import ecrire, serialiser
from .traduction import GLOSSAIRE, Bilan, Cache, Unite, traduire

ENTREE = "entree.json"


class LectureRefusee(PermissionError):
    """Le générateur commun a tenté de lire hors de son entrée."""


class EntreeInvalide(ValueError):
    pass


class LecteurBorne:
    def __init__(self, permis: list[Path]):
        self.permis = [p.resolve() for p in permis]
        self.lus: list[str] = []

    def __call__(self, chemin: Path) -> bytes:
        reel = chemin.resolve()
        if not any(reel == p or p in reel.parents for p in self.permis):
            raise LectureRefusee(f"lecture hors de l'entrée du générateur commun : {chemin.name}")
        self.lus.append(str(reel))
        return reel.read_bytes()


def ecrire_entree(dossier: Path, communs: dict[str, dict], couverture_sources: dict) -> bool:
    """Entrée du générateur : documents factuels et couverture des sources. Remplacée en bloc ; rien n'est réécrit si
    elle est identique. Rend True si elle a changé."""
    fichiers = [{"chemin": rel, "sha256": hashlib.sha256(serialiser(doc)).hexdigest()} for rel, doc in sorted(communs.items())]
    meta = {"schema": schemas.COMMUN, "schema_version": schemas.VERSION, "vue": "entree", "fichiers": fichiers,
            "couverture_sources": couverture_sources}
    try:
        if (dossier / ENTREE).read_bytes() == serialiser(meta):
            return False
    except OSError:
        pass
    chantier = dossier.with_name(f".{dossier.name}.tmp")
    if chantier.exists():
        shutil.rmtree(chantier)
    for rel, doc in communs.items():
        ecrire(chantier / "communs" / rel, doc)
    ecrire(chantier / ENTREE, meta)
    ancien = dossier.with_name(f".{dossier.name}.ancien")
    if dossier.exists():
        if ancien.exists():
            shutil.rmtree(ancien)
        dossier.rename(ancien)
    chantier.rename(dossier)
    if ancien.exists():
        shutil.rmtree(ancien)
    return True


@dataclass
class Generation:
    communs: dict
    manifest: dict
    lus: list[str]
    bilan: Bilan
    textes: int  # textes anglais portant une enveloppe
    traduits: int  # dont traduits en français
    cache_modifie: bool


def _lire_entree(entree: Path, lire: LecteurBorne) -> tuple[dict, dict]:
    try:
        meta = json.loads(lire(entree / ENTREE).decode("utf-8"))
    except (OSError, ValueError) as e:
        raise EntreeInvalide(f"entrée du générateur illisible : {e}") from e
    if (not isinstance(meta, dict) or meta.get("schema") != schemas.COMMUN or meta.get("vue") != "entree"
            or meta.get("schema_version") != schemas.VERSION or not isinstance(meta.get("fichiers"), list)):
        raise EntreeInvalide("entrée du générateur : vue entree v1 attendue")
    communs = {}
    for f in meta["fichiers"]:
        octets = lire(entree / "communs" / f["chemin"])
        if hashlib.sha256(octets).hexdigest() != f["sha256"]:
            raise EntreeInvalide(f"entrée du générateur : {f['chemin']} différent de son empreinte")
        communs[f["chemin"]] = json.loads(octets.decode("utf-8"))
    return meta, communs


def unites_a_traduire(communs: dict) -> list[Unite]:
    """Une unité par texte source distinct (deux fiches au même extrait partagent une traduction)."""
    vues: dict[str, Unite] = {}
    for doc in communs.values():
        if doc.get("famille") != "kb":
            continue
        for fiche in doc["entrees"]:
            for champ, origine in schemas.CHAMPS_TEXTES["kb"].items():
                texte = fiche.get(origine)
                if isinstance(texte, str) and texte.strip():
                    vues.setdefault(f"{schemas.sha256_texte(texte)}:{champ}", Unite(f"{fiche['identite']}#{champ}", champ, texte))
    return list(vues.values())


def envelopper(communs: dict, cache: Cache) -> tuple[int, int]:
    """Ajoute `textes` aux fiches de la base : anglais = extrait source, français = traduction en cache s'il y en a une."""
    textes = traduits = 0
    for doc in communs.values():
        if doc.get("famille") != "kb":
            continue
        for fiche in doc["entrees"]:
            enveloppe = {}
            for champ, origine in schemas.CHAMPS_TEXTES["kb"].items():
                texte = fiche.get(origine)
                if not (isinstance(texte, str) and texte.strip()):
                    continue
                langues = {"en": {"texte": texte, "statut": "source", "origine": origine}}
                fr = cache.get(texte, champ)
                if fr is not None:
                    langues["fr"] = {"texte": fr, "statut": "automatique", "de": "en",
                                     "source_sha256": schemas.sha256_texte(texte), "glossaire": GLOSSAIRE}
                    traduits += 1
                textes += 1
                enveloppe[champ] = langues
            if enveloppe:
                fiche["textes"] = enveloppe
            else:
                fiche.pop("textes", None)
    return textes, traduits


def _dates(doc) -> list[str]:
    sortie = [doc[c][:10] for c in ("maj_le", "date_releve") if isinstance(doc.get(c), str)]
    for f in doc.get("entrees", []) if isinstance(doc.get("entrees"), list) else []:
        sortie += [pub["jour"] for pub in f.get("publications", []) if isinstance(pub.get("jour"), str)]
    return sortie


def manifeste(communs: dict, couverture_sources: dict, textes: int = 0, traduits: int = 0) -> dict:
    fichiers = [{"chemin": rel, "taille": len(serialiser(doc)), "sha256": hashlib.sha256(serialiser(doc)).hexdigest()}
                for rel, doc in sorted(communs.items())]
    dates = [d for doc in communs.values() for d in _dates(doc)]
    return {"schema": schemas.MANIFEST, "schema_version": schemas.VERSION, "generation": schemas.generation_de(fichiers),
            "publie_le": None, "donnees_du": max(dates) if dates else None,
            "schemas_requis": [f"{schemas.COMMUN}@{schemas.VERSION}"],
            "langues": (["en"] if textes else []) + (["fr"] if traduits else []),
            "couverture": {rel: doc.get("total", len(doc.get("noms", {}))) for rel, doc in sorted(communs.items())},
            "couverture_langues": {"en": {"textes": textes, "disponibles": textes, "statut": "source"},
                                   "fr": {"textes": textes, "disponibles": traduits, "manquants": textes - traduits,
                                          "repli": "en"}},
            "couverture_sources": couverture_sources, "fichiers": fichiers}


def generer(entree: Path, traductions: Path | None = None, redacteur=None, budget: int = 0,
            le: str | None = None) -> Generation:
    """Génération commune depuis la seule entrée ; `budget` = unités au plus envoyées au rédacteur (0 : cache seul)."""
    lire = LecteurBorne([entree] + ([traductions] if traductions is not None else []))
    meta, communs = _lire_entree(entree, lire)
    cache = Cache(traductions, "fr", lire=lire)
    bilan = Bilan()
    if redacteur is not None and budget > 0:
        traduire(unites_a_traduire(communs), cache, redacteur, budget, le or date.today().isoformat(), bilan,
                 apres_lot=cache.enregistrer)
    cache_modifie = cache.enregistrer() or cache.ecrit
    textes, traduits = envelopper(communs, cache)
    return Generation(communs, manifeste(communs, meta.get("couverture_sources") or {}, textes, traduits),
                      lire.lus, bilan, textes, traduits, cache_modifie)

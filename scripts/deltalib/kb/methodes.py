"""Fiches de méthode locales (D121) : kb-methodes/*.md → docs/data/kb/methodes.json.

Une fiche de méthode est rédigée à la main, jamais extraite d'une page de documentation : elle n'entre dans aucun
lot de `/delta-kb`, n'est jamais `retiree` par l'extraction, et disparaît seulement si son fichier source est supprimé.
Chaque fichier : un en-tête YAML (id, nom, produits, verifie_le, versions, certitude, sources), puis le corps en Markdown.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml

from .modeles import PERIMETRE_DU_PRODUIT, slug

DOSSIER_SOURCE = "kb-methodes"
CATEGORIE = "methodes"
CERTITUDES = ("officiel", "rapporte", "non_confirme")
CHAMPS_ENTETE = ("id", "nom", "produits", "verifie_le", "versions", "certitude", "sources")
RE_ENTETE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
RE_BLOC = re.compile(r"^```[^\n]*\n(.*?)\n```[ \t]*$", re.S | re.M)


class FicheMethodeInvalide(ValueError):
    pass


def chemin_methodes(racine: Path) -> Path:
    return racine / "docs" / "data" / "kb" / "methodes.json"


def lire_fiche(chemin: Path) -> dict:
    """Une entrée de `methodes.json` depuis un fichier source ; lève FicheMethodeInvalide si l'en-tête est incomplet."""
    brut = chemin.read_text(encoding="utf-8")
    m = RE_ENTETE.match(brut)
    if not m:
        raise FicheMethodeInvalide(f"{chemin.name} : en-tête YAML `---` absent")
    try:
        entete = yaml.safe_load(m.group(1))
    except yaml.YAMLError as err:
        raise FicheMethodeInvalide(f"{chemin.name} : en-tête illisible ({err})") from err
    if not isinstance(entete, dict):
        raise FicheMethodeInvalide(f"{chemin.name} : l'en-tête n'est pas un dictionnaire")
    manquants = [c for c in CHAMPS_ENTETE if entete.get(c) in (None, "", [], {})]
    if manquants:
        raise FicheMethodeInvalide(f"{chemin.name} : champs absents de l'en-tête : {', '.join(manquants)}")
    ident = str(entete["id"])
    if ident != slug(ident) or ident != chemin.stem:
        raise FicheMethodeInvalide(f"{chemin.name} : `id` doit être le nom du fichier sans extension, en minuscules et tirets")
    produits = entete["produits"]
    if not isinstance(produits, list) or any(p not in PERIMETRE_DU_PRODUIT for p in produits):
        raise FicheMethodeInvalide(f"{chemin.name} : `produits` parmi {', '.join(PERIMETRE_DU_PRODUIT)}")
    if entete["certitude"] not in CERTITUDES:
        raise FicheMethodeInvalide(f"{chemin.name} : `certitude` parmi {', '.join(CERTITUDES)}")
    verifie = entete["verifie_le"]
    verifie = verifie.isoformat() if isinstance(verifie, date) else str(verifie)
    try:
        date.fromisoformat(verifie)
    except ValueError as err:
        raise FicheMethodeInvalide(f"{chemin.name} : `verifie_le` n'est pas une date AAAA-MM-JJ") from err
    if not isinstance(entete["versions"], dict):
        raise FicheMethodeInvalide(f"{chemin.name} : `versions` doit associer un produit à une version")
    sources = []
    for s in entete["sources"] if isinstance(entete["sources"], list) else []:
        if not isinstance(s, dict) or not str(s.get("url", "")).startswith("https://") or not str(s.get("libelle", "")).strip():
            raise FicheMethodeInvalide(f"{chemin.name} : chaque source porte une `url` https et un `libelle`")
        sources.append({"url": s["url"], "libelle": str(s["libelle"]).strip(), "officielle": entete["certitude"] == "officiel"})
    if not sources:
        raise FicheMethodeInvalide(f"{chemin.name} : `sources` vide")
    corps = m.group(2).strip()
    if not corps:
        raise FicheMethodeInvalide(f"{chemin.name} : corps vide")
    bloc = RE_BLOC.search(corps)
    return {
        "id": f"methode-{ident}", "produit": produits[0], "produits": list(produits), "categorie": CATEGORIE,
        "nom": str(entete["nom"]).strip(), "gabarit": "complet", "description": corps, "description_source": None,
        "usage": bloc.group(1) if bloc else "", "usage_nature": "syntaxe", "exemple": None, "disponibilite": None,
        "statut_usage": "inconnu", "recommandation": None, "sources": sources, "commentee": True,
        "certitude": entete["certitude"], "versions": {str(k): str(v) for k, v in entete["versions"].items()},
        "verifie_le": verifie, "origine": "locale", "fichier_source": f"{DOSSIER_SOURCE}/{chemin.name}",
        "retiree": False, "maj_le": verifie,
    }


def construire_methodes(racine: Path) -> dict:
    """Le document de `methodes.json`, tiré des seuls fichiers de `kb-methodes/` (rien n'est lu ailleurs, rien n'est daté de « aujourd'hui »)."""
    dossier = racine / DOSSIER_SOURCE
    entrees = [lire_fiche(p) for p in sorted(dossier.glob("*.md"))] if dossier.is_dir() else []
    ids = [e["id"] for e in entrees]
    doublons = sorted({i for i in ids if ids.count(i) > 1})
    if doublons:
        raise FicheMethodeInvalide(f"identifiants en double : {', '.join(doublons)}")
    return {"categorie": CATEGORIE, "origine": "locale", "maj_le": max((e["maj_le"] for e in entrees), default=None),
            "total": len(entrees), "entrees": entrees}


def ecrire_methodes(racine: Path) -> dict:
    doc = construire_methodes(racine)
    chemin = chemin_methodes(racine)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(chemin)
    return doc

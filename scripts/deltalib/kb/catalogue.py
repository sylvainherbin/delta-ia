"""Catalogue docs/data/kb/<perimetre>/<categorie>.json : extraction, fusion avec l'existant, lots, commentaires.

Fusion (D40, D44) :
- entrée nouvelle : ajoutée avec `commentee: false` ;
- `usage` ou `description_source` changé (D48) : mis à jour, `commentee` repasse à false (le commentaire précédent
  reste lisible) ;
- autre changement de la source (URL, groupe, nature de l'usage) : mis à jour sans toucher au commentaire ;
- entrée absente d'une page extraite avec succès : `retiree: true` (jamais supprimée) ; elle reparaît si la page
  la décrit de nouveau. Les pages non extraites (échec, pas de copie) ne retirent rien.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..dates import maintenant_iso
from ..modeles import FormatInattendu
from .documentation import DocSource, lire_cache
from .extracteurs import EXTRACTEURS
from .modeles import (CATEGORIES, PRODUITS_PAR_PERIMETRE, STATUTS_USAGE, VERDICTS, EntreeExtraite, gabarit_de)

SEUIL_DEMI = {"complet": 60, "court": 150}  # au-delà, une catégorie est coupée en deux lots (D46)


def dossier(racine: Path, perimetre: str) -> Path:
    return racine / "docs" / "data" / "kb" / perimetre


def charger(racine: Path, perimetre: str) -> dict[str, dict]:
    entrees: dict[str, dict] = {}
    for cat in CATEGORIES:
        p = dossier(racine, perimetre) / f"{cat}.json"
        if p.exists():
            for e in json.loads(p.read_text(encoding="utf-8")).get("entrees", []):
                entrees[e["id"]] = e
    return entrees


def ecrire(racine: Path, perimetre: str, entrees: dict[str, dict]) -> None:
    d = dossier(racine, perimetre)
    d.mkdir(parents=True, exist_ok=True)
    horodatage = maintenant_iso()
    for cat in CATEGORIES:
        liste = sorted((e for e in entrees.values() if e["categorie"] == cat), key=lambda e: e["id"])
        doc = {"perimetre": perimetre, "categorie": cat, "maj_le": max((e["maj_le"] for e in liste), default=horodatage[:10]),
               "total": len(liste), "commentees": sum(1 for e in liste if e.get("commentee")), "entrees": liste}
        tmp = d / f"{cat}.json.tmp"
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(d / f"{cat}.json")


def extraire(racine: Path, docs: list[DocSource], surcharge: dict | None = None
             ) -> tuple[list[EntreeExtraite], set[str], list[dict]]:
    """Rend (entrées, docs extraites avec succès, échecs). Une doc sans copie locale est ignorée."""
    entrees: list[EntreeExtraite] = []
    ok: set[str] = set()
    echecs: list[dict] = []
    for d in docs:
        fichiers = lire_cache(racine, d, surcharge)
        if not fichiers:
            echecs.append({"doc": d.id, "erreur": "aucune copie locale (lancer fetch.py --kb)"})
            continue
        try:
            extraites = EXTRACTEURS[d.extracteur](d, fichiers)
        except FormatInattendu as e:
            echecs.append({"doc": d.id, "erreur": f"FormatInattendu: {e}"})
            continue
        entrees.extend(extraites)
        if d.extracteur != "pages" or len(fichiers) == len(d.fichiers()):
            ok.add(d.id)  # une doc à pages partiellement récupérée ne retire rien
    return _dedoublonner(entrees), ok, echecs


def _dedoublonner(entrees: list[EntreeExtraite]) -> list[EntreeExtraite]:
    """Même identifiant deux fois : le second prend le groupe dans son identifiant ; s'il collisionne encore, il est ignoré."""
    from .modeles import slug
    vus: dict[str, EntreeExtraite] = {}
    res = []
    for e in entrees:
        if e.id in vus:
            if vus[e.id].usage == e.usage:
                continue
            e.id = f"{e.produit}-{e.categorie}-{slug((e.groupe or e.origine) + '-' + (e.cle or e.nom))}"
            if e.id in vus:
                continue
        vus[e.id] = e
        res.append(e)
    return res


def nouvelle_entree(x: EntreeExtraite, jour: str) -> dict:
    return {
        "id": x.id, "produit": x.produit, "categorie": x.categorie, "nom": x.nom, "gabarit": gabarit_de(x.categorie),
        "description": None, "description_source": x.description_source, "usage": x.usage,
        "usage_nature": x.usage_nature, "exemple": None,
        "disponibilite": None, "statut_usage": "inconnu", "recommandation": None,
        "sources": [{"url": x.url, "libelle": x.libelle, "officielle": True}],
        "commentee": False, "retiree": False, "origine": x.origine, "groupe": x.groupe,
        "maj_le": jour, "historique": [{"date": jour, "changement": "ajoutée à l'inventaire"}],
    }


def fusionner(existantes: dict[str, dict], extraites: list[EntreeExtraite], docs_ok: set[str],
              jour: str | None = None) -> tuple[dict[str, dict], dict]:
    jour = jour or date.today().isoformat()
    res = {k: dict(v) for k, v in existantes.items()}
    modif = {"ajoutees": [], "usage_modifie": [], "description_source_modifiee": [], "retirees": [], "reapparues": []}
    presentes = set()
    for x in extraites:
        presentes.add(x.id)
        e = res.get(x.id)
        if e is None:
            res[x.id] = nouvelle_entree(x, jour)
            modif["ajoutees"].append(x.id)
            continue
        if e.get("retiree"):
            e["retiree"] = False
            e["historique"] = e.get("historique", []) + [{"date": jour, "changement": "de nouveau dans la documentation"}]
            e["maj_le"] = jour
            modif["reapparues"].append(x.id)
        if e.get("usage") != x.usage:
            e["usage"] = x.usage
            e["commentee"] = False
            e["historique"] = e.get("historique", []) + [{"date": jour, "changement": "usage modifié dans la documentation"}]
            e["maj_le"] = jour
            modif["usage_modifie"].append(x.id)
        if e.get("description_source") != x.description_source:  # D48
            e["description_source"] = x.description_source
            e["commentee"] = False
            e["historique"] = e.get("historique", []) + [{"date": jour, "changement": "description d'origine modifiée dans la documentation"}]
            e["maj_le"] = jour
            modif["description_source_modifiee"].append(x.id)
        e["usage_nature"] = x.usage_nature
        e["sources"] = [{"url": x.url, "libelle": x.libelle, "officielle": True}] + [
            s for s in e.get("sources", [])[1:] if s.get("url") != x.url]
        e["nom"], e["groupe"], e["origine"] = x.nom, x.groupe, x.origine
    for k, e in res.items():
        if k not in presentes and e.get("origine") in docs_ok and not e.get("retiree"):
            e["retiree"] = True
            e["historique"] = e.get("historique", []) + [{"date": jour, "changement": "absente de la documentation"}]
            e["maj_le"] = jour
            modif["retirees"].append(k)
    return res, modif


def mettre_a_jour(racine: Path, perimetre: str, docs: list[DocSource], ecrire_fichiers: bool = True,
                  surcharge: dict | None = None) -> dict:
    docs = [d for d in docs if d.perimetre == perimetre and d.active]
    extraites, ok, echecs = extraire(racine, docs, surcharge)
    entrees, modif = fusionner(charger(racine, perimetre), extraites, ok)
    if ecrire_fichiers:
        ecrire(racine, perimetre, entrees)
    return {"perimetre": perimetre, "genere_le": maintenant_iso(), "docs_extraites": sorted(ok), "echecs": echecs,
            "total": len(entrees), "a_commenter": sorted(k for k, e in entrees.items() if not e.get("commentee") and not e.get("retiree")),
            **modif}


# ----------------------------------------------------------------------------------------------- lots et commentaires

ORDRE_LOTS = ("commandes", "fonctionnalites", "skills", "plugins", "mcp", "raccourcis", "parametres")  # D51
QUARTS = ("parametres",)  # D50 : paramètres coupés en quarts
GROUPES = {"openai": {("skills", "plugins", "mcp"): "skills+plugins+mcp"}}  # D50 : lots regroupés


def lots(entrees: dict[str, dict], perimetre: str) -> list[dict]:
    """Lots D46, D50, D51 : par valeur décroissante ; paramètres en quarts ; catégorie complète coupée en deux
    au-delà du seuil de son gabarit ; skills, plugins et MCP regroupés pour openai."""
    res = []
    groupes = GROUPES.get(perimetre, {})
    deja: set[str] = set()
    for cat in ORDRE_LOTS:
        if cat in deja:
            continue
        groupe = next((g for g in groupes if cat in g), None)
        cats = groupe or (cat,)
        deja.update(cats)
        ids = sorted(k for k, e in entrees.items() if e["categorie"] in cats and not e.get("retiree"))
        if not ids:
            continue
        gab = gabarit_de(cat)
        nom = groupes.get(groupe, cat) if groupe else cat
        if cat in QUARTS:
            n = 4
        elif len(ids) > SEUIL_DEMI[gab]:
            n = 2
        else:
            n = 1
        taille = -(-len(ids) // n)
        parts = [(f"{nom}:{k + 1}" if n > 1 else nom, ids[k * taille:(k + 1) * taille]) for k in range(n)]
        for nom_lot, liste in parts:
            if liste:
                res.append({"lot": nom_lot, "perimetre": perimetre, "gabarit": gab, "entrees": len(liste),
                            "a_commenter": sum(1 for k in liste if not entrees[k].get("commentee")), "ids": liste})
    return res


def appliquer_commentaires(entrees: dict[str, dict], commentaires: dict, jour: str | None = None) -> list[str]:
    """Applique {id: {description, statut_usage, recommandation, exemple?, disponibilite?}} ; jamais `usage`."""
    jour = jour or date.today().isoformat()
    erreurs = []
    for k, c in commentaires.items():
        e = entrees.get(k)
        if e is None:
            erreurs.append(f"{k}: identifiant inconnu")
            continue
        interdits = set(c) - {"description", "statut_usage", "recommandation", "exemple", "disponibilite"}
        if interdits:
            erreurs.append(f"{k}: champs non modifiables par le commentaire : {sorted(interdits)}")
            continue
        if not isinstance(c.get("description"), str) or not c["description"].strip():
            erreurs.append(f"{k}: description absente")
            continue
        if c.get("statut_usage") not in STATUTS_USAGE:
            erreurs.append(f"{k}: statut_usage invalide {c.get('statut_usage')!r}")
            continue
        r = c.get("recommandation")
        if not isinstance(r, dict) or r.get("verdict") not in VERDICTS or not str(r.get("pourquoi", "")).strip():
            erreurs.append(f"{k}: recommandation {{verdict, pourquoi}} invalide")
            continue
        deja = e.get("commentee")
        e.update({kk: c[kk] for kk in c})
        e["commentee"] = True
        e["maj_le"] = jour
        e["historique"] = e.get("historique", []) + [{"date": jour, "changement": "commentaire révisé" if deja else "commentée"}]
    return erreurs

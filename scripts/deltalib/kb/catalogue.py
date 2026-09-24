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
from ..contexte import empreintes as empreintes_sections, est_perime, projets as projets_contexte
from ..modeles import FormatInattendu, empreinte_contexte
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
    ctx = empreinte_contexte(racine)  # D60 : empreinte du fichier entier (historique)
    courantes = empreintes_sections(racine)  # D64 : empreintes par section, base de la péremption
    connus = projets_connus(racine, perimetre, entrees)
    for cat in CATEGORIES:
        liste = sorted((e for e in entrees.values() if e["categorie"] == cat), key=lambda e: e["id"])
        for e in liste:
            e.setdefault("contexte_empreinte", None)
            e.setdefault("contexte_sections", None)
        doc = {"perimetre": perimetre, "categorie": cat, "maj_le": max((e["maj_le"] for e in liste), default=horodatage[:10]),
               "contexte_empreinte": ctx, "contexte_sections": courantes, "projets_connus": connus,
               "total": len(liste), "commentees": sum(1 for e in liste if e.get("commentee")), "entrees": liste}
        tmp = d / f"{cat}.json.tmp"
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(d / f"{cat}.json")


def projets_connus(racine: Path, perimetre: str, entrees: dict[str, dict]) -> list[str]:
    """D64 : sections de projet (`###` sous « ## 2. Projets ») déjà prises en compte par la base.

    Au premier passage, ce sont les projets présents. Un nouveau projet y entre quand sa repasse des « ignorer »
    (fonctionnalités et commandes) est terminée."""
    precedent = None
    f = dossier(racine, perimetre) / "commandes.json"
    if f.exists():
        precedent = json.loads(f.read_text(encoding="utf-8")).get("projets_connus")
    actuels = projets_contexte(racine)
    if precedent is None:
        return sorted(actuels)
    connus = set(precedent)
    for k in actuels:
        if k not in connus and not repasse_projet(entrees, k):
            connus.add(k)
    return sorted(connus)


def repasse_projet(entrees: dict[str, dict], projet: str) -> list[str]:
    """D64 : entrées « ignorer » des fonctionnalités et commandes pas encore relues à la lumière d'un nouveau projet."""
    return sorted(k for k, e in entrees.items() if e.get("commentee") and not e.get("retiree")
                  and e["categorie"] in ("fonctionnalites", "commandes")
                  and (e.get("recommandation") or {}).get("verdict") == "ignorer"
                  and projet not in (e.get("contexte_sections") or {}))


def nouveaux_projets(racine: Path, perimetre: str) -> list[str]:
    f = dossier(racine, perimetre) / "commandes.json"
    connus = set(json.loads(f.read_text(encoding="utf-8")).get("projets_connus") or []) if f.exists() else set()
    return [k for k in projets_contexte(racine) if connus and k not in connus]


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
        "commentee": False, "contexte_empreinte": None, "contexte_sections": None, "retiree": False, "origine": x.origine, "groupe": x.groupe,
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


PERIMEES_MAX = 30  # D60, D64 : réévaluations prioritaires par lancement, en plus des lots
# Lot `perimees` suspendu jusqu'à D64-bis (au plus tard le 01/10) : passer à False pour le réactiver.
PERIMEES_SUSPENDU = True


def perimees(entrees: dict[str, dict], courantes: dict[str, str] | None, maximum: int = PERIMEES_MAX) -> list[str]:
    """D64 : entrées `utiliser` puis `tester` à revoir, 30 au plus.

    D'abord celles dont une section citée a changé ou disparu, puis celles commentées avant D64
    (`contexte_sections: null`), qui seront revues en citant leurs sections. Une entrée qui ne cite aucune
    section (liste vide) n'est jamais périmée."""
    if not courantes:
        return []
    rang = {"utiliser": 0, "tester": 1}
    perimees_, anterieures = [], []
    for k, e in entrees.items():
        verdict = (e.get("recommandation") or {}).get("verdict")
        if not e.get("commentee") or e.get("retiree") or verdict not in rang:
            continue
        etat = est_perime(e.get("contexte_sections"), courantes)
        if etat is True:
            perimees_.append(k)
        elif etat is None:
            anterieures.append(k)
    cle = lambda k: (rang[entrees[k]["recommandation"]["verdict"]], k)
    return (sorted(perimees_, key=cle) + sorted(anterieures, key=cle))[:maximum]


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


def appliquer_commentaires(entrees: dict[str, dict], commentaires: dict, jour: str | None = None,
                           contexte: str | None = None, resoudre=None) -> list[str]:
    """Applique {id: {description, statut_usage, recommandation, exemple?, disponibilite?}} ; jamais `usage`.
    `contexte` : empreinte de CONTEXTE.md au moment du commentaire, inscrite sur chaque entrée (D60).
    `resoudre` (D64) : fonction liste de clés -> {clé: sha1} ; quand elle est fournie, chaque commentaire doit citer
    `contexte_sections` (liste, vide si le jugement ne dépend pas de CONTEXTE), stocké avec les empreintes."""
    jour = jour or date.today().isoformat()
    erreurs = []
    for k, c in commentaires.items():
        e = entrees.get(k)
        if e is None:
            erreurs.append(f"{k}: identifiant inconnu")
            continue
        interdits = set(c) - {"description", "statut_usage", "recommandation", "exemple", "disponibilite", "contexte_sections"}
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
        sections_citees = None
        if resoudre is not None or "contexte_sections" in c:
            cs = c.get("contexte_sections")
            if not isinstance(cs, list) or not all(isinstance(x, str) for x in cs):
                erreurs.append(f"{k}: `contexte_sections` doit être une liste de clés de CONTEXTE.md (vide si sans lien) (D64)")
                continue
            if resoudre is not None:
                try:
                    sections_citees = resoudre(cs)
                except ValueError as err:
                    erreurs.append(f"{k}: {err}")
                    continue
        deja = e.get("commentee")
        e.update({kk: c[kk] for kk in c if kk != "contexte_sections"})
        if sections_citees is not None:
            e["contexte_sections"] = sections_citees
        e["commentee"] = True
        e["contexte_empreinte"] = contexte
        e["maj_le"] = jour
        e["historique"] = e.get("historique", []) + [{"date": jour, "changement": "commentaire révisé" if deja else "commentée"}]
    return erreurs

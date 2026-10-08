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
import re
import unicodedata
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import yaml

from ..dates import maintenant_iso
from ..contexte import deprecies as deprecies_contexte, empreintes as empreintes_sections, format_valide, sections_perimees
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
    courantes = empreintes_sections(racine)  # D64-bis : empreintes par ctx-id, base de la péremption
    for cat in CATEGORIES:
        liste = sorted((e for e in entrees.values() if e["categorie"] == cat), key=lambda e: e["id"])
        for e in liste:
            e.setdefault("contexte_empreinte", None)
            # D64-bis : un format antérieur (liste ou {clé: sha1} de ae895e6) n'a pas de correspondance : null
            if e.get("contexte_sections") is not None and not format_valide(e["contexte_sections"]):
                e["contexte_sections"] = None
            e.setdefault("contexte_sections", None)
        doc = {"perimetre": perimetre, "categorie": cat, "maj_le": max((e["maj_le"] for e in liste), default=horodatage[:10]),
               "contexte_empreinte": ctx, "contexte_sections": courantes, "contexte_deprecies": sorted(deprecies_contexte(racine)),
               "total": len(liste), "commentees": sum(1 for e in liste if e.get("commentee")), "entrees": liste}
        tmp = d / f"{cat}.json.tmp"
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(d / f"{cat}.json")
    ecrire_recent(racine)  # D99 : vue légère des ajouts récents, des deux périmètres réunis


MENTION_ADOPTION = "adoption déclarée, PROGRESSION.md"


def adoptions(racine: Path) -> list[str]:
    """D67 : identifiants de la section « Adoptions » de PROGRESSION.md (première colonne du tableau).
    Rien d'autre dans ce fichier n'agit sur la base."""
    f = racine / "PROGRESSION.md"
    if not f.exists():
        return []
    ids, dedans = [], False
    for ligne in f.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("## "):
            dedans = ligne.strip() == "## Adoptions"
            continue
        if dedans and ligne.startswith("|"):
            cellule = ligne.strip("|").split("|")[0].strip().strip("`").strip()
            if cellule and not set(cellule) <= set("-: ") and cellule != "Id de l'entrée":
                ids.append(cellule)
    return ids


def appliquer_adoptions(entrees: dict[str, dict], ids: list[str], jour: str | None = None) -> list[str]:
    """Passe `statut_usage` à `utilise` pour les entrées adoptées (D67), avec une ligne d'historique ; idempotent."""
    jour = jour or date.today().isoformat()
    changees = []
    for k in ids:
        e = entrees.get(k)
        if e is None or e.get("statut_usage") == "utilise":
            continue
        e["statut_usage"] = "utilise"
        e["maj_le"] = jour
        e["historique"] = e.get("historique", []) + [{"date": jour, "changement": f"statut_usage : utilise ({MENTION_ADOPTION})"}]
        changees.append(k)
    return changees


def extraire(racine: Path, docs: list[DocSource], surcharge: dict | None = None, avertissements: list | None = None
             ) -> tuple[list[EntreeExtraite], set[str], list[dict]]:
    """Rend (entrées, docs extraites avec succès, échecs). Une doc sans copie locale est ignorée.
    Doc à pages : une page en échec est signalée à part et ne bloque pas les autres ; la doc n'est alors pas
    « extraite avec succès », donc rien n'est retiré. Les replis HTML vont dans `avertissements`."""
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
        for chemin, err in getattr(extraites, "echecs_pages", []):
            echecs.append({"doc": d.id, "page": chemin, "erreur": f"FormatInattendu: {err}"})
        if avertissements is not None:
            avertissements.extend({"doc": d.id, "page": c, "avertissement": "page servie en HTML, lue en repli"}
                                  for c in getattr(extraites, "replis_html", []))
        if getattr(extraites, "echecs_pages", None):
            continue  # une page en échec : ses entrées restent inchangées, aucune entrée n'est retirée
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


LIGNE_AJOUT = "ajoutée à l'inventaire"


def date_ajout(entree: dict) -> str | None:
    """Date d'ajout d'une entrée : ligne « ajoutée à l'inventaire » de l'historique, à défaut la plus ancienne
    date de l'historique, à défaut None (jamais devinée). Miroir de `dateAjout` dans docs/assets/app.js."""
    historique = entree.get("historique") if isinstance(entree, dict) else None
    lignes = [l for l in historique if isinstance(l, dict) and isinstance(l.get("date"), str)
              and re.fullmatch(r"\d{4}-\d{2}-\d{2}", l["date"])] if isinstance(historique, list) else []
    ajout = sorted(l["date"] for l in lignes
                   if isinstance(l.get("changement"), str) and unicodedata.normalize("NFC", l["changement"]).strip() == LIGNE_AJOUT)
    return ajout[0] if ajout else (min(l["date"] for l in lignes) if lignes else None)


RECENT_JOURS = 30  # D99 : fenêtre du fichier léger des ajouts récents
RECENT_MAX = 150  # D99 : plafond d'entrées (≈ 35 Ko) ; au-delà, les plus anciennes sont coupées et `tronque` vaut true


def chemin_recent(racine: Path) -> Path:
    return racine / "docs" / "data" / "kb" / "recent.json"


def construire_recent(entrees: list[dict], jour: str | None = None) -> dict:
    """D99 : entrées non retirées ajoutées depuis RECENT_JOURS jours (aujourd'hui compris), date d'ajout décroissante,
    nom puis id à égalité, au plus RECENT_MAX. `total` = entrées de la fenêtre avant coupe ; `plus_ancienne` = date
    d'ajout la plus ancienne des entrées gardées (null si aucune)."""
    jour = jour or date.today().isoformat()
    seuil = (date.fromisoformat(jour) - timedelta(days=RECENT_JOURS)).isoformat()
    fenetre = []
    for e in entrees:
        d = date_ajout(e)
        if e.get("retiree") or not d or not seuil <= d <= jour:
            continue
        reco = e.get("recommandation") if e.get("commentee") else None
        verdict = reco.get("verdict") if isinstance(reco, dict) else None
        fenetre.append({"id": e["id"], "produit": e.get("produit"), "categorie": e.get("categorie"), "nom": e.get("nom"),
                        "usage": e.get("usage"), "usage_nature": e.get("usage_nature"), "exemple": e.get("exemple"),
                        "verdict": verdict, "date_ajout": d})
    fenetre.sort(key=lambda x: (str(x["nom"]), x["id"]))
    fenetre.sort(key=lambda x: x["date_ajout"], reverse=True)  # tri stable : nom puis id gardés à égalité de date
    gardees = fenetre[:RECENT_MAX]
    return {"genere_le": jour, "fenetre_jours": RECENT_JOURS, "total": len(fenetre), "tronque": len(fenetre) > len(gardees),
            "plus_ancienne": gardees[-1]["date_ajout"] if gardees else None, "entrees": gardees}


def ecrire_recent(racine: Path, jour: str | None = None) -> dict:
    """Écrit docs/data/kb/recent.json depuis la base des deux périmètres telle qu'elle est sur disque."""
    entrees = [e for per in PRODUITS_PAR_PERIMETRE for e in charger(racine, per).values()]
    doc = construire_recent(entrees, jour)
    chemin = chemin_recent(racine)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    # une entrée par ligne : un diff git d'une mise à jour ne montre que les entrées changées
    entete = json.dumps({k: v for k, v in doc.items() if k != "entrees"}, ensure_ascii=False, separators=(",", ":"))[:-1]
    lignes = ",\n".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in doc["entrees"])
    tmp.write_text(f'{entete},"entrees":[\n{lignes}\n]}}\n' if lignes else f'{entete},"entrees":[]}}\n', encoding="utf-8")
    tmp.replace(chemin)
    return doc


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


def sujet_d71(entrees: dict[str, dict], modif: dict) -> list[str]:
    """D71, étape 2a : ids des entrées ajoutées ou modifiées (usage, description d'origine) dont le nom, l'usage ou la
    description d'origine touche au compte et aux quotas (mots-clés de `deltalib.sujet_d71`). Aucun jugement."""
    from ..sujet_d71 import correspond_base
    ids = []
    for cle in ("ajoutees", "usage_modifie", "description_source_modifiee"):
        for i in modif.get(cle, []):
            e = entrees.get(i) or {}
            if i not in ids and correspond_base(e.get("nom"), e.get("usage"), e.get("description_source")):
                ids.append(i)
    return sorted(ids)


SEUIL_AJOUTS_PAR_LIGNE = 30  # étape 2c : au-delà, fetch.py n'imprime qu'un décompte par catégorie


def ajouts_par_categorie(ids: list[str], entrees: dict[str, dict]) -> dict[str, int]:
    """Nombre d'ajouts par catégorie de la base (champ `categorie` de l'entrée), du plus fourni au moins fourni."""
    n: dict[str, int] = {}
    for i in ids:
        cat = (entrees.get(i) or {}).get("categorie") or "autre"
        n[cat] = n.get(cat, 0) + 1
    return dict(sorted(n.items(), key=lambda kv: (-kv[1], kv[0])))


def ajouts_a_citer(modif: dict, deja_cites: list[str], base_existante: bool) -> list[str]:
    """Étape 2c : ids des entrées ajoutées à la base (réglages, commandes, raccourcis, etc.) à citer chacun en une ligne
    dans la veille du jour, sans jugement. Hors `sujet_d71` (déjà cités avec l'impact de D71) ; vide quand la base n'existait
    pas encore : la création initiale de l'inventaire n'est pas une nouveauté."""
    if not base_existante:
        return []
    return sorted(i for i in modif.get("ajoutees", []) if i not in deja_cites)


def mettre_a_jour(racine: Path, perimetre: str, docs: list[DocSource], ecrire_fichiers: bool = True,
                  surcharge: dict | None = None) -> dict:
    docs = [d for d in docs if d.perimetre == perimetre and d.active]
    avertissements: list[dict] = []
    extraites, ok, echecs = extraire(racine, docs, surcharge, avertissements)
    existantes = charger(racine, perimetre)
    entrees, modif = fusionner(existantes, extraites, ok)
    if ecrire_fichiers:
        ecrire(racine, perimetre, entrees)
    d71 = sujet_d71(entrees, modif)
    ajouts = ajouts_a_citer(modif, d71, bool(existantes))
    return {"perimetre": perimetre, "genere_le": maintenant_iso(), "docs_extraites": sorted(ok), "echecs": echecs,
            "avertissements": avertissements,
            "sujet_d71": d71, "ajouts_a_citer": ajouts,
            "ajouts_par_categorie": ajouts_par_categorie(ajouts, entrees),
            "total": len(entrees), "a_commenter": sorted(k for k, e in entrees.items() if not e.get("commentee") and not e.get("retiree")),
            **modif}


# ----------------------------------------------------------------------------------------------- lots et commentaires

ORDRE_LOTS = ("commandes", "fonctionnalites", "skills", "plugins", "mcp", "raccourcis", "parametres")  # D51
QUARTS = ("parametres",)  # D50 : paramètres coupés en quarts
GROUPES = {"openai": {("skills", "plugins", "mcp"): "skills+plugins+mcp"}}  # D50 : lots regroupés


PERIMEES_MAX = 10  # D64-bis (amendée le 29/09/2026) : réévaluations prioritaires par lancement, en plus des lots
# Lot `perimees` : passer à True pour le suspendre (il l'a été du 24/09 jusqu'à la livraison de D64-bis).
PERIMEES_SUSPENDU = False


def lire_demandes(racine: Path) -> list[dict]:
    """D78 : demandes validées du YAML, dans l'ordre, avec `ids` sans doublon ; [] si absent ou vide."""
    chemin = racine / "kb-rejugements.yaml"
    if not chemin.exists():
        return []
    try:
        demandes = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise ValueError(f"kb-rejugements.yaml : YAML invalide : {err}") from err
    if demandes is None:
        return []
    if not isinstance(demandes, list):
        raise ValueError("kb-rejugements.yaml : liste de demandes {date, motif, ids} attendue")
    res = []
    for n, demande in enumerate(demandes, 1):
        ou = f"kb-rejugements.yaml : demande {n}"
        if not isinstance(demande, dict):
            raise ValueError(f"{ou} : {{date, motif, ids}} attendu")
        jour = str(demande.get("date", ""))  # safe_load accepte aussi les dates YAML non citées
        try:
            if date.fromisoformat(jour).isoformat() != jour:
                raise ValueError
        except ValueError as err:
            raise ValueError(f"{ou} : date AAAA-MM-JJ attendue") from err
        motif, ids = demande.get("motif"), demande.get("ids")
        if not isinstance(motif, str) or not motif.strip() or "\n" in motif or "\r" in motif:
            raise ValueError(f"{ou} : motif non vide sur une ligne attendu")
        if not isinstance(ids, list) or not all(isinstance(k, str) and k.strip() for k in ids):
            raise ValueError(f"{ou} : liste d'ids attendue")
        plafond = demande.get("plafond", PERIMEES_MAX)
        if type(plafond) is not int or not 10 <= plafond <= 50:
            raise ValueError(f"{ou} : plafond entier de 10 à 50 attendu")
        res.append({"date": jour, "motif": motif.strip(), "plafond": plafond, "ids": list(dict.fromkeys(ids))})
    return res


def _indexer_demandes(demandes: list[dict], connus: set[str]) -> tuple[dict[str, list[dict]], set[str]]:
    res, inconnus = {}, set()
    for demande in demandes:
        for k in demande["ids"]:
            if k not in connus:
                inconnus.add(k)
            else:
                res.setdefault(k, []).append({"date": demande["date"], "motif": demande["motif"], "plafond": demande["plafond"]})
    return res, inconnus


def _ids_connus(racine: Path) -> set[str]:
    return {k for per in PRODUITS_PAR_PERIMETRE for k in charger(racine, per)}


def charger_rejugements(racine: Path) -> dict[str, list[dict]]:
    """D78 : demandes par id, tous périmètres confondus ; un id inconnu est seulement signalé.
    Toutes les demandes sont conservées pour éteindre leurs plafonds indépendamment."""
    demandes = lire_demandes(racine)
    if not demandes:
        return {}
    res, inconnus = _indexer_demandes(demandes, _ids_connus(racine))
    if inconnus:
        print(f"! kb-rejugements.yaml : id inconnus dans la base : {', '.join(sorted(inconnus))}", file=sys.stderr)
    return res


def _perimetre_du_prefixe(ident: str) -> str | None:
    return next((per for per, prods in PRODUITS_PAR_PERIMETRE.items() if any(ident.startswith(f"{p}-") for p in prods)), None)


def suivi_rejugements(racine: Path, perimetres: list[str], courantes: dict[str, str],
                      deprecies_: set[str] = frozenset()) -> dict:
    """Vue de suivi D78, lecture seule : par périmètre, le plafond effectif, les fiches dues (toutes catégories)
    et une estimation du nombre de passages ; par demande, ids listés, dus, recommentés et inconnus.
    Un id inconnu de toutes les bases est rattaché au périmètre de son préfixe produit, sinon à tous."""
    demandes = lire_demandes(racine)
    bases = {per: charger(racine, per) for per in PRODUITS_PAR_PERIMETRE}
    tous = {k for b in bases.values() for k in b}
    rejugements, _ = _indexer_demandes(demandes, tous)
    sortie = {}
    for per in perimetres:
        entrees = bases[per]
        plafond = plafond_perimees(entrees, rejugements)
        dus_total = len(perimees_detail(entrees, courantes, deprecies_, maximum=None, rejugements=rejugements))
        lignes = []
        for d in demandes:
            listes = [k for k in d["ids"] if k in entrees]
            dus = [k for k in listes if motif_rejugement(entrees[k], {k: [d]}) is not None]
            recommentes = [k for k in listes if k not in dus and entrees[k].get("commentee") and not entrees[k].get("retiree")]
            inconnus = [k for k in d["ids"] if k not in tous and _perimetre_du_prefixe(k) in (None, per)]
            lignes.append({"date": d["date"], "motif": d["motif"], "plafond": d["plafond"], "active": bool(dus),
                           "ids_listes": listes, "ids_dus": dus, "ids_recommentes": recommentes, "ids_inconnus": inconnus})
        sortie[per] = {"plafond_effectif": plafond, "dus_total_perimees": dus_total,
                       "passages_restants_estimes": -(-dus_total // plafond), "estimation": True, "demandes": lignes}
    return sortie


def motif_rejugement(e: dict, rejugements: dict | None) -> str | None:
    """D78 : seule la date du dernier commentaire éteint la demande, jamais `maj_le` (adoption, source…)."""
    # À date égale, la dernière demande du YAML prévaut pour le motif.
    demande = max(reversed((rejugements or {}).get(e.get("id"), [])), key=lambda d: d["date"], default=None)
    if not demande or not e.get("commentee") or e.get("retiree"):
        return None
    dernier = max((h["date"] for h in e.get("historique", [])
                   if h.get("changement") in ("commentée", "commentaire révisé", "réévaluée")), default="")
    if dernier < demande["date"]:
        return f"rejugement demandé ({demande['motif']})"
    return None


def plafond_perimees(entrees: dict[str, dict], rejugements: dict | None = None) -> int:
    """Plafond D78 des demandes encore dues dans le périmètre, même si la section est aussi périmée."""
    plafond = PERIMEES_MAX
    for k, e in entrees.items():
        for demande in (rejugements or {}).get(k, []):
            if motif_rejugement(e, {k: [demande]}) is not None:
                plafond = max(plafond, demande.get("plafond", PERIMEES_MAX))
    return plafond


def adoptee_non_revue(e: dict) -> bool:
    """D67 : adoption déclarée (statut_usage `utilise`) sur un verdict `ignorer`, sans commentaire postérieur."""
    if e.get("statut_usage") != "utilise" or (e.get("recommandation") or {}).get("verdict") != "ignorer":
        return False
    for h in reversed(e.get("historique") or []):
        if MENTION_ADOPTION in str(h.get("changement", "")):
            return True
        if h.get("changement") in ("commentée", "commentaire révisé", "réévaluée"):
            return False
    return False


def classer(e: dict, courantes: dict[str, str], deprecies_: set[str] = frozenset(),
            rejugements: dict | None = None) -> tuple[str, str] | None:
    """(catégorie a|adoption|rejugement, motif du journal) si l'entrée est à réévaluer, sinon None.
    a) section citée modifiée, disparue ou dépréciée ; adoption) `ignorer` adopté par Sylvain (D67) ; demande D78.
    Une entrée antérieure à D64 (null) ou sans section citée ({}) n'est jamais reprise pour un changement de CONTEXTE."""
    if not e.get("commentee") or e.get("retiree"):
        return None
    cs = e.get("contexte_sections")
    touchees = sections_perimees(cs, courantes, deprecies_) if cs else []
    if touchees:
        return "a", f"section:{touchees[0]}"
    if adoptee_non_revue(e):
        return "adoption", "adoption"
    motif = motif_rejugement(e, rejugements)
    if motif:
        return "rejugement", motif
    return None


def perimees_detail(entrees: dict[str, dict], courantes: dict[str, str], deprecies_: set[str] = frozenset(),
                    maximum: int | None | Literal["auto"] = "auto", *, rejugements: dict | None = None) -> list[dict]:
    """D64-bis et D78 : lot `perimees`, ordonné `utiliser`, `tester`, adoption, puis `ignorer`
    (une adoption déclarée par Sylvain est le signal le plus fiable) ; plafond effectif par défaut,
    `maximum=None` pour compter toutes les entrées dues."""
    if maximum == "auto":
        maximum = plafond_perimees(entrees, rejugements)
    rang = {"utiliser": 0, "tester": 1, "ignorer": 2}
    res = []
    for k, e in entrees.items():
        if courantes:
            c = classer(e, courantes, deprecies_, rejugements)
        else:  # sans CONTEXTE, D64-bis reste inactif ; une demande explicite D78 reste exploitable
            motif = motif_rejugement(e, rejugements)
            c = ("rejugement", motif) if motif else None
        if c:
            res.append({"id": k, "categorie": c[0], "motif": c[1]})
    def cle(x):
        if x["categorie"] == "adoption":
            return (2, 0, x["id"])
        v = rang.get((entrees[x["id"]].get("recommandation") or {}).get("verdict"), 3)
        return (v if v < 2 else v + 1, 0, x["id"])
    res.sort(key=cle)
    return res if maximum is None else res[:maximum]


def perimees(entrees: dict[str, dict], courantes: dict[str, str] | None, deprecies_: set[str] = frozenset(),
             maximum: int | None | Literal["auto"] = "auto", *, rejugements: dict | None = None) -> list[str]:
    return [x["id"] for x in perimees_detail(entrees, courantes or {}, deprecies_, maximum, rejugements=rejugements)]


EXEMPLES_MAX = 50  # D91 : exemples à produire par lancement, en plus de `perimees` et des lots ordinaires
EXEMPLES_CATEGORIES = ("commandes", "fonctionnalites", "skills", "mcp")  # ordre de traitement du lot `exemples`
ORIGINES_EXEMPLE = ("source", "compose")
CHAMPS_EXEMPLE = {"exemple", "exemple_origine"}


def sans_exemple(e: dict) -> bool:
    """D91 : entrée commentée, de syntaxe, de l'une des catégories du lot `exemples`, sans exemple ; une entrée dont
    `usage_nature` est `etapes` n'a jamais d'exemple et n'est donc jamais due."""
    return (bool(e.get("commentee")) and not e.get("retiree") and e.get("categorie") in EXEMPLES_CATEGORIES
            and e.get("usage_nature") == "syntaxe" and not str(e.get("exemple") or "").strip())


def exemples_detail(entrees: dict[str, dict], maximum: int | None | Literal["auto"] = "auto") -> list[str]:
    """D91 : lot `exemples`. Catégories dans l'ordre de EXEMPLES_CATEGORIES, puis dans chacune les verdicts `utiliser`,
    `tester`, `ignorer` (une entrée sans verdict en dernier), puis l'identifiant. Plafond EXEMPLES_MAX par défaut,
    `maximum=None` pour compter toutes les entrées dues."""
    if maximum == "auto":
        maximum = EXEMPLES_MAX
    rang = {"utiliser": 0, "tester": 1, "ignorer": 2}
    dues = [k for k, e in entrees.items() if sans_exemple(e)]
    dues.sort(key=lambda k: (EXEMPLES_CATEGORIES.index(entrees[k]["categorie"]),
                             rang.get((entrees[k].get("recommandation") or {}).get("verdict"), 3), k))
    return dues if maximum is None else dues[:maximum]


def options_hors_source(exemple: str, e: dict) -> list[str]:
    """D91 : options longues (`--option`) d'un exemple composé qui ne figurent ni dans `usage` ni dans `description_source`."""
    source = f"{e.get('usage') or ''}\n{e.get('description_source') or ''}"
    return sorted({o for o in re.findall(r"(?<![\w-])--[A-Za-z][\w-]*", exemple) if o not in source})


def verifier_exemple(e: dict, exemple, origine) -> str | None:
    """D91 : message d'erreur si (exemple, exemple_origine) viole la règle de provenance pour l'entrée `e`, sinon None."""
    if exemple is None or (isinstance(exemple, str) and not exemple.strip()):
        return "`exemple_origine` sans `exemple`" if origine is not None else None
    if not isinstance(exemple, str):
        return "`exemple` doit être un texte ou null"
    if e.get("usage_nature") != "syntaxe":
        return "pas d'exemple pour une entrée dont `usage_nature` est `etapes` (exemple: null)"
    if origine not in ORIGINES_EXEMPLE:
        return f"`exemple_origine` attendu avec un exemple : {' ou '.join(ORIGINES_EXEMPLE)}"
    if origine == "compose":
        hors = options_hors_source(exemple, e)
        if hors:
            return f"exemple composé : option(s) absente(s) de `usage` et de la source : {', '.join(hors)}"
    return None


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
                           contexte: str | None = None, resoudre=None, journal: list | None = None,
                           motif_de=None) -> list[str]:
    """Applique {id: {description, statut_usage, recommandation, exemple?, exemple_origine?, disponibilite?}} ; jamais `usage`.
    D91 : `exemple` non nul exige `exemple_origine` (`source` ou `compose`) ; {exemple, exemple_origine} seuls, sur une entrée
    déjà commentée, ajoutent l'exemple sans refaire le commentaire (historique « exemple ajouté »).
    `contexte` : empreinte de CONTEXTE.md au moment du commentaire, inscrite sur chaque entrée (D60).
    `resoudre` (D64-bis) : fonction {ctx-id: pourquoi} -> {ctx-id: {sha1, pourquoi}} ; quand elle est fournie, chaque
    commentaire doit citer `contexte_sections` ({} si le jugement ne dépend d'aucune section).
    `journal` (B3) : reçoit une ligne {date, id, verdict_avant, verdict_apres, motif} par réévaluation ; `motif_de(entrée)`
    donne le motif (section:<ctx-id>, adoption, rejugement demandé (<motif>))."""
    jour = jour or date.today().isoformat()
    erreurs = []
    for k, c in commentaires.items():
        e = entrees.get(k)
        if e is None:
            erreurs.append(f"{k}: identifiant inconnu")
            continue
        interdits = set(c) - {"description", "statut_usage", "recommandation", "exemple", "exemple_origine", "disponibilite",
                              "contexte_sections"}
        if interdits:
            erreurs.append(f"{k}: champs non modifiables par le commentaire : {sorted(interdits)}")
            continue
        if c and set(c) <= CHAMPS_EXEMPLE:  # D91 : ajout d'exemple seul, sans refaire le jugement
            if not e.get("commentee") or e.get("retiree"):
                erreurs.append(f"{k}: ajout d'exemple réservé aux entrées commentées")
            elif not str(c.get("exemple") or "").strip():
                erreurs.append(f"{k}: `exemple` absent")
            elif (message := verifier_exemple(e, c.get("exemple"), c.get("exemple_origine"))):
                erreurs.append(f"{k}: {message}")
            else:
                e.update({"exemple": c["exemple"], "exemple_origine": c["exemple_origine"], "maj_le": jour})
                e["historique"] = e.get("historique", []) + [{"date": jour, "changement": "exemple ajouté"}]
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
        if "exemple" in c or "exemple_origine" in c:
            message = verifier_exemple(e, c.get("exemple"), c.get("exemple_origine"))
            if message:
                erreurs.append(f"{k}: {message}")
                continue
        sections_citees = None
        if resoudre is not None or "contexte_sections" in c:
            cs = c.get("contexte_sections")
            if not isinstance(cs, dict) or not all(isinstance(x, str) for x in cs):
                erreurs.append(f"{k}: `contexte_sections` doit être {{ctx-id: pourquoi}} ({{}} si sans lien) (D64-bis)")
                continue
            if resoudre is not None:
                try:
                    sections_citees = resoudre(cs)
                except ValueError as err:
                    erreurs.append(f"{k}: {err}")
                    continue
        deja = e.get("commentee")
        verdict_avant = (e.get("recommandation") or {}).get("verdict") if deja else None
        motif = motif_de(e) if (deja and motif_de) else None
        e.update({kk: c[kk] for kk in c if kk != "contexte_sections"})
        if "exemple" in c and not str(c["exemple"] or "").strip():
            e["exemple"] = None
            e.pop("exemple_origine", None)
        if motif and journal is not None:
            journal.append({"date": jour, "id": k, "verdict_avant": verdict_avant, "verdict_apres": r["verdict"],
                            "motif": motif})
        if sections_citees is not None:
            e["contexte_sections"] = sections_citees
        e["commentee"] = True
        e["contexte_empreinte"] = contexte
        e["maj_le"] = jour
        e["historique"] = e.get("historique", []) + [{"date": jour, "changement": "commentaire révisé" if deja else "commentée"}]
    return erreurs

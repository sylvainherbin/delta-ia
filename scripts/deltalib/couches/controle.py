"""Contrôle de fidélité d'un import (critère de fin du lot L1) : relit le dépôt et compare aux deux magasins.

- mêmes identités : chaque fiche de la base, méthode, couple et modèle, élément de veille et outil de versions du dépôt
  a sa fiche commune (sauf refus déclaré), et le commun n'en invente aucune ;
- avis et essais historiques retrouvés dans le magasin privé : `statut_usage` et `recommandation` de chaque fiche, chaque
  ligne de réévaluation, d'essai (`kb-essais.yaml`, `essai` de l'onglet À tester) et de rejugement ;
- noms : `kb/noms.json` du commun identique à celui du dépôt quand aucune fiche n'a été retenue ;
- empreintes des entrées identiques à celles du relevé d'import.
Rend des messages sans valeur personnelle (identités et compteurs seulement).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .projection import ESSAIS, REJUGEMENTS, lire_entrees, slug_outil
from .racines import Racines


def _charger(chemin: Path):
    return json.loads(chemin.read_text(encoding="utf-8"))


def fidelite(depot: Path, racines: Racines) -> tuple[list[str], dict]:
    erreurs: list[str] = []
    actif = _charger(racines.commun_actif)
    dossier = racines.commun / actif["generation"]
    manifest = _charger(dossier / "manifest.json")
    communs = {f["chemin"]: _charger(dossier / f["chemin"]) for f in manifest["fichiers"]}
    overlay = _charger(racines.personnel / "overlay.json")["objets"]
    attente = _charger(racines.personnel / "en_attente.json")
    releve = _charger(racines.personnel / "import.json")
    retenus = {r["objet"] for r in attente["refus"]}
    data = depot / "docs" / "data"

    entrees = {e.rel: e.sha256 for e in lire_entrees(depot)}
    if entrees != {x["chemin"]: x["sha256"] for x in releve["entrees"]}:
        erreurs.append("entrées du dépôt différentes de celles du relevé d'import (import à relancer)")

    identites_communes = {f["identite"] for d in communs.values() for f in d.get("entrees", [])}
    identites_communes |= {f["identite"] for d in communs.values() for f in (d.get("modeles") or {}).values()}
    attendues: set[str] = set()
    avis = essais_a_tester = 0
    for chemin in sorted(data.glob("kb/*/*.json")):
        perimetre = chemin.parent.name
        for e in _charger(chemin)["entrees"]:
            ident = f"kb:{perimetre}:{e['id']}"
            attendues.add(ident)
            o = overlay.get(ident)
            for cle in ("statut_usage", "recommandation"):
                if cle in e and (o is None or o[cle] != e[cle]):
                    erreurs.append(f"{ident}: `{cle}` absent ou différent dans le magasin privé")
            avis += 1 if ("statut_usage" in e or "recommandation" in e) else 0
    for rel, espace in (("kb/methodes.json", "kb:delta:methodes:"), ("kb/modeles.json", "kb:delta:modeles:")):
        if (data / rel).is_file():
            doc = _charger(data / rel)
            for e in doc.get("entrees", []):
                attendues.add(espace + e["id"])
                o = overlay.get(espace + e["id"])
                if "recommandation" in e and (o is None or o["recommandation"] != e["recommandation"]):
                    erreurs.append(f"{espace}{e['id']}: `recommandation` absente ou différente dans le magasin privé")
            attendues |= {espace + k for k in doc.get("modeles", {})}
    for perimetre in ("claude", "openai", "actu"):
        for chemin in sorted(data.glob(f"{perimetre}/????-??-??.json")):
            attendues |= {f"veille:{perimetre}:{e['id']}" for e in _charger(chemin)["elements"]}
    if (data / "versions.json").is_file():
        attendues |= {f"version:{slug_outil(v['outil'])}" for v in _charger(data / "versions.json")}
    manquantes = attendues - identites_communes - retenus
    inventees = identites_communes - attendues
    if manquantes:
        erreurs.append(f"{len(manquantes)} identité(s) du dépôt absente(s) du commun, ex. {sorted(manquantes)[:3]}")
    if inventees:
        erreurs.append(f"{len(inventees)} identité(s) du commun absente(s) du dépôt, ex. {sorted(inventees)[:3]}")

    reevaluations = 0
    for chemin in sorted(data.glob("kb/*/reevaluations.jsonl")):
        perimetre = chemin.parent.name
        par_objet: dict[str, list] = {}
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            if ligne.strip():
                x = json.loads(ligne)
                par_objet.setdefault(f"kb:{perimetre}:{x['id']}", []).append(x)
        for ident, lignes in par_objet.items():
            reevaluations += len(lignes)
            if (overlay.get(ident) or {}).get("reevaluations") != lignes:
                erreurs.append(f"{ident}: réévaluations absentes ou différentes dans le magasin privé")
    essais = rejugements = 0
    for rel, champ, cle in ((ESSAIS, "essais", "id"), (REJUGEMENTS, "rejugements", "ids")):
        if not (depot / rel).is_file():
            continue
        for ligne in yaml.safe_load((depot / rel).read_text(encoding="utf-8")) or []:
            ids = [ligne[cle]] if cle == "id" else ligne[cle]
            reste = {k: v for k, v in ligne.items() if k != cle}
            for i in ids:
                trouve = [o for k, o in overlay.items() if k.rsplit(":", 1)[-1] == i
                          and {**reste, "source": rel} in o[champ]]
                if not trouve:
                    erreurs.append(f"{i}: ligne de {rel} absente du magasin privé")
                if champ == "essais":
                    essais += 1
                else:
                    rejugements += 1
    if (data / "kb" / "a-tester.json").is_file():
        for e in _charger(data / "kb" / "a-tester.json")["entrees"]:
            if "essai" not in e:
                continue
            essais_a_tester += 1
            trouve = any(h["fichier"] == "docs/data/kb/a-tester.json" and h["champs"].get("essai") == e["essai"]
                         for k, o in overlay.items() if k.rsplit(":", 1)[-1] == e["id"] for h in o["historique_importe"])
            if not trouve:
                erreurs.append(f"{e['id']}: essai de l'onglet À tester absent du magasin privé")
    if (data / "kb" / "noms.json").is_file() and "kb/noms.json" in communs and not retenus:
        if communs["kb/noms.json"]["noms"] != _charger(data / "kb" / "noms.json"):
            erreurs.append("kb/noms.json du commun différent de celui du dépôt")
    comptes = {"identites_attendues": len(attendues), "identites_communes": len(identites_communes),
               "retenues": len(retenus), "avis": avis, "reevaluations": reevaluations, "essais": essais,
               "essais_a_tester": essais_a_tester, "rejugements": rejugements}
    return erreurs, comptes

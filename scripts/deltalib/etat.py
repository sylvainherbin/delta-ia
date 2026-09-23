"""État `state/<perimetre>.json` : identifiants déjà vus, empreintes. Détection des nouveautés et validation."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .dates import maintenant_iso
from .modeles import Element

VERSION_ETAT = 1


def charger_etat(chemin: Path) -> dict:
    if not chemin.exists():
        return {"version": VERSION_ETAT, "maj_le": None, "vus": {}}
    with open(chemin, encoding="utf-8") as f:
        etat = json.load(f)
    if not isinstance(etat, dict) or not isinstance(etat.get("vus"), dict):
        raise ValueError(f"{chemin}: état illisible (clé `vus` attendue)")
    return etat


def ecrire_json(chemin: Path, donnees: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    tmp.replace(chemin)


def premier_passage(etat: dict) -> bool:
    return not etat.get("vus")


def detecter(elements: list[Element], etat: dict, fenetre_depuis: date | None) -> tuple[list[Element], list[str]]:
    """Sépare les nouveautés des éléments à ignorer.

    - identifiant connu : rien, sauf si la source suit les révisions et que l'empreinte a changé,
      auquel cas l'élément revient en nouveauté avec `revision: true` (D1) ;
    - daté avant `fenetre_depuis` : ignoré, mais retenu pour que `--valider` l'inscrive dans l'état ;
    - non daté : jamais ignoré à cause de la fenêtre, c'est une nouveauté (D3) ;
    - sinon : nouveauté.
    """
    vus = etat.get("vus", {})
    nouveautes: list[Element] = []
    ignores: list[str] = []
    deja: set[str] = set()
    for e in elements:
        if e.id in deja:
            continue  # même identifiant natif rapporté par deux sources (ex. general et codex-app)
        deja.add(e.id)
        if e.id in vus:
            connue = vus[e.id].get("empreinte")
            if e.empreinte and connue and connue != e.empreinte:
                e.revision = True
                nouveautes.append(e)
            continue
        if fenetre_depuis is not None and e.date_publication is not None \
                and date.fromisoformat(e.date_publication) < fenetre_depuis:
            ignores.append(e.id)
            continue
        nouveautes.append(e)
    nouveautes.sort(key=lambda e: (e.date_publication or "9999", e.source_id, e.id), reverse=True)
    return nouveautes, sorted(ignores)


def valider(etat: dict, brut: dict) -> tuple[dict, int]:
    """Fait avancer l'état à partir du fichier des nouveautés en attente. Retourne (état, nb ajoutés ou révisés).

    Phase 2 (D5) : seuls les identifiants présents dans le fichier quotidien de l'agent seront inscrits ;
    en phase 1b, toutes les nouveautés du fichier brut le sont.
    """
    vus = etat.setdefault("vus", {})
    empreintes = brut.get("empreintes") or {}
    horodatage = maintenant_iso()
    modifies = 0
    for e in brut.get("nouveautes", []):
        entree = vus.get(e["id"])
        empreinte = e.get("empreinte") or empreintes.get(e["id"])
        if entree is None:
            vus[e["id"]] = {"date_publication": e.get("date_publication"), "vu_le": horodatage, "source_id": e.get("source_id")}
            if empreinte:
                vus[e["id"]]["empreinte"] = empreinte
            modifies += 1
        elif empreinte and entree.get("empreinte") != empreinte:
            entree["empreinte"] = empreinte
            entree["revise_le"] = horodatage
            modifies += 1
    for ident in brut.get("ignores", []):
        if ident not in vus:
            vus[ident] = {"date_publication": None, "vu_le": horodatage, "source_id": None, "ignore": True}
            if ident in empreintes:
                vus[ident]["empreinte"] = empreintes[ident]
            modifies += 1
    etat["version"] = VERSION_ETAT
    etat["maj_le"] = horodatage
    etat["vus"] = dict(sorted(vus.items()))
    return etat, modifies

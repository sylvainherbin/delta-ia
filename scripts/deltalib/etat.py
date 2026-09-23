"""État `state/<perimetre>.json` : identifiants déjà vus. Détection des nouveautés et validation."""

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

    - déjà vu (id dans l'état) : ni l'un ni l'autre ;
    - hors fenêtre (`fenetre_depuis` fourni et date absente ou antérieure) : ignoré, mais retenu pour que
      `--valider` l'inscrive dans l'état ;
    - sinon : nouveauté.
    """
    vus = etat.get("vus", {})
    nouveautes: list[Element] = []
    ignores: list[str] = []
    deja: set[str] = set()
    for e in elements:
        if e.id in vus or e.id in deja:
            continue
        deja.add(e.id)
        if fenetre_depuis is not None:
            if e.date_publication is None or date.fromisoformat(e.date_publication) < fenetre_depuis:
                ignores.append(e.id)
                continue
        nouveautes.append(e)
    nouveautes.sort(key=lambda e: (e.date_publication or "", e.source_id, e.id), reverse=True)
    return nouveautes, sorted(ignores)


def valider(etat: dict, brut: dict) -> tuple[dict, int]:
    """Fait avancer l'état à partir du fichier des nouveautés en attente. Retourne (état, nb ajoutés)."""
    vus = etat.setdefault("vus", {})
    horodatage = maintenant_iso()
    ajoutes = 0
    for e in brut.get("nouveautes", []):
        if e["id"] not in vus:
            vus[e["id"]] = {"date_publication": e.get("date_publication"), "vu_le": horodatage, "source_id": e.get("source_id")}
            ajoutes += 1
    for ident in brut.get("ignores", []):
        if ident not in vus:
            vus[ident] = {"date_publication": None, "vu_le": horodatage, "source_id": None, "ignore": True}
            ajoutes += 1
    etat["version"] = VERSION_ETAT
    etat["maj_le"] = horodatage
    etat["vus"] = dict(sorted(vus.items()))
    return etat, ajoutes

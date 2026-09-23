"""Chargement et validation de `sources.yaml`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .modeles import PERIMETRES, PRODUITS, STATUTS, STATUTS_ACTIFS, TYPES


@dataclass
class Source:
    id: str
    perimetre: str
    produit: str
    type: str
    url: str
    statut: str
    officielle: bool = False
    note: str = ""
    options: dict = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.statut in STATUTS_ACTIFS


class ErreurConfiguration(Exception):
    pass


def _valider(s: Source) -> None:
    if s.perimetre not in PERIMETRES:
        raise ErreurConfiguration(f"{s.id}: perimetre inconnu {s.perimetre!r}")
    if s.produit not in PRODUITS:
        raise ErreurConfiguration(f"{s.id}: produit inconnu {s.produit!r}")
    if s.type not in TYPES:
        raise ErreurConfiguration(f"{s.id}: type inconnu {s.type!r}")
    if s.statut not in STATUTS:
        raise ErreurConfiguration(f"{s.id}: statut inconnu {s.statut!r}")
    if not s.url.startswith(("http://", "https://")):
        raise ErreurConfiguration(f"{s.id}: url invalide {s.url!r}")
    if not isinstance(s.options, dict):
        raise ErreurConfiguration(f"{s.id}: options doit être un dictionnaire")


def charger_sources(chemin: str | Path) -> list[Source]:
    with open(chemin, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    brutes = doc.get("sources")
    if not isinstance(brutes, list) or not brutes:
        raise ErreurConfiguration(f"{chemin}: clé `sources` absente ou vide")
    sources: list[Source] = []
    vus: set[str] = set()
    for b in brutes:
        champs = {k: b.get(k) for k in ("id", "perimetre", "produit", "type", "url", "statut")}
        manquants = [k for k, v in champs.items() if v in (None, "")]
        if manquants:
            raise ErreurConfiguration(f"source {b.get('id', '?')}: champs manquants {manquants}")
        s = Source(**champs, officielle=bool(b.get("officielle", False)), note=b.get("note") or "",
                   options=b.get("options") or {})
        _valider(s)
        if s.id in vus:
            raise ErreurConfiguration(f"identifiant de source en double : {s.id}")
        vus.add(s.id)
        sources.append(s)
    return sources


def sources_du_perimetre(sources: list[Source], perimetre: str, actives_seulement: bool = True) -> list[Source]:
    return [s for s in sources if s.perimetre == perimetre and (s.active or not actives_seulement)]
